---
title: "角色与演员音色链路"
description: "当前真实生效的配音音色模型：演员默认音色 → 角色覆盖 → 显式入参的三级解析、供应商音色列表接口，以及对应的前端编辑入口。"
weight: 15
---

> 本文属于“当前架构”文档，描述当前真实生效的实现。

## 背景

短剧配音要求同一个「人」在整部剧（乃至跨剧集复用同一演员）里保持同一声线。若音色只能挂在角色上，同一演员演十个角色就要重复配十次，且没有「这个人本来的声音」这一层概念。因此当前实现是**两级音色 + 显式覆盖**：

- **演员音色** = 某个「人」的默认音色（第一优先级来源，复用时不重复配置）。
- **角色音色** = 针对具体角色的覆盖项（有对白的角色才需要）。

## 数据模型

三列在两个表上口径完全一致，都是 `NULL` 表示未指定：

| 列 | characters | actors | 语义 |
| --- | --- | --- | --- |
| `voice_id` | 迁移 016 | 迁移 019 | 供应商侧音色 ID（`varchar(64)`，索引 `ix_<table>_voice_id`） |
| `voice_source` | 迁移 016 | 迁移 019 | 音色来源 `preset` / `custom`（`varchar(32)`；为空时按模型名推断） |
| `voice_description` | 迁移 016 / 018 | 迁移 019 | 音色描述（年龄段/声线/气质/语速），由剧本提取产出，供配音选型参考 |

- `actors` 的三列由 `backend/sql/019-add-actor-voice.sql` 建立（幂等：先经 `information_schema` 判定再执行，可被 compose 重复执行）。
- `voice_description` 在 ORM 侧是 `Text, nullable=False, default=""`，DDL 侧同步收紧为 `TEXT NOT NULL`（MySQL 不允许 TEXT 默认值，空串只能由 SQLAlchemy 客户端补）。迁移 018 对 `characters` 做过同样的收紧，`actors` 在 019 内一次完成（`ADD NULL` → 回填 → `MODIFY NOT NULL`）。
- 迁移 019 会建索引 `ix_actors_voice_id`，与 ORM 的 `index=True`（SQLAlchemy 默认命名）对齐。

契约侧：`AudioVoiceSource` 定义在 `app/core/contracts/audio_generation.py`，被 schema 直接复用。

## 音色解析顺序

`app/services/studio/audio_task_runner.py::_resolve_audio_voice`：

```text
显式传入的 voice（调用方最清楚，最高优先级）
  → characters.voice_id（角色级覆盖）
    → 该角色所绑演员的 actors.voice_id（演员级默认）
      → 都没有：返回 (None, voice_source)，由 _validate_audio_request 统一报 422
```

- 「显式入参优先」保证调用方（如分镜台词配音）能指定具体音色而不被实体配置覆盖。
- `voice_source` **始终跟随实际取到音色的那一层**：只有调用方没显式给 `voice_source` 时才回填，避免覆盖调用方的显式指定。
- 角色未绑定演员（`actor_id` 为空）或演员行不存在时直接返回未解析，不做名字匹配。

## 供应商音色列表

接口：`GET /api/v1/studio/audio-tasks/voices?model_id=<id>&kind=preset|custom`

- 响应：`ApiResponse[list[VoiceItem]]`，`VoiceItem = {voice_id, name, language, raw}`（取值 `row.get("voice_id") or row.get("id") or row.get("voice")`）。
- **只有 `compshare_model_api` 支持**：其它供应商抛 `HTTPException(400, "Provider ... does not expose a voice list API")`。因此前端必须把该 400 当作**预期降级**而非故障。

## 前端入口

- 复用组件 `front/src/pages/aiStudio/components/VoiceSelectField.tsx`：`value` 是供应商侧 `voice_id`（`string | null`，**不是对象**），`onChange` 回传 `VoiceChoice = {voice_id, voice_source}`。
  - 供应商列表里没有的**已保存** `voice_id` 会以 `__saved__:` 前缀补一条选项（label `已保存：<id>`），避免用户因为「看不见」而误把已有配置清空。
  - 拉取失败时降级为「仅显示已保存音色」并给出说明，不阻塞编辑。
- 角色编辑表单（`tabs/RolesTab.tsx`）：音色类型（preset/custom）+ `VoiceSelectField` + 音色描述。演员下拉下方常驻说明：**系统不做名字匹配**，同名演员也要显式绑定；同名只作为「一键绑定」建议由用户确认。
- 演员编辑表单（`assets/components/ActorEntityFormModal.tsx`）：同样的三字段，文案说明「角色未单独配置音色时，配音将回退使用该演员音色」。
- 独立页面「音色管理」（`front/src/pages/aiStudio/voice/VoiceManager.tsx`，路由 `/voices`，主菜单在「模型管理」之后）：三个页签 —— ① 供应商音色列表（含「已被角色直接引用」反查）；② 演员默认音色（逐行 `VoiceSelectField`，直接 `PATCH` 演员）；③ 角色生效音色（显示「角色音色（覆盖演员）」或「回退演员「X」的音色」，两者都没有时明确警告「配音时会直接报错」）。

## 写接口语义

演员与角色的音色都通过实体更新接口写入：`PATCH /api/v1/studio/entities/{entity_type}/{entity_id}`。

- `entity_crud.py` 用 `spec.update_model.model_validate(body).model_dump(exclude_unset=True)`，因此**请求体里显式出现 `voice_id: null` 才会真正清空该列**；字段缺席表示「不改动」。
- `CharacterUpdate` / `ActorUpdate` 都**不继承**各自的 Base、显式声明全部可改字段：漏声明会让该字段在 PATCH 时被静默忽略（评审 C-3 中 `voice_description` 曾因此改不动）。
