# 短剧生产 SOP — Jellyfish 工作台

> 适用范围：40–150 集竖屏短剧（9:16）。
> 本文所有页面、路由、接口与判定规则均来自**当前仓库真实代码**（已逐项核对），
> 与实现不一致处在本版第六节「能力边界」中显式标注。
> 配套文档：`审阅报告-426f9ab.md`、`供应商配置.md`、`site/content/docs/architecture/`。

---

## 0. 总览

### 0.1 一条主线

```text
建项目 → 建章节 → 录入原文 → 提取分镜 → 逐镜提取确认 → 资产化（建实体 + 出参考图）
   → 分镜准备就绪(ready) → 关键帧 → 视频 → 配音 → 成片
```

代码侧的主业务链路定义（[project-structure.md:22](site/content/docs/architecture/project-structure.md)）：

```text
项目 -> 章节 -> 分镜 -> 资产 / 帧图 -> 时间线
```

### 0.2 章节状态机（唯一权威，前端据此推荐下一步）

来源：[chapterPreparation.tsx:19-59](front/src/pages/aiStudio/project/ProjectWorkbench/chapterPreparation.tsx#L19-L59)

| 状态 key | 显示 | 触发条件 | 推荐动作 |
|---|---|---|---|
| `edit_raw` | 待录入原文 | `chapter.rawText` 为空 | 编辑原文 |
| `extract_shots` | 待提取分镜 | 有原文、分镜数 = 0 | 提取分镜 |
| `prepare_shots` | 待准备镜头 | 有分镜、章节状态非 shooting/done | 进入分镜工作室 |
| `shoot` | 可进入拍摄 | 有分镜且 `chapter.status ∈ {shooting, done}` | 进入拍摄 |

### 0.3 分镜状态机（`shot.status`）

来源：[shot-status-flow.md:57-79](site/content/docs/architecture/shot-status-flow.md#L57-L79)。只有两个正式状态，**由后端统一重算，前端不得自行推导**：

1. `skip_extraction = true` → `ready`
2. 从未提取过 → `pending`
3. 提取过但无任何候选 → `ready`
4. 所有资产候选 + 对白候选都已处理完 → `ready`
5. 其他 → `pending`

其中：

- 资产候选「处理完」= `candidate_status ∈ {linked, ignored}`
- 对白候选「处理完」= `candidate_status ∈ {accepted, ignored}`
- **只要还有任意一条 pending，镜头就卡在 pending**
- 镜头无任何对白候选 **不** 阻塞 ready

> ⚠️ 前置条件：`Shot` 与 `ShotDetail` 一对一、同主键。**没有 `shot_details` 行的分镜永远停在 pending**，且 `skip-extraction` / `preparation-state` 会直接报错。新建分镜必须走 `shot_details.build_default_shot_detail()`（[shot-status-flow.md:81-95](site/content/docs/architecture/shot-status-flow.md#L81-L95)）。

### 0.4 页面地图（真实路由）

来源：[App.tsx:25-45](front/src/App.tsx#L25-L45)

| 路由 | 页面 | 职责 |
|---|---|---|
| `/projects` | `ProjectLobby` | 项目大厅，含「推荐下一步」 |
| `/projects/:projectId` | `ProjectWorkbench` | 项目工作台（Dashboard/章节/角色/演员/场景/道具/文件/设置） |
| `/projects/:projectId/chapters/:chapterId/shots` | `ChapterShotsPage` | **章节分镜列表 + 一键提取分镜** |
| `/projects/:projectId/chapters/:chapterId/shots/:shotId/edit` | `ChapterShotEditPage` | **单镜头准备台**（提取与确认） |
| `/projects/:projectId/chapters/:chapterId/studio` | `ChapterStudio` | **章节生成工作台**（关键帧/视频/批量） |
| `/projects/:projectId/editor` | `VideoEditor` | 成片与时间线 |
| `/assets`、`/assets/{actor\|scene\|prop\|costume}/:id/edit` | 资产库与资产编辑页 | 资产生成与抽卡 |
| `/models`、`/settings`、`/prompts` | 模型/设置/提示词模板 | 供应商、参数、Agent 模板 |

> `prep` 与 `prep-drafts` 两个旧路由已**重定向到 `../shots`**（[App.tsx:31-35](front/src/App.tsx#L31-L35)）。

---

## 1. 开工前：环境与参数（一次性）

### 1.1 启动与健康检查

```bash
docker compose -f deploy/compose/docker-compose.yml up -d
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health   # 期望 200
```

- 后端 `:8000`，前端工作台 `:7788`（`compose-front-1` 映射 80）。
- **后端代码烘进镜像，无 bind mount**：任何后端改动必须 `build backend celery-worker` 再 `up -d`，否则不生效。

### 1.2 供应商与三个默认模型（必配，否则预检不过）

在 `/models` 配置供应商 API Key，并把默认模型指到：

| 用途 | 供应商 | 模型 | 本项目参数 |
|---|---|---|---|
| 文本 | — | 项目自选 | — |
| 图片 | PIX | `gpt-image-2.5-flare` | 出图 **1K** |
| 视频 | 优云智算 / PIX | `MiniMax-H3` | 出片 **768p** |
| 音频 | 优云智算 | `IndexTTS-2.5` / `IndexTTS-2.5-custom` | **每个角色一个音色** |

校验（只读）：

```bash
curl -s http://127.0.0.1:8000/api/v1/llm/image-generation-options
curl -s http://127.0.0.1:8000/api/v1/llm/video-generation-options
curl -s http://127.0.0.1:8000/api/v1/llm/audio-generation-options
curl -s http://127.0.0.1:8000/api/v1/llm/providers/supported   # 期望 6 个供应商
```

### 1.3 项目级参数（建项目时就定死）

- **画幅 9:16**：落到 `Project.default_video_ratio = "9:16"`，不要再依赖分镜级覆盖。
- `style`（题材）与 `visual_style` 是**中文枚举**，传英文值返回 422：
  - `style`：真人都市 / 真人科幻 / 真人古装 / 动漫科幻 / 动漫3D / 国漫 / 水墨画
  - `visual_style`：现实 / 动漫
- `ProjectCreate` 必填 = `['id', 'name', 'style']`。

### 1.4 开工预检（建议每集开拍前跑一次）

```bash
curl -s http://127.0.0.1:8000/api/v1/studio/projects/<project_id>/production-readiness
```

只读端点，返回 `{ready, checks[], stats{chapters,shots,shots_with_reference_frames,characters,characters_with_voice}}`。
检查项 10 个：`text_model_ready` / `image_model_ready` / `video_model_ready` / `audio_model_ready` /
`project_style_ready` / `image_output_ready` / `video_ratio_ready` / `character_voice_ready` /
`shot_reference_frames_ready` / `extraction_confirmed_ready`。

**未配齐模型时这里就会红，不要带着红灯往下走。**

---

## 2. 阶段一｜建项目

1. 打开 `/projects` → 新建项目。
2. 填写：`id`、`name`、`style`（中文）、`visual_style`、**`default_video_ratio = 9:16`**。
3. 保存后在 `/models` 复核该项目的默认模型绑定。

> 用户侧准备：**剧本 / 大纲先放进项目文件夹**，再开工（按既定约定，一步一步来）。

---

## 3. 阶段二｜建章节 + 录入原文（`edit_raw`）

1. 进入 `/projects/:projectId` → **章节** Tab。
2. 点「新建章节」。
3. 在章节行点「编辑原文」→ `ChapterRawTextEditorModal` 录入本章剧本原文。
4. 保存后章节状态自动从 `edit_raw` 变为 `extract_shots`。

**验收标准**：章节列表显示「待提取分镜」。

> 一集一章是推荐粒度；40–150 集建议按「每集独立章节」建，便于逐集推进与复用资产。

---

## 4. 阶段三｜提取分镜（`extract_shots`）

1. 进入 `/projects/:projectId/chapters/:chapterId/shots`。
2. 点 **「一键提取分镜」**。
   - 按钮语义：`shots.length === 0` 时为「一键提取分镜」；已有分镜时变为「重新提取需先清空分镜」。
   - 运行中显示「分镜提取中」，可「取消提取」。
3. 后台链路：

```text
POST /api/v1/script-processing/divide-async
  → 分镜写入 shots（每镜同事务写入 shot_details）
```

**验收标准**：分镜列表出现镜头；章节状态变为 `prepare_shots` 或直接 `shoot`。

**坑**：

- 已有分镜时想重新提取，**必须先清空分镜**（提供了批量删除）。
- 提取是异步任务，注意任务中心里是否有失败。

---

## 5. 阶段四｜逐镜提取与确认（`prepare_shots`）

### 5.1 单镜头提取与确认（准备台）

进入 `/projects/:projectId/chapters/:chapterId/shots/:shotId/edit`，这是**单镜头准备台**，负责把镜头推到 `ready`：

```text
POST /api/v1/script-processing/extract-async
  → 资产候选写入 shot_extracted_candidates（pending）
  → 对白候选写入 shot_extracted_dialogue_candidates（pending）
```

然后逐条处理：

- 资产候选 → `linked`（关联到真实实体）或 `ignored`
- 对白候选 → `accepted`（写入 `ShotDialogLine`）或 `ignored`
- 本镜确实不需要提取 → 打开 `skip_extraction`

命令接口：

```text
PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/link
PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/ignore
PATCH /api/v1/studio/shots/{shot_id}/skip-extraction
PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/accept
PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/ignore
GET   /api/v1/studio/shots/{shot_id}/preparation-state
```

聚合读取优先用 `GET /api/v1/studio/shots/{shot_id}/preparation-state`（返回 `shot` / `assets_overview` /
`dialogue_candidates` / `saved_dialogue_lines` / `pending_confirm_count` / `ready_for_generation`）。**不要在
关联/忽略成功后自己拼局部状态**。

**验收标准**：`pending_confirm_count = 0`，`shot.status = ready`。

> 自动回写已就绪：角色/场景/道具/服装关联成功 → 对应候选自动 `linked`；删除关联 → 候选自动退回 `pending`；
> 接受对白 → 自动写 `ShotDialogLine`（[shot-status-flow.md:182-195](site/content/docs/architecture/shot-status-flow.md#L182-L195)）。

### 5.2 一键创建资产（候选 → 真实实体）

**UI 入口（推荐）**：章节分镜列表页（`/projects/:projectId/chapters/:chapterId/shots`）的 **「一键创建资产」** 按钮，
与「一键提取分镜」并列。点一下即处理本章节全部待处理候选，完成后提示 `新建 N / 关联 N / 跳过 N`。
前置条件：该章节至少有分镜已完成「信息提取」（否则提示「没有待处理的提取候选」）。

**API 入口**（等价，脚本化/批量时用）：

按章节批量落库：

```bash
POST /api/v1/studio/shots/extracted-candidates/batch-create-assets
body: { "chapter_id": "<cid>", "types": ["character","scene","prop","costume"] }
```

**`types` 的两种「空」语义不同**（[asset-extraction-oneclick.md:34-38](site/content/docs/architecture/asset-extraction-oneclick.md#L34-L38)）：

- **不传 `types`（`None`）= 不限定类型，处理全部 pending 候选**
- **显式传 `[]` = 一个类型都不处理**，直接返回三个空列表
- 传 `character/scene/prop/costume` 之外的值 → 400

查重口径：character 按 `project_id + name`；scene/prop/costume 通过项目关联表限定项目后按 `name`。
已存在的直接关联，不新建。返回 `{created, linked, skipped}`。

**验收标准**：`created + linked` 覆盖全部候选；`skipped` 为空或已逐条确认原因。

### 5.3 关键概念：演员 vs 角色（不要混）

| | 演员 `Actor` | 角色 `Character` |
|---|---|---|
| 是什么 | **外形素材**（长什么样） | **戏里的身份**（演谁） |
| 归属 | 全局资产，表里无 `project_id` | 项目内，`project_id` 必填 |
| 怎么挂项目 | `ProjectActorLink`（可跨项目复用） | 自带 `project_id` |
| 名字唯一性 | 全局唯一 | **项目内**唯一（跨项目可同名） |
| 内容 | 多视角立绘（`view_count` 决定几个角度，**不含分镜帧**） | 人物文案 |
| 组成 | — | **演员 + 服装 + 道具** |
| 音色 | 无 | **有**（`voice_id` / `voice_source` / `voice_description`） |
| 进镜头 | 不进 | 靠 `ShotCharacterLink` |
| 删除约束 | `RESTRICT`（被角色引用则不可删） | 随项目 `CASCADE` |

代码原话（[studio_assets.py:203](backend/app/models/studio_assets.py#L203)）：**「角色由：Actor（演员） + Costume（服装） + Props（道具）组成」**。

实务含义：

- 一个演员可演多个角色（跨项目复用）；一个角色也可暂不指定演员（`actor_id` 可空）。
- **音色挂在角色上**——同一演员演两个角色，可以是两种声音（一人分饰两角 / 不同年龄段）。
- 演员出的是**定妆图**（多视角），用来锁人物一致性；角色的图槽位是按需补的（角色外观由演员/服装拼出）。

### 5.4 角色卡定死清单（每个角色开工前必须填满）

| 项 | 落在哪 | 说明 |
|---|---|---|
| 脸型 / 发型 / 体型 / 年龄感 | 演员（`Actor`）+ 角色 `description` | 外形真值 |
| 服装 | 角色 `costume_id` | 应用层保证与角色同项目或全局 |
| 道具 | `CharacterPropLink` | 多对多 |
| 音色 | 角色 `voice_id` / `voice_source` | 预设或复刻；**每角色一个** |
| 音色描述 | 角色 `voice_description` | 年龄段/声线/气质/语速，**由剧本提取自动产出**（非空文本） |

> `voice_description` 由提取链路的 `ElementExtractorAgent` 输出（有对白的角色才产出），落库为
> `TEXT NOT NULL`（迁移 016 + 018，历史 NULL 已回填为空串）。

### 5.5 资产化：批量生成参考图

```bash
POST /api/v1/studio/image-tasks/assets/batch-image-tasks
body: { "project_id": "<pid>", "asset_type": "character", "asset_ids": ["..."] }
```

- **`project_id` 必填**：批量任务**只处理该项目下的资产**；项目不存在 → 404。
- `asset_ids` 可选、**最多 200 条**；缺省 = 该项目下该类型全部资产。
- 传入但不属于该项目的 ID **不报错**，逐条记入 `skipped`（reason = `not in project`）。
- 服务侧另有 `MAX_BATCH_ASSETS = 200` 上限，**超限直接 400，不截断**（成本保护）。
- 角色没有图片槽位时**自动补一个 front 空槽位**；其他类型补不了 → `skipped`（reason = `no image slot`）。
- 返回 `{tasks, skipped, enqueue_failed}`：`tasks` **只含已成功入队**的任务；`enqueue_failed` 的任务行已被标记 `failed` 并写入原因。

**验收标准**：`tasks` 覆盖目标资产；到「任务中心」或资产编辑页看出图与**抽卡**。

> ⚠️ 该接口会**真实消耗算力额度**。先在 1–2 个角色上验证参数，再全量铺开。

### 5.6 参考图回链（自动，无需维护）

只要资产图生成且 `file_id` 非空，关键帧与视频提示词会**按「角色 → 场景 → 道具 → 服装」优先级自动携带参考图**（[asset-extraction-oneclick.md:66-70](site/content/docs/architecture/asset-extraction-oneclick.md#L66-L70)）。

**这是「分镜必须挂参考图」这条硬要求的实现机制**：先把资产图片做出来，回链自动生效。

---

## 6. 阶段五｜生成（`shoot`）

入口：`/projects/:projectId/chapters/:chapterId/studio`（`ChapterStudio`，章节生成工作台）。

### 6.1 先看 readiness

工作台内有 `ChapterStudioVideoReadinessPanel`（单镜 + 批量 `video-readiness`）与
`ChapterStudioReadinessDiagnosisPanel`。**不 ready 不要强行提交**。

后端已做硬拦截：提交视频任务前会跑 `get_shot_video_readiness`，**不 ready → 409**，
detail 为 `Shot is not ready for video generation: <key: message; ...>`。

### 6.2 关键帧

先生成关键帧（首帧 / 关键帧 / 尾帧），再进视频。关键帧提示词已收敛：

- 最终图片 prompt 会带上 `director_command_summary` → `continuity_guidance` → `screen_direction_guidance` → `composition_anchor`（最多保留 3 条）
- 首帧偏向保 `composition_anchor`，关键帧/尾帧偏向保 `screen_direction_guidance`
- 关键帧用于视频参考时，提交会显式带 `target_ratio + resolution_profile`，后端按**图片模型 capability** 解析 `size`，保证关键帧画幅与目标视频一致

### 6.3 视频参数：`ratio` 是唯一业务主参数

解析顺序（后端继承链，全空 → 400）：

```text
请求参数 → ShotDetail.override_video_ratio → Shot.chapter_id → Chapter.project_id → Project.default_video_ratio
```

- 非法比例 → 400，并指明来源字段（`shot_details.override_video_ratio` / `projects.default_video_ratio`）
- 供应商不支持 `ratio` 时，由 provider adapter 在执行层内部派生辅助 `size`
- 前端比例枚举来自**当前默认视频模型 capability** 动态返回

### 6.4 提交与批量推进

- 单镜：确认参数 → 生成视频。
- 批量：`ChapterStudioBatchToolbar` 在章节内连续推进多个镜头。
- 提交前 `submitNow()` 会自动确保 `derived` 为最新（生成准备架构四层：Base Draft → Context → Derived Preview → Submission Payload，见 [generation-workspace.md](site/content/docs/architecture/generation-workspace.md)）。
- 运行中的生成**不写 `shots.status`**；「生成中」由 `GenerationTask / GenerationTaskLink` 动态聚合。

**验收标准**：镜头有可用视频；失败任务在任务中心可见原因。

---

## 7. 阶段六｜配音（TTS）

### 7.1 音色配置

在角色编辑页给每个角色定 `voice_id` + `voice_source`（`preset` 预设 / `custom` 复刻）。
查询供应商可用音色：

```bash
GET /api/v1/studio/audio-tasks/voices?kind=preset     # 或 kind=custom
```

> 当前**仅优云智算 IndexTTS** 暴露音色列表接口；其他供应商调用会 400。

### 7.2 生成配音（两种用法）

```bash
POST /api/v1/studio/audio-tasks/speech
```

- **按台词配音（推荐）**：传 `dialog_line_id` —— 文本、说话角色、挂载目标**自动带出**，音色取该角色默认音色，
  产物**直接挂到这句台词上**（一个分镜多句台词互不覆盖）。
- **独立音频**：传 `text`（可配 `voice`）。

其他可选项：`speaker_character_id`、`voice`、`voice_source`、`language`、`speed`、`emotion`（情感描述，
对白候选接受时情绪会作为 TTS 情绪下发）、`format`（默认 `wav`）、`relation_type` / `relation_entity_id`
（留空则服务端推导为 `shot` / `dialog_line` / `standalone`）。

参数在**请求期即按供应商能力校验**，非法参数返回 422（不是先建任务再失败）。

### 7.3 挂载结果

产物落到 `shot_dialog_lines.generated_audio_file_id`（逐句）；分镜级挂载用
`shots.generated_audio_file_id`。

### 7.4 ⚠️ 当前能力边界

**配音链路目前只有后端 API 与已生成的 TypeScript 客户端（`StudioAudioTasksService`），前端没有 UI 入口。**
现阶段配音需按下述方式触发（二选一）：

- 调 `POST /api/v1/studio/audio-tasks/speech`（传 `dialog_line_id`）
- 或在后续版本的 UI 接入后，在分镜/台词处直接点生成

**不要在前端找「生成配音」按钮——目前不存在。**

---

## 8. 阶段七｜成片与时间线

入口：`/projects/:projectId/editor`（`VideoEditor`）。

- 按章节/镜头拼装成片，查看「带配音片段」统计。
- 时间线链路：`项目 → 章节 → 分镜 → 资产 / 帧图 → 时间线`。
- 判断某镜是否真的带配音，看 `clips_with_audio`。

**验收标准**：成片可预览；每条分镜的视频与配音齐备。

---

## 9. 开工前预检清单（每集必跑）

| # | 检查项 | 怎么查 | 期望 |
|---|---|---|---|
| 1 | 后端健康 | `GET /health` | 200 |
| 2 | 供应商 Key | `/models` → 供应商 | 4 类全 active |
| 3 | 默认模型 | `GET /llm/{image,video,audio}-generation-options` | 与 1.2 表一致 |
| 4 | 项目画幅 | `GET /studio/projects/{id}/production-readiness` | `video_ratio_ready = true` |
| 5 | 角色音色 | 同上 | `character_voice_ready = true` |
| 6 | 参考图齐备 | 同上 | `shot_reference_frames_ready = true` |
| 7 | 章节原文 | 项目工作台 → 章节 | 非「待录入原文」 |
| 8 | 分镜已提取 | 章节分镜列表 | 分镜数 > 0 |
| 9 | 逐镜确认完成 | `GET /studio/shots/{id}/preparation-state` | `pending_confirm_count = 0` |
| 10 | 视频就绪 | 工作台 readiness 面板 | 无红光 / 提交不返回 409 |

`production-readiness` 的 `ready` 为 `false` 时，逐条读 `checks[].message` 照做。

---

## 10. 常见坑（对照表）

| 现象 | 原因 | 处理 |
|---|---|---|
| 422 `Field required` | 缺必填参数（如批量参考图的 `project_id`） | 补参 |
| 422 值非法 | 传了英文枚举，接口要**中文** | `style`=真人都市/真人科幻/真人古装/动漫科幻/动漫3D/国漫/水墨画；`visual_style`=现实/动漫 |
| 422 镜头语言 | `CameraShotType/CameraAngle/CameraMovement` **枚举值全大写** | 传 `MS` / `EYE_LEVEL` / `STATIC` |
| 400 `ratio is required` | 请求、分镜覆盖、项目默认**全为空** | 设 `Project.default_video_ratio = 9:16` |
| 400 `Invalid video ratio` | 非法比例值 | 用模型 capability 返回的比例 |
| 409 `Shot is not ready...` | 候选未确认完 / 缺前置 | 读 detail 里的 `key: message` 逐条补齐 |
| 分镜永远 `pending` | 缺 `shot_details` 行 | 修复创建路径（必须走默认工厂） |
| 400 `too many assets` | 批量参考图目标 > 200 | 缩小 `asset_ids` 或分批 |
| `skipped: not in project` | `asset_id` 不属于该 `project_id` | 核对项目归属 |
| `skipped: no image slot` | 非角色类型无图片槽位 | 先创建槽位（角色会自动补） |
| 抽卡出图不一致 | 资产参考图未生成 / `file_id` 为空 | 先完成资产化，回链才生效 |
| 提取后候选为空 | 提取入参无分镜内容 | 已修复（服务端从库内分镜重建）；确认章节确有分镜 |
| 「生成配音」找不到 | 前端无该入口 | 走后端 API（见 7.4） |

---

## 11. 能力边界（诚实标注）

1. **配音无 UI**：后端 API + 生成的 TS 客户端齐备，前端页面未接入（第 7.4 节）。
2. **旧提取向导页仍未接线**：`ChapterPrep.tsx` 的 5 步向导（智能提取 → 场景生成 → 道具生成 → 角色生成 → 分镜预览）
   **无路由可达**（`/prep/*` 重定向到 `../shots`，全仓无 import），属不可达代码。实际入口是
   `ChapterShotsPage` 的「一键提取分镜」+「一键创建资产」+ `ChapterShotEditPage` 的逐镜确认。
   `ChapterPrep` 里**尚未搬家**的只剩「批量生成参考图」按钮（接口可用，见第 6 节）。
3. **`types: []` 是行为变更**：由「全部」变为「不处理」。当前唯一前端调用点传 `undefined`（等价 `None`），
   故现状安全；对外发布需写入 release note 的 Breaking Changes。
4. **提示词模板发布**：需在 `/prompts` 显式「发布生效」；已发布模板修改内容会**自动取消发布**（需重新发布）。
   Celery 各 worker 进程各自持缓存，刷新钩子已统一到任务执行前置钩子。
5. **批量接口会真实扣算力**：`batch-image-tasks` 与视频任务都会真实入队，测试时先小范围。

---

## 12. 单集执行时间线（模板）

```text
D-1  预检 10 项全绿；角色卡定死（外形 + 音色 + 音色描述）
D0   建章节 → 录原文 → 一键提取分镜
D0   逐镜：提取 → 确认资产候选 → 确认对白候选 → shot.status = ready
D1   一键创建资产（按需） → 批量生成参考图 → 抽卡筛选
D2   关键帧生成 → 视频提交（单镜） → 批量推进本章余下镜头
D3   配音（按 dialog_line_id 逐句） → 成片拼装 → 验收
```

---

*本 SOP 基于当前代码状态编写，涉及具体数值（上限 200、比例继承链、状态机）均已核对实现。*
