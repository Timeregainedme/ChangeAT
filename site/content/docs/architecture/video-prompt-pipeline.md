---
title: "视频提示词链路与参考图"
description: "说明分镜视频提示词的 IR 中间表示、H3 渲染器、参考图模式与生成前准备度校验。"
weight: 10
---

> 本文属于“当前架构”文档，描述当前已经生效的视频提示词链路。

## 为什么要有 IR 层

视频提示词不能直接由“镜头数据 → 一句话”拼出来，原因是：

- 同一份镜头信息要输出给不同供应商、不同模型，各自要求的格式不同（例如 H3 要求英文六段式并限制字数）。
- 参考图顺序、说话人编号、图片编号必须在提示词正文和实际上传的图片列表之间**严格一致**，否则模型会把 `图2` 认成另一个人。

因此链路被拆成两段：

```text
镜头业务数据
→ IR（结构化中间表示）
→ 渲染器（按目标模型输出格式）
→ 最终视频提示词
```

IR 是唯一事实来源：参考图列表、主体定义、对白行、镜头语言都先在这里定稿，再交给渲染器。

## IR 层

代码在 `backend/app/chains/prompts/ir.py`。

| 模型 | 作用 |
| --- | --- |
| `IRReference` | 一张参考图：`token`（`图1`…）、`kind`、`name`、`file_id` |
| `IRSubjectDefinition` | 主体定义（角色/场景/道具/服装的外观描述） |
| `IRShot` | 镜头语言：景别、机位、运镜、时长 |
| `IRDialogueLine` | 一句对白：说话主体、受话主体、文本、情绪 |
| `IRPrompt` | 汇总以上内容，是渲染器的唯一输入 |

入口是：

```python
def build_video_prompt_ir(...) -> IRPrompt
```

相关常量：

- `MAX_REFERENCE_IMAGES`：参考图上限（转发 `short_drama_rules.MAX_REFERENCE_IMAGES`，当前 `9`）。
- `DEFAULT_VIDEO_DURATION_SECONDS = 5.0`：镜头未配置时长时的兜底。

## 参考图顺序：角色卡永远是 图1

`backend/app/services/studio/generation/frame/build_context.py` 定义了固定优先级：

```python
_REFERENCE_KIND_PRIORITY = {"character": 0, "scene": 1, "prop": 2, "costume": 3}
```

`build_ordered_shot_frame_references` 会先按该优先级**稳定排序**，再去重、再分配 `token = f"图{len(mappings) + 1}"`。所以：

- 角色卡即使排在入参列表最后，也一定是 `图1`。
- 同类内保持调用方（前端）传入的顺序。
- 未识别的类别排在最后，且不会被丢弃。

这条顺序是安全的，因为上传图片列表与提示词里的“实体名 → token”替换**都在服务端生成**：`app/services/studio/generation/frame/derive_preview.py` 用
`images=[mapping.file_id for mapping in context.ordered_refs]` 构造上传列表，前端只提交实体名。

## 人物卡的双重判定

一个角色“和镜头关联”不等于“这个镜头里出现了这个角色”。如果只按关联插卡，纯空镜也会被塞进角色参考图，污染生成结果。

因此在 `_collect_asset_references` 里，角色需要同时满足：

1. 该角色已关联当前镜头；
2. 该角色的名字出现在当前镜头的**剧本语料**里。

剧本语料由 `_shot_script_corpus(pack)` 拼成，包含 `title`、`script_excerpt`、`shot_description`、`action_beats`、`dialogue_summary`；**刻意不含** `previous_shot_summary` / `next_shot_goal`——相邻镜头出现的角色不代表本镜头出场。

判定函数是 `_character_appears_in_shot(*, name, corpus)` 的子串命中。因为 `dialogue_summary` 的构造方式是 `f"{line.speaker_name or '角色'}：{line.text}"`，所以“该角色有台词”会被自然覆盖。

未命中时不会静默丢弃，而是追加一条可解释的警告，例如：

```text
角色「林晚」已关联该镜头，但本镜头剧本内容里没有出现，本次未插入该角色卡
```

场景、道具、服装**不参与**该判定，仍只看有没有绑定文件。

## 渲染器

`backend/app/chains/prompts/renderers/__init__.py` 对外暴露：

```python
def uses_h3_prompt_format(*, provider: str = "", model: str = "") -> bool
def get_video_renderer(*, provider: str = "", model: str = "") -> VideoRenderer
def render_video_prompt(...)
```

H3 渲染器在 `renderers/h3.py`，关键约束：

- `H3_MAX_PROMPT_CHARS = 7000`
- `H3_RECOMMENDED_WORD_RANGE = (350, 500)`
- 输出结构由 `h3_label_for(kind, subject_index, picture_index)` 生成标签，保证“主体编号 / 图片编号”与 IR 一致。
- 部分段落（主体定义、摘要、留存分析）在模型未产出时有 fallback 实现，避免整段缺失。

需要 LLM 生成正文时走：

```python
def build_h3_agent_variables(ir: IRPrompt) -> dict[str, str]
class H3VideoPromptAgent(AgentBase[H3Prose])
async def generate_h3_prose(...)
```

代码在 `backend/app/chains/agents/h3_video_prompt_agent.py`。

## 默认视频模型

视频生成任务的模型**不可由请求体指定**：`build_run_args` 一律通过
`resolve_default_video_model(db)` 读取 `ModelSettings.default_video_model_id`，
因此「当前默认模型」决定了所有视频生成实际使用的供应商与模型。

当前生效配置（运行库 `model_settings`）：

| 项 | 值 |
| --- | --- |
| 默认视频模型 | `MiniMax-H3`（优云智算供应商 `a04dc839…`，base `https://cp.compshare.cn`） |
| 备用视频模型 | `minimax-h3`（PIX 供应商 `db1fec41…`，保留可选，不再默认） |

决策背景：

- 默认模型由产品方指定为**优云智算的 `MiniMax-H3`**（历史生成结果可用，供应商链路能正常出片）；
- PIX 的 `minimax-h3` 曾作为默认并被成功使用过，现降级为备用；
- 已知风险：优云智算链路上曾出现一次任务载荷中提示词中文乱码
  （`generation_tasks` 中 `task_kind=video_generation` 的 `run_args.input.prompt` 全为 `?`）；
  该条任务虽成功出片，但画面与提示词不对应。若默认切回优云智算后再次出现乱码，
  优先排查供应商 API 的编码/请求体序列化，必要时切回 PIX；
- 40–150 集短剧要求跨集画风一致，默认模型保持单一供应商/模型是硬约束；
  如需切换，在「模型设置」页修改默认视频模型即可，代码无需变更。

## 短剧创作纪律

`backend/app/chains/prompts/short_drama_rules.py` 是无 IO、无 LLM 的纯常量与纯函数层，供 IR 与校验复用：

- `SUBTITLE_SAFE_AREA_RATIO = 0.15`：画面下部约 15% 作为字幕安全区。
- `micro_expression_quota(duration_seconds)`：按镜头时长给出微表情配额。
- `CHARS_PER_MINUTE = 150`、`MAX_SINGLE_UTTERANCE_CHARS = 50`：口播节奏与单句上限。
- `estimate_dialogue_seconds(...)`：按标点估算对白时长。
- `action_beats_for_duration(duration_seconds)`：按时长给出动作拍点数量。
- `ABSTRACT_WORD_RULE` / `find_abstract_words(text)`：拦截“唯美”“电影感”这类不可拍摄的抽象形容。

## 参考图模式

`backend/app/services/studio/generation/video/build_context.py` 定义：

```python
REFERENCE_MODE = "reference"
REFERENCE_MAX_IMAGES = 9
REQUIRED_FRAMES_BY_MODE = {...}   # 权威定义，含 REFERENCE_MODE: ()
```

参考图模式与首尾帧模式**互斥**：它不使用分镜帧，参考图由服务端按 IR 的有序参考列表解析：

```python
resolve_reference_mode_file_ids(db, shot_id=...)
```

客户端提交 `images` 为空是正常的——服务端会覆盖。

### 缺图必须是可执行的 400

`validate_images_count(reference_mode, images)` 在参考图模式下的两支报错都写明了原因与下一步：

- 0 张：`reference_mode=reference 需要至少 1 张参考图，但本镜头没有可用参考图。角色卡只在剧本中出现该角色时才会插入；空镜请改用 text_only。`
- 超过上限：`reference_mode=reference 最多支持 9 张参考图，当前 N 张`

## 生成前准备度

`get_shot_video_readiness(db, *, shot_id, reference_mode)` 返回逐项检查，当前 8 项：

| key | 含义 |
| --- | --- |
| `extraction_ready` | 镜头提取结果已确认（或已标记无需提取） |
| `duration_ready` | 镜头时长已配置 |
| `prompt_ready` | 视频提示词可用 |
| `reference_frames_ready` | 当前参考模式所需的帧齐备 |
| `reference_images_ready` | 参考图模式下能解析到至少 1 张参考图 |
| `video_model_ready` | 默认视频模型可用 |
| `provider_ready` | 该模型供应商可用 |
| `no_active_video_task` | 当前没有进行中的视频任务 |

`reference_images_ready` 与 `reference_frames_ready` 的分工很重要：前者管“参考图有没有”，后者管“分镜帧够不够”。**空镜在参考图模式下会在这里被判为未就绪**，而不是等到提交后收到 400。

生成端点（`POST /api/v1/film/tasks/video`）在构造任务参数之前会再跑一次同一套检查，未就绪直接返回 **409**：

```text
Shot is not ready for video generation: reference_images_ready: ...
```

前端 `ChapterStudio.tsx` 读取 `reference_images_ready` 的结论，在参考图不可用时**自动回落到 `text_only`** 并给出提示，避免默认值把用户带进死路。

另有一个项目级的开工预检：

```text
GET /api/v1/studio/projects/{project_id}/production-readiness
```

检查项目是否有默认文/图/视频/音频模型、风格是否就绪、是否有可用的视频比例、角色是否有音色、分镜是否有参考帧等，用于开工前一次性暴露阻塞项。

## 视频比例继承链

`resolve_effective_video_options(db, *, shot_id, shot_detail, requested_ratio)` 按以下顺序取值：

```text
请求参数 ratio
→ shot_details.override_video_ratio
→ projects.default_video_ratio
```

全部为空时返回 400，报错会指出是哪个字段缺失；传入非法值时返回 400 并带上来源字段名（`shot_details.override_video_ratio` / `projects.default_video_ratio`）。

因此 `VideoGenerationTaskRequest.ratio` 是**可选**的——不传就按继承链解析。

## 相关文档

- [提示词模板与风格包](/docs/architecture/prompt-templates/)
- [视频抽卡与版本切换](/docs/architecture/video-version-redraw/)
- [分镜基础提示词生成](/docs/architecture/shot-frame-prompt-generation/)
