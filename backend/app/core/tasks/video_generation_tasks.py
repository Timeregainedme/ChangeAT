"""视频生成任务（Task）：对接 OpenAI Videos API、火山方舟内容生成、PIX 与优云智算。

HTTP 细节在 `app.core.integrations`；本模块保留轮询节奏与 BaseTask 契约。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.core.integrations.compshare.video import (
    CompshareVideoApiAdapter,
    video_url_from_task,
)
from app.core.integrations.compshare.client import task_error_message
from app.core.integrations.openai.video import OpenAIVideoApiAdapter
from app.core.integrations.pix.client import is_final
from app.core.integrations.pix.video import PixVideoApiAdapter
from app.core.integrations.volcengine.video import VolcengineVideoApiAdapter
from app.core.contracts.provider import ProviderConfig
from app.core.tasks.registry import resolve_task_adapter
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult
from app.core.task_manager.types import BaseTask

__all__ = [
    "VideoGenerationInput",
    "VideoGenerationResult",
    "AbstractVideoGenerationTask",
    "OpenAIVideoGenerationTask",
    "VolcengineVideoGenerationTask",
    "PixVideoGenerationTask",
    "CompshareVideoGenerationTask",
    "VideoGenerationTask",
]

# 各供应商的轮询节奏与总超时预算（仅在调用方未显式指定时生效）。
_PROVIDER_POLL_INTERVAL_DEFAULTS: dict[str, float] = {
    "pix": 6.0,
    "compshare_model_api": 3.0,
}
_PROVIDER_TOTAL_TIMEOUT_DEFAULTS: dict[str, float] = {
    "pix": 1800.0,
    "compshare_model_api": 1800.0,
}
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_TOTAL_TIMEOUT_S = 120.0


def default_poll_interval_s(provider: str) -> float:
    return _PROVIDER_POLL_INTERVAL_DEFAULTS.get(provider, DEFAULT_POLL_INTERVAL_S)


def default_total_timeout_s(provider: str) -> float:
    return _PROVIDER_TOTAL_TIMEOUT_DEFAULTS.get(provider, DEFAULT_TOTAL_TIMEOUT_S)


class AbstractVideoGenerationTask(BaseTask, ABC):
    """视频生成任务基类：公共状态与 run/status/is_done/get_result。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        self._cfg = provider_config
        self._input = input_
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._provider_task_id: str | None = None
        self._result: VideoGenerationResult | None = None
        self._error: str = ""

    async def _sleep_poll(self) -> None:
        await asyncio.sleep(self._poll_interval_s)

    @abstractmethod
    async def _create_task(self) -> None:
        """发起供应商创建任务请求，并设置 self._provider_task_id。"""

    @abstractmethod
    async def _poll_and_get_result(self) -> VideoGenerationResult:
        """轮询至终态并解析为 VideoGenerationResult。"""

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
            "task": "video_generation",
            "provider": self._cfg.provider,
            "provider_task_id": self._provider_task_id,
            "done": await self.is_done(),
            "has_result": self._result is not None,
            "error": self._error,
            "status": self._result.status if self._result else None,
        }

    async def is_done(self) -> bool:  # type: ignore[override]
        return self._result is not None or bool(self._error)

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return self._result


class OpenAIVideoGenerationTask(AbstractVideoGenerationTask):
    """OpenAI Videos：adapter 负责 HTTP，Task 负责轮询间隔。"""

    def __init__(
        self,
        *,
        adapter: OpenAIVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or OpenAIVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_video(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        video_id = self._provider_task_id or ""
        if not video_id:
            raise RuntimeError("OpenAI poll missing provider task id")

        base_url = (self._cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        status_val = ""
        while True:
            meta = await self._adapter.get_video(
                cfg=self._cfg,
                video_id=video_id,
                timeout_s=self._timeout_s,
            )
            status_val = str(meta.get("status") or "")
            if status_val in ("completed", "failed"):
                if status_val == "failed":
                    raise RuntimeError(f"OpenAI video failed: {meta.get('error')!r}")
                break
            await self._sleep_poll()

        return VideoGenerationResult(
            url=f"{base_url}/videos/{video_id}/content",
            file_id=None,
            provider_task_id=video_id,
            provider="openai",
            status=status_val or "completed",
        )


class VolcengineVideoGenerationTask(AbstractVideoGenerationTask):
    """火山内容生成任务：adapter 负责 HTTP，Task 负责轮询。"""

    def __init__(
        self,
        *,
        adapter: VolcengineVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or VolcengineVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_contents_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Volcengine poll missing provider task id")

        base_url = (self._cfg.base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        status_val = ""
        video_url: str | None = None
        while True:
            meta = await self._adapter.get_contents_task(
                cfg=self._cfg,
                task_id=task_id,
                timeout_s=self._timeout_s,
            )
            status_val = str(meta.get("status") or "")
            content = meta.get("content") or {}
            if isinstance(content, dict):
                vu = content.get("video_url")
                if isinstance(vu, str) and vu:
                    video_url = vu
            if status_val in ("succeeded", "failed", "cancelled"):
                if status_val != "succeeded":
                    raise RuntimeError(f"Volcengine task not succeeded: status={status_val!r} meta={meta!r}")
                break
            await self._sleep_poll()

        if not video_url:
            video_url = f"{base_url}/contents/generations/tasks/{task_id}"

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="volcengine",
            status=status_val or "succeeded",
        )


class PixVideoGenerationTask(AbstractVideoGenerationTask):
    """PIX 视频生成：`POST /v1/media/generate` 后轮询 `GET /v1/tasks/{id}`。"""

    def __init__(
        self,
        *,
        adapter: PixVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 6.0,
        timeout_s: float = 1800.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or PixVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_media_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=min(self._timeout_s, 120.0),
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("PIX poll missing provider task id")

        deadline = time.monotonic() + self._timeout_s
        payload: dict[str, Any] = {}
        while True:
            payload = await self._adapter.get_task(cfg=self._cfg, task_id=task_id)
            status_val = str(payload.get("status") or "")
            if status_val == "failed":
                reason = payload.get("error") or payload.get("message") or payload
                raise RuntimeError(f"PIX 视频任务失败：{reason}")
            if is_final(payload):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"PIX 视频任务超时：task_id={task_id!r} last_status={status_val!r}"
                )
            await self._sleep_poll()

        output_url = str(payload.get("output_url") or "").strip()
        if not output_url:
            raise RuntimeError(f"PIX 视频任务已完成但未返回 output_url：{payload!r}")

        return VideoGenerationResult(
            url=output_url,
            file_id=None,
            provider_task_id=task_id,
            provider="pix",
            status=str(payload.get("status") or "succeeded"),
        )


def _compshare_terminal_error(status_val: str, task: dict[str, Any]) -> str:
    mapping = {
        "failed": "MiniMax H3 生成失败",
        "cancelled": "MiniMax H3 任务已被取消",
        "blocked": "MiniMax H3 任务被审核拦截",
    }
    label = mapping.get(status_val, "MiniMax H3 任务异常")
    return f"{label}（status={status_val!r}）：{task_error_message(task)}"


class CompshareVideoGenerationTask(AbstractVideoGenerationTask):
    """优云智算 MiniMax H3：提交后轮询 `GET /minimax/v2/query/video_generation/{id}`。"""

    def __init__(
        self,
        *,
        adapter: CompshareVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 1800.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or CompshareVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_video_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=min(self._timeout_s, 120.0),
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Compshare poll missing provider task id")

        deadline = time.monotonic() + self._timeout_s
        status_val = ""
        video_url = ""
        while True:
            task = await self._adapter.get_video_task(cfg=self._cfg, task_id=task_id)
            status_val = str(task.get("status") or "").lower()
            if status_val == "succeeded":
                video_url = video_url_from_task(task)
                if not video_url:
                    raise RuntimeError("MiniMax H3 任务已完成，但没有返回可用的视频地址")
                break
            if status_val in ("failed", "cancelled", "blocked"):
                raise RuntimeError(_compshare_terminal_error(status_val, task))
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"MiniMax H3 视频任务超时：task_id={task_id!r} last_status={status_val!r}"
                )
            await self._sleep_poll()

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="compshare_model_api",
            status=status_val or "succeeded",
        )


class VideoGenerationTask(BaseTask):
    """按 provider 分派到 OpenAI / 火山 / PIX / 优云智算实现。

    `poll_interval_s` 与 `timeout_s` 省略时按 provider 取默认值
    （PIX 6s/30min、优云智算 3s/30min、其余 2s/120s）。
    """

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float | None = None,
        timeout_s: float | None = None,
    ) -> None:
        from app.bootstrap import bootstrap_all_registries

        bootstrap_all_registries()
        if poll_interval_s is None:
            poll_interval_s = default_poll_interval_s(provider_config.provider)
        if timeout_s is None:
            timeout_s = default_total_timeout_s(provider_config.provider)
        factory = resolve_task_adapter("video_generation", provider_config.provider)
        self._impl: AbstractVideoGenerationTask = factory(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )  # type: ignore[assignment]

    @staticmethod
    def _build_openai_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> AbstractVideoGenerationTask:
        return OpenAIVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_volcengine_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 2.0,
        timeout_s: float = 120.0,
    ) -> AbstractVideoGenerationTask:
        return VolcengineVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_pix_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 6.0,
        timeout_s: float = 1800.0,
    ) -> AbstractVideoGenerationTask:
        return PixVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_compshare_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 3.0,
        timeout_s: float = 1800.0,
    ) -> AbstractVideoGenerationTask:
        return CompshareVideoGenerationTask(
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

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return await self._impl.get_result()
