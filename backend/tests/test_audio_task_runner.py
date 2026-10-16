"""音频（TTS）任务服务层测试。

覆盖评审指出的「音频链路零覆盖」缺口，重点是有回归价值的三件事：

- `_resolve_audio_target`：`dialog_line_id` 是权威挂载目标，文本 / 说话角色 / 分镜自动带出；
- `_resolve_audio_voice`：显式音色优先，其次回落角色卡默认音色（R-08，每角色一个音色）；
- `_validate_audio_request`：请求期前置校验，不再「先 201、任务随后必然失败」（R-20）；
- `_attach_audio_to_target`：分镜级与台词行级音频挂载写回。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.contracts.audio_generation import AudioGenerationResult
from app.models.studio_assets import Actor, Character
from app.models.studio_shots import Shot, ShotDialogLine
from app.services.studio import audio_task_runner as runner
from app.services.studio.audio_task_runner import (
    _attach_audio_to_target,
    _resolve_audio_target,
    _resolve_audio_voice,
    _validate_audio_request,
)

PROVIDER = "compshare_model_api"
MODEL = "IndexTTS-2.5"


class _EmptyScalars:
    """替身查询结果的 `.scalars()` 返回值：本测试不维护 GenerationTaskLink 表。"""

    def first(self):  # noqa: ANN201
        return None


class _EmptyExecuteResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _FakeAudioDB:
    """最小 DB 替身：只实现被测代码用到的 `get` 与 `execute`。"""

    def __init__(
        self,
        *,
        dialog_lines: dict | None = None,
        characters: dict | None = None,
        shots: dict | None = None,
        actors: dict | None = None,
    ) -> None:
        self.dialog_lines = dict(dialog_lines or {})
        self.characters = dict(characters or {})
        self.shots = dict(shots or {})
        self.actors = dict(actors or {})

    async def get(self, model, entity_id):  # noqa: ANN001, ANN201
        if model is ShotDialogLine:
            return self.dialog_lines.get(entity_id)
        if model is Character:
            return self.characters.get(entity_id)
        if model is Shot:
            return self.shots.get(entity_id)
        if model is Actor:
            return self.actors.get(entity_id)
        return None

    async def execute(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
        return _EmptyExecuteResult()


def _line(
    *,
    line_id: int = 1,
    text: str = "你好，我叫林晚。",
    speaker: str | None = "char-1",
    shot_detail_id: str = "shot-1",
    emotion: str = "愤怒",
) -> ShotDialogLine:
    return ShotDialogLine(
        id=line_id,
        shot_detail_id=shot_detail_id,
        index=0,
        text=text,
        speaker_character_id=speaker,
        emotion=emotion,
    )


# --------------------------------------------------------------------------- #
# _resolve_audio_target：挂载目标推导
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_audio_target_without_text_or_dialog_line_raises_422() -> None:
    db = _FakeAudioDB()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_audio_target(
            db,
            text=None,
            dialog_line_id=None,
            shot_id=None,
            relation_type="",
            relation_entity_id="",
            speaker_character_id=None,
        )

    assert exc_info.value.status_code == 422
    assert "text is required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_resolve_audio_target_blank_text_raises_422() -> None:
    db = _FakeAudioDB()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_audio_target(
            db,
            text="   ",
            dialog_line_id=None,
            shot_id=None,
            relation_type="",
            relation_entity_id="",
            speaker_character_id=None,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_audio_target_dialog_line_is_authoritative() -> None:
    """只传 dialog_line_id 时，文本 / 说话角色 / 分镜都必须自动带出。"""
    line = _line(line_id=7, text="台词内容", speaker="char-9", shot_detail_id="shot-3")
    db = _FakeAudioDB(dialog_lines={7: line})

    text, shot_id, relation_type, relation_entity_id, speaker, emotion = await _resolve_audio_target(
        db,
        text=None,
        dialog_line_id=7,
        shot_id=None,
        relation_type="standalone",
        relation_entity_id="stale",
        speaker_character_id=None,
    )

    assert text == "台词内容"
    assert shot_id == "shot-3"
    assert speaker == "char-9"
    # F：台词行的 emotion 自动带给 TTS
    assert emotion == "愤怒"
    # 即使调用方给了 standalone/stale，也必须被台词行覆盖，避免挂错目标。
    assert relation_type == "dialog_line"
    assert relation_entity_id == "7"


@pytest.mark.asyncio
async def test_resolve_audio_target_dialog_line_not_found_raises_404() -> None:
    db = _FakeAudioDB()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_audio_target(
            db,
            text=None,
            dialog_line_id=999999,
            shot_id=None,
            relation_type="",
            relation_entity_id="",
            speaker_character_id=None,
        )

    assert exc_info.value.status_code == 404
    assert "ShotDialogLine not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_resolve_audio_target_defaults_to_shot_then_standalone() -> None:
    db = _FakeAudioDB()

    _, shot_id, relation_type, relation_entity_id, _, _ = await _resolve_audio_target(
        db,
        text="  你好  ",
        dialog_line_id=None,
        shot_id="shot-1",
        relation_type="",
        relation_entity_id="",
        speaker_character_id=None,
    )
    assert (relation_type, relation_entity_id, shot_id) == ("shot", "shot-1", "shot-1")

    _, shot_id, relation_type, relation_entity_id, _, _ = await _resolve_audio_target(
        db,
        text="你好",
        dialog_line_id=None,
        shot_id=None,
        relation_type="",
        relation_entity_id="",
        speaker_character_id=None,
    )
    assert (relation_type, relation_entity_id, shot_id) == ("standalone", "", None)


# --------------------------------------------------------------------------- #
# _resolve_audio_voice：每角色一个音色
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_audio_voice_prefers_explicit_voice() -> None:
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1", voice_id="from-character")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice="explicit-voice",
        voice_source="preset",
        speaker_character_id="char-1",
    )

    assert (voice, source) == ("explicit-voice", "preset")


@pytest.mark.asyncio
async def test_resolve_audio_voice_falls_back_to_character_config() -> None:
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1", voice_id="  char-voice  ", voice_source="custom")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert voice == "char-voice"
    assert source == "custom"


@pytest.mark.asyncio
async def test_resolve_audio_voice_blank_character_voice_is_treated_as_unset() -> None:
    db = _FakeAudioDB(characters={"char-1": Character(id="char-1", voice_id="   ")})

    voice, _ = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert voice is None


@pytest.mark.asyncio
async def test_resolve_audio_voice_returns_none_when_character_missing() -> None:
    db = _FakeAudioDB()

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="missing",
    )

    assert (voice, source) == (None, None)


# --------------------------------------------------------------------------- #
# _resolve_audio_voice：角色未配音色时回退到演员（sql/019-add-actor-voice.sql）
#
# 用户需求 m08247：「角色和演员都要，演员第一优先级」——演员音色是「这个人」的默认音色，
# 同一演员复用到不同角色时不必重复配置；角色音色是针对具体角色的覆盖项，故角色优先于演员。
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_audio_voice_falls_back_to_actor_config() -> None:
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1", actor_id="actor-1")},
        actors={"actor-1": Actor(id="actor-1", voice_id="  actor-voice  ", voice_source="preset")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert voice == "actor-voice"
    assert source == "preset"


@pytest.mark.asyncio
async def test_resolve_audio_voice_prefers_character_voice_over_actor() -> None:
    """角色级音色是覆盖项：角色有音色时不再看演员。"""
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1", actor_id="actor-1", voice_id="char-voice")},
        actors={"actor-1": Actor(id="actor-1", voice_id="actor-voice")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert (voice, source) == ("char-voice", None)


@pytest.mark.asyncio
async def test_resolve_audio_voice_without_actor_link_returns_none() -> None:
    """角色没绑演员（本项目 6 个角色的现状）：保持未解析，交给 _validate_audio_request 报 422。"""
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1")},
        actors={"actor-1": Actor(id="actor-1", voice_id="actor-voice")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert (voice, source) == (None, None)


@pytest.mark.asyncio
async def test_resolve_audio_voice_blank_actor_voice_is_treated_as_unset() -> None:
    db = _FakeAudioDB(
        characters={"char-1": Character(id="char-1", actor_id="actor-1")},
        actors={"actor-1": Actor(id="actor-1", voice_id="   ")},
    )

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert (voice, source) == (None, None)


@pytest.mark.asyncio
async def test_resolve_audio_voice_missing_actor_row_returns_none() -> None:
    """角色绑了一个已被删除的演员 ID：不崩、保持未解析。"""
    db = _FakeAudioDB(characters={"char-1": Character(id="char-1", actor_id="actor-gone")})

    voice, source = await _resolve_audio_voice(
        db,
        voice=None,
        voice_source=None,
        speaker_character_id="char-1",
    )

    assert (voice, source) == (None, None)


# --------------------------------------------------------------------------- #
# _validate_audio_request：R-20 请求期前置校验
# --------------------------------------------------------------------------- #


def _validate(**overrides) -> None:  # noqa: ANN003
    kwargs: dict = {
        "provider": PROVIDER,
        "model_name": MODEL,
        "text": "你好",
        "voice": "male-qn-qingse",
        "voice_source": None,
        "language": None,
        "speed": None,
        "emotion": None,
        "audio_format": None,
    }
    kwargs.update(overrides)
    _validate_audio_request(**kwargs)


def test_validate_audio_request_accepts_valid_request() -> None:
    _validate()


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"text": "啊" * 5001}, "text must be <="),
        ({"speed": 99.0}, "speed must be <="),
        ({"speed": 0.01}, "speed must be >="),
        ({"voice": None}, "voice is required"),
        ({"voice": "v", "voice_source": "custom"}, "voice_source=custom is not supported"),
    ],
)
def test_validate_audio_request_rejects_invalid_input(overrides: dict, needle: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate(**overrides)

    assert exc_info.value.status_code == 422
    assert needle in exc_info.value.detail


def test_validate_audio_request_reports_text_length_before_voice_requirement() -> None:
    """顺序护栏：文本超长必须优先于「缺音色」报出，否则用户看不到真正的问题。"""
    with pytest.raises(HTTPException) as exc_info:
        _validate(text="啊" * 5001, voice=None)

    assert exc_info.value.status_code == 422
    assert "text must be <=" in exc_info.value.detail


# --------------------------------------------------------------------------- #
# _attach_audio_to_target：分镜级 / 台词行级挂载写回
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_attach_audio_to_shot_writes_generated_audio_file_id() -> None:
    shot = Shot(id="shot-1")
    db = _FakeAudioDB(shots={"shot-1": shot})

    await _attach_audio_to_target(
        db, relation_type="shot", relation_entity_id="shot-1", file_id="file-a"
    )

    assert shot.generated_audio_file_id == "file-a"


@pytest.mark.asyncio
async def test_attach_audio_to_dialog_line_writes_generated_audio_file_id() -> None:
    line = _line(line_id=3)
    db = _FakeAudioDB(dialog_lines={3: line})

    await _attach_audio_to_target(
        db, relation_type="dialog_line", relation_entity_id="3", file_id="file-b"
    )

    assert line.generated_audio_file_id == "file-b"


@pytest.mark.asyncio
async def test_attach_audio_to_target_is_noop_for_unknown_target() -> None:
    shot = Shot(id="shot-1")
    line = _line(line_id=3)
    db = _FakeAudioDB(shots={"shot-1": shot}, dialog_lines={3: line})

    # 空目标 / 非数字台词行 ID / 未登记的关系类型 / 目标行不存在：都不许抛异常。
    await _attach_audio_to_target(db, relation_type="shot", relation_entity_id="", file_id="f")
    await _attach_audio_to_target(db, relation_type="dialog_line", relation_entity_id="abc", file_id="f")
    await _attach_audio_to_target(db, relation_type="standalone", relation_entity_id="x", file_id="f")
    await _attach_audio_to_target(db, relation_type="shot", relation_entity_id="missing", file_id="f")
    await _attach_audio_to_target(db, relation_type="dialog_line", relation_entity_id="404", file_id="f")

    assert shot.generated_audio_file_id is None
    assert line.generated_audio_file_id is None


@pytest.mark.asyncio
async def test_persist_generated_audio_attaches_file_to_dialog_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """落库后必须把 files 行挂到台词行上（m01534：分镜要能挂生成好的音频）。"""
    line = _line(line_id=5)
    db = _FakeAudioDB(dialog_lines={5: line})

    async def _fake_create_file(_session, *, url, name, prefix):  # noqa: ANN001, ANN202
        return SimpleNamespace(id="file-x", name=name, storage_key=prefix)

    monkeypatch.setattr(runner, "create_file_from_url_or_b64", _fake_create_file)

    file_obj = await runner.persist_generated_audio(
        db,
        task_id="task-1",
        relation_type="dialog_line",
        relation_entity_id="5",
        result=AudioGenerationResult(url="https://example.com/a.wav"),
    )

    assert file_obj is not None
    assert file_obj.id == "file-x"
    assert line.generated_audio_file_id == "file-x"


@pytest.mark.asyncio
async def test_persist_generated_audio_returns_none_without_url() -> None:
    db = _FakeAudioDB()

    file_obj = await runner.persist_generated_audio(
        db,
        task_id="task-2",
        relation_type="standalone",
        relation_entity_id="",
        # url / b64_data / file_id 至少给一个才构造得出结果；这里刻意只给 file_id，
        # 用来验证「没有可下载 url 时不落 files 行」。
        result=AudioGenerationResult(file_id="file-y"),
    )

    assert file_obj is None
