"""音频（TTS）生成任务（Task）：对接优云智算 IndexTTS 2.5。

HTTP 细节在 `app.core.integrations.compshare.audio`；本模块保留轮询节奏与 BaseTask 契约。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.core.contracts.audio_generation import AudioGenerationInput, AudioGenerationResult
from app.core.contracts.provider import ProviderConfig
from app.core.integrations.compshare.audio import (
    CompshareAudioApiAdapter,
    audio_url_from_task,
)
from app.core.integrations.compshare.client import task_error_message
from app.core.task_manager.types import BaseTask
from app.core.tasks.registry import resolve_task_adapter

__all__ = [
    "AudioGenerationInput",
    "AudioGenerationResult",
    "AbstractAudioGenerationTask",
    "CompshareAudioGenerationTask",
    "AudioGenerationTask",
]

DEFAULT_AUDIO_POLL_INTERVAL_S = 3.0
DEFAULT_AUDIO_TOTAL_TIMEOUT_S = 1200.0


class AbstractAudioGenerationTask(BaseTask, ABC):
    """音频生成任务基类：公共状态与 run/status/is_done/get_result。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: AudioGenerationInput,
        poll_interval_s: float = DEFAULT_AUDIO_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_AUDIO_TOTAL_TIMEOUT_S,
    ) -> None:
        self._cfg = provider_config
        self._input = input_
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._provider_task_id: str | None = None
        self._result: AudioGenerationResult | None = None
        self._error: str = ""

    async def _sleep_poll(self) -> None:
        await asyncio.sleep(self._poll_interval_s)

    @abstractmethod
    async def _create_task(self) -> None:
        """发起供应商创建任务请求，并设置 self._provider_task_id。"""

    @abstractmethod
    async def _poll_and_get_result(self) -> AudioGenerationResult:
        """轮询至终态并解析为 AudioGenerationResult。"""

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        try:
            await self._create_task()
            self._result = await self._poll_and_get_result()
            if self._result is not None:
                self._provider_task_id = self._result.provider_task_id
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            self._result = None
        return None

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "task": "audio_generation",
            "provider": self._cfg.provider,
            "provider_task_id": self._provider_task_id,
            "done": await self.is_done(),
            "has_result": self._result is not None,
            "error": self._error,
            "status": self._result.status if self._result else None,
        }

    async def is_done(self) -> bool:  # type: ignore[override]
        return self._result is not None or bool(self._error)

    async def get_result(self) -> AudioGenerationResult | None:  # type: ignore[override]
        return self._result


class CompshareAudioGenerationTask(AbstractAudioGenerationTask):
    """优云智算 IndexTTS 2.5：提交后轮询 `GET /audio/v1/speech/jobs/{id}`。"""

    def __init__(
        self,
        *,
        adapter: CompshareAudioApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: AudioGenerationInput,
        poll_interval_s: float = DEFAULT_AUDIO_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_AUDIO_TOTAL_TIMEOUT_S,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or CompshareAudioApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_speech_job(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=min(self._timeout_s, 120.0),
        )

    async def _poll_and_get_result(self) -> AudioGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Compshare audio poll missing provider task id")

        deadline = time.monotonic() + self._timeout_s
        status_val = ""
        audio_url = ""
        while True:
            task = await self._adapter.get_speech_job(cfg=self._cfg, task_id=task_id)
            status_val = str(task.get("status") or "").lower()
            if status_val == "succeeded":
                audio_url = audio_url_from_task(task)
                if not audio_url:
                    raise RuntimeError("IndexTTS 2.5 任务已完成，但没有返回可用的音频地址")
                break
            if status_val in ("failed", "cancelled"):
                label = "IndexTTS 2.5 生成失败" if status_val == "failed" else "IndexTTS 2.5 任务已被取消"
                raise RuntimeError(f"{label}（status={status_val!r}）：{task_error_message(task)}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"IndexTTS 2.5 语音任务超时：task_id={task_id!r} last_status={status_val!r}"
                )
            await self._sleep_poll()

        return AudioGenerationResult(
            url=audio_url,
            provider="compshare_model_api",
            provider_task_id=task_id,
            mime_type="audio/wav",
            status=status_val or "succeeded",
        )


class AudioGenerationTask(BaseTask):
    """按 provider 分派到语音实现；对外构造函数与图片/视频任务保持一致。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: AudioGenerationInput,
        poll_interval_s: float | None = None,
        timeout_s: float | None = None,
    ) -> None:
        from app.bootstrap import bootstrap_all_registries

        bootstrap_all_registries()
        factory = resolve_task_adapter("audio_generation", provider_config.provider)
        self._impl: AbstractAudioGenerationTask = factory(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s or DEFAULT_AUDIO_POLL_INTERVAL_S,
            timeout_s=timeout_s or DEFAULT_AUDIO_TOTAL_TIMEOUT_S,
        )  # type: ignore[assignment]

    @staticmethod
    def _build_compshare_impl(
        *,
        provider_config: ProviderConfig,
        input_: AudioGenerationInput,
        poll_interval_s: float = DEFAULT_AUDIO_POLL_INTERVAL_S,
        timeout_s: float = DEFAULT_AUDIO_TOTAL_TIMEOUT_S,
    ) -> AbstractAudioGenerationTask:
        return CompshareAudioGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        return await self._impl.run(*args, **kwargs)

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return await self._impl.status()

    async def is_done(self) -> bool:  # type: ignore[override]
        return await self._impl.is_done()

    async def get_result(self) -> AudioGenerationResult | None:  # type: ignore[override]
        return await self._impl.get_result()
