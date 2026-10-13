---
title: "提示词模板与风格包"
description: "说明数据库内置的提示词模板、变量契约、项目级风格包与统一负面提示词。"
weight: 11
---

> 本文属于“当前架构”文档，描述当前已经生效的提示词模板机制。

## 模板存在数据库里

提示词模板不再硬编码在代码中，而是作为数据行存在 `prompt_templates` 表：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `varchar(64)` | 主键 |
| `category` | `varchar(32)` | 模板类别，业务侧按类别查找 |
| `name` | `varchar(255)` | 展示名 |
| `preview` | `text` | 预览用短文本 |
| `content` | `text` | 模板正文，含 `{{ 变量 }}` |
| `variables` | `json` | 本模板声明的变量列表 |
| `is_default` | `tinyint(1)` | 是否默认模板 |
| `is_system` | `tinyint(1)` | 是否系统内置 |

索引为 `ix_prompt_templates_category`、`ix_prompt_templates_name`。注意 **`category` 上没有唯一键**，因此写入迁移必须是幂等的 `UPDATE ... WHERE category = 'x'` 配合
`INSERT INTO ... SELECT ... FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM prompt_templates WHERE category = 'x')`。

当前共 **14 个类别**：

```text
actor_image_front        actor_image_other
character_image_front    character_image_other
prop_image_front         prop_image_other
scene_image_front        scene_image_other
costume_image_front      costume_image_other
combined
frame_head_prompt        frame_tail_prompt        frame_key_prompt
```

### 为什么 `video_prompt` 故意不播种

一旦库里存在 `video_prompt` 行，`derive_video_preview` 就会走模板分支，从而**绕过** IR → H3 渲染器这条链路（见[视频提示词链路](/docs/architecture/video-prompt-pipeline/)）。所以它被有意留空。

## 迁移由代码生成，不手抄

模板正文要求与代码里的常量逐字一致，手抄必然漂移。因此迁移文件是**生成物**：

```bash
cd backend && .venv/bin/python scripts/gen_prompt_templates_sql.py
```

脚本 `backend/scripts/gen_prompt_templates_sql.py` 会：

- `import` 三个帧模板常量（`_FIRST_FRAME_TEMPLATE` / `_LAST_FRAME_TEMPLATE` / `_KEY_FRAME_TEMPLATE`）以及 `_SHOT_FRAME_INPUT_VARS`，保证 SQL 与运行代码同源；
- 用统一的 `ASSET_VARS` 描述资产类模板变量；
- 输出 `backend/sql/012-rewrite-prompt-templates.sql`。

应用方式：

```bash
docker exec -i compose-mysql-1 mysql -uroot -p"$DB_PASS" --default-character-set=utf8mb4 jellyfish \
  < backend/sql/012-rewrite-prompt-templates.sql
```

迁移可重复执行：跑第二次不会新增行，`SELECT COUNT(*) FROM prompt_templates` 仍是 14。

## 变量契约

资产类模板（角色 / 演员 / 场景 / 道具 / 服装 / combined）共享同一组变量：

```text
name  description  tags  visual_style  style
view_angle  quality_level  format  style_pack  negative_prompt
```

**这里有一个历史坑**：早期模板正文用了 `{{ view }}` 和 `{{ extra_details }}`，但这两个变量从未被传进 `variables`。渲染时 `render_prompt_template_content` 会把未知变量渲染成空字符串，于是“镜头方向：”后面一直是空的。新模板统一改用实际会传入的 `view_angle` / `tags` / `style_pack` / `negative_prompt`。

修改模板变量时，务必同步 `ASSET_VARS` 与调用侧的 `variables` 字典——两边不一致就是静默的空字符串。

## 项目级风格包

`backend/app/chains/prompts/style_pack.py` 提供“一处配置、全局注入”的风格层：

| 常量 | 键 | 说明 |
| --- | --- | --- |
| `FORMAT_PACKS` | `现实` / `动漫` | 按项目 `visual_style` |
| `STYLE_PACKS` | 7 个中文题材 | 按项目 `style` |

对外函数：

```python
def format_pack_for(visual_style) -> str
def motif_pack_for(style) -> str
def style_pack_line(*, visual_style="", style="") -> str
def negative_image_prompt(*, visual_style="", style="") -> str
def is_anime(*, visual_style, style) -> bool
```

`style_pack_line` 用「；」拼接题材包与形态包，**永远非空**（找不到就回落到 `DEFAULT_STYLE_PACK = STYLE_PACKS["真人都市"]` / `DEFAULT_FORMAT_PACK = FORMAT_PACKS["现实"]`），因此模板里的 `{{ style_pack }}` 不会渲染成空。

### 字段语义（容易搞混，务必分清）

`backend/app/models/types.py` 里：

- `ProjectStyle` → 对应 **`style`** 字段，取值 `真人都市` / `真人科幻` / `真人古装` / `动漫科幻` / `动漫3D` / `国漫` / `水墨画`。
- `ProjectVisualStyle` → 对应 **`visual_style`** 字段，取值只有 `现实` / `动漫`。

`app.models.types` 里**没有** `VisualStyle` 这个名字。给 `style_pack_line` 传参时不要把两者对调。

### 命名约定

- `_ANIME_FORMATS = {"动漫"}`
- `_ANIME_STYLES = {"动漫科幻", "动漫3D", "国漫", "水墨画"}`
- `_ANCIENT_STYLES = {"真人古装"}`

## 统一负面提示词

同一模块提供四组负面词常量：

```text
COMMON_NEGATIVE_IMAGE
REALISTIC_NEGATIVE_IMAGE
ANIME_NEGATIVE_IMAGE
ANCIENT_NEGATIVE_IMAGE
```

由 `negative_image_prompt(*, visual_style, style)` 用「，」拼成一条，写进模板变量 `negative_prompt`，并由每个模板结尾的固定块消费：

```text
负面提示（必须避免，不要出现在画面中）：
{{ negative_prompt }}
```

### 刻意不写的东西

风格包只描述**画面可观察要素**，不写“8K 分辨率”“f/1.4 大光圈”这类参数：当前出图统一 1K，且主流出图模型对光圈数值不敏感，写了只是噪音。

## 角色卡的身份锁

`character_image_front` 模板包含一段身份锁，用于在带参考图时固定角色身份：

```text
若提供了参考图，参考图中的人物即为本角色「{{ name }}」的身份基准
不得换脸、不得改变发型发色与年龄感
若参考图包含服装则沿用
```

角色图基础草稿由 `build_character_image_base_draft`（`backend/app/services/studio/generation/asset_image/build_base.py`）构造，使用 **`PromptCategory.character_image_front`**。

这里曾经有过一个静默缺陷：该函数原先传的是 `PromptCategory.combined`，而库里**没有** `combined` 模板行，`build_prompt_with_template` 只能回落到 `prompt_from_description(character.description)`，导致角色卡提示词退化成一句原始描述，而 `character_image_front` 成了死配置。现已修正，两个类别现在都有真实模板。

## 相关文档

- [视频提示词链路与参考图](/docs/architecture/video-prompt-pipeline/)
- [分镜基础提示词生成](/docs/architecture/shot-frame-prompt-generation/)
