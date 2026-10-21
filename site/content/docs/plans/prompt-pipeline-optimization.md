---
title: "提示词链路优化分析"
description: "梳理资产图、分镜帧、视频三条提示词支路的现状，列出可优化点与建议顺序。"
weight: 12
---

> 本文属于“任务计划”文档，是一次**现状分析 + 优化建议**，不是已落地的架构说明。
> 当前生效的链路见 [提示词模板与风格包](/docs/architecture/prompt-templates/)、
> [分镜基础提示词生成](/docs/architecture/shot-frame-prompt-generation/)、
> [视频提示词链路](/docs/architecture/video-prompt-pipeline/)。

## 1. 链路全景

当前共有 **五条** 与提示词相关的支路，彼此独立实现：

| 支路 | 入口 | 是否用 LLM | 产物落地 |
|---|---|---|---|
| 资产图（演员/角色/场景/道具/服装） | `assets/.../build_base.py` → `build_prompt_with_template` | 否（纯模板渲染） | 直接提交图片模型 |
| 分镜帧（首/关键/尾） | `chains/agents/shot_frame_prompt_agents.py` | **是**（生成基础提示词） | 存 `shot_details.first/last/key_frame_prompt` |
| 帧渲染（最终图片提示词） | `generation/frame/derive_preview.py` | 否（拼装 + guidance 剪裁） | 提交图片模型 |
| 视频 | `chains/prompts/ir.py` → `renderers/h3.py` | **可能是**（H3 正文可由 agent 生成） | 存任务 `run_args.input.prompt` |
| 预处理 Agent（拆解/提取/画像…12 个） | `chains/agents/*` | 是 | 结构化数据落库 |

共同的下游是两类适配器：

- 图片：`core/integrations/{openai,pix,compshare}/image*`
- 视频：`core/integrations/{compshare,pix,volcengine,openai}/video.py`

## 2. 现状数据流

```text
prompt_templates(DB)  ──resolve_prompt_template(每次查库)──┐
                                                          ├─ render(jinja2) ─→ 资产图提示词
style_pack(代码+目录) ──style_pack_line────────────────────┘
negative_image_prompt(代码) ──────────────────────────────┘

镜头/实体数据 ─→ 帧 Agent(LLM) ─→ first/last/key_frame_prompt(落库)
                                    └─ frame-render：图片内容说明 + guidance + 基础提示词 → 图片模型

镜头数据 ─→ IR(结构化) ─→ H3 渲染器 ─→ 视频提示词 → 视频适配器
```

## 3. 发现的问题

### P0：同一项目在三个环节的画风依据不一致

| 环节 | 实际拿到的"风格"信息 |
|---|---|
| 资产图 | `style_pack_line()`：表现形式包 + **题材质感描述全文** + 负面词 |
| 分镜帧 | 只有两个**名称**：`{visual_style} / {style}`（`_SHOT_FRAME_INPUT_VARS`） |
| 视频 | `style_anchor = "现实 真人都市"`，同样只有名称（`ir.py:344`） |

后果：资产图是按"现代都市实拍、冷暖对比、浅景深"这类具体词生成的，
而帧与视频只看到"真人都市"三个字，模型对画风的理解完全依赖自己的先验。
这正是"资产图很电影感、帧图却不像同一部片"的结构性原因。

> 上一轮给 `project_styles` 加了 `prompt_pack` 后，只有资产图会用它，
> 帧和视频仍然收不到——**自定义风格目前只影响资产图**。

### P0：`is_anime()` 仍按硬编码集合判定

`style_pack.py` 里：

```python
_ANIME_STYLES = {"动漫科幻", "动漫3D", "国漫", "水墨画"}
```

风格目录已经可扩展，但负面词选择仍按名称白名单判断。
新增一个挂在「动漫」下的风格（例如「赛博国风」）会被判为写实，
于是给动漫画面套上 `cartoon, 3d render, illustration` 这类**反向**负面词。

正确判据应该是目录里的 `visual_style`（或 `is_anime` 由调用方传入 `visual_style`，
现有签名已经带了这个参数，只是优先用了硬编码集合）。

### P1：分镜帧链路完全没有负面词

资产图会把 `negative_image_prompt()` 渲染进模板，帧渲染只拼"图片内容说明 + 正文 + guidance"，
`_SHOT_FRAME_INPUT_VARS` 里也没有 negative 变量。

后果：帧更容易出现文字、水印、畸变手指。而这批帧随后会作为视频的首尾帧/参考图，
错误会被放大到视频里。

### P1：视频 IR 的 `negative_prompt` / `avoid` 是死字段

`ir.py` 构造了 `negative_prompt` 与 `avoid`，但 H3 渲染器和四个视频适配器**都没有读取**
（grep `negative`/`avoid` 在 renderers 与 integrations 下无命中）。
这会让后续维护者误以为"视频已经有负面约束"。

### P2：模板解析没有缓存

`resolve_prompt_template()` 每次提示词构建都查一次库：

```python
select(PromptTemplate).where(category == ...).order_by(is_default.desc(), updated_at.desc())
```

批量生成 20 个资产 = 20 次相同查询；`render_prompt_template_content()` 还会每次
`LcPromptTemplate.from_template()` 重新解析 Jinja2。单次不贵，但批量时是纯浪费。

### P2：模板变量缺失时静默为空

```python
render_vars = {k: str(variables.get(k, "")) for k in tmpl.input_variables}
```

模板里写了 `{{ style_packk }}`（拼错）不会报错，只会渲染成空串，
最终生成一条"少了画风约束"的提示词，且没有任何告警。

### P2：缺少统一的长度预算

- H3 有 `H3_MAX_PROMPT_CHARS = 7000` 与推荐 350–500 词；
- 图片链路对长度没有任何约束；
- 资产模板 + 风格包 + 负面词叠加后长度不可控，也没有"超限怎么办"的统一策略。

### P2：可追溯性只覆盖一半

- 帧：基础提示词落库 + `shot_details.prompt_template_id`，可回溯；
- 资产图：模板内容**没有快照**，事后改模板会改变"当时为什么这么写"的解释；
- 视频：`run_args.input.prompt` 存了最终提示词，但没存 IR 与模板版本。

## 4. 优化建议（按收益/成本排序）

### 第一批：一致性（小改动，直接改善出片）

1. **帧提示词注入 `style_pack`**
   - 在 `_SHOT_FRAME_INPUT_VARS` 增加 `style_pack`，构建变量时用
     `style_pack_line(visual_style, style, motif_override=await resolve_style_motif(db, style))`；
   - 模板正文增加一段"画风质感（必须遵守）"；
   - 收益：资产图与帧图共享同一套质感词，自定义风格同时作用于帧。
2. **视频 `style_anchor` 改用质感描述**
   - `IRPrompt.style_anchor` 由"名称拼接"改为"品牌包 + 题材包"，H3 渲染器的
     `The video keeps the established project look:` 段落自动受益。
3. **`is_anime()` 改为看 `visual_style`**
   - 判定顺序：`visual_style == 动漫` → 动漫包；否则看题材集合；最后兼容旧值。

### 第二批：缺失约束（中等改动）

4. **帧补负面词**：帧模板加 `negative_prompt` 变量，渲染时与资产共用
   `negative_image_prompt()`。
5. **视频负面/avoid 落地或删除**：H3 无独立 negative 参数，可在渲染器正文末尾
   以"避免：…"形式表达；做不到就删掉字段，避免误导。

### 第三批：工程性（不改出片效果，降低长期成本）

6. **模板读取加进程内缓存**（TTL 或按 `updated_at` 失效），批量生成只查一次；
   同时把 Jinja2 解析结果缓存起来。
7. **变量校验**：模板保存/发布时校验 `input_variables ⊆ 已知变量集`，
   缺变量在构建时至少打 warning。
8. **长度预算**：统一 `max_chars` 常量，超限先裁剪低优先级段落（guidance 之类），
   并在 `debug_context` 里记录被裁掉的部分。
9. **提示词快照**：生成任务里存 `template_id + template_updated_at + 最终提示词`，
   便于事后解释与 A/B。

## 5. 验证手段

现有可用的观察点，做优化时优先复用而不是新造：

| 手段 | 位置 |
|---|---|
| 帧任务 `debug_context` / `quality_checks` | 基础提示词任务结果 |
| 视频提示词预览 | `GET /api/v1/studio/shots/{shot_id}/video-prompt-preview` |
| 帧渲染预览 | `POST /api/v1/studio/shot-frame-images/shot/{shot_id}/frame-render-prompt` |
| 任务输入快照 | `generation_tasks.run_args.input` |
| 模板一致性校验 | `backend/scripts/check_agent_prompt_templates_sql.py` |

建议第一批改动后，固定 3 个镜头（近景人物 / 空镜 / 对白反打）做前后对比，
确认"资产图与帧图观感一致"这一条真的改善，而不是只改了代码。

## 6. 风险

- 帧提示词加入质感描述后**变长**，接近 H3 7000 字符上限时需要第 8 条的长度预算兜底；
- 视频 `style_anchor` 改成质感词后，历史版本的对比基线会变，A/B 时要注意区分；
- 帧 Agent 已把基础提示词落库，**只在"重新生成"时才会用到新注入**——
  已有项目不会自动改变，需要显式重跑，这反而是安全的。
