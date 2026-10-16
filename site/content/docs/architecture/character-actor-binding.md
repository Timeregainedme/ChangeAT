---
title: "角色与演员的绑定要求（主角级才必填）"
description: "角色要不要绑定演员由「跨集出现次数」决定：出现在 ≥2 个章节的角色必须绑，只在一集内出现的可以不绑；含判定口径、接口、开工预检与告警行为。"
weight: 16
---

> 本文属于“当前架构”文档，描述当前真实生效的实现。

## 背景

角色绑定演员的作用只有一个：让角色图拿到**演员参考图**，从而保证同一个「人」在不同镜头、不同集里的长相一致。
但把「关联演员」做成角色的必填项是错的：

- 只在一集里露一次面的角色（路人、群演、被提及的角色）根本不需要跨集一致，强制绑定只是增加建卡负担。
- 反过来，跨集反复出现的主角级角色如果没绑演员，各集里的长相会各演各的 —— 这才是真正要拦住的。

因此当前实现的判定口径是**按出现次数自动判定**，而不是新增一个需要用户手填的「角色类型」字段。

## 判定口径

- 数据来源：`shot_character_links ⋈ shots.chapter_id` 的**去重章节数**。
  角色出现在几个不同章节（集）里，就是它的出现次数；分镜关联本来就已经记录了这件事。
- 阈值：`RECURRING_MIN_CHAPTERS = 2`（`backend/app/services/studio/character_recurrence.py`）。
  `chapter_count >= 2` 即为主角级（`is_recurring()`）。
- 尚未挂过任何分镜的角色 `chapter_count = 0`，与「只在一集内出现」（1）同等对待 —— 都不要求绑演员。
- **没有**「角色类型 / 是否主角」这样的数据列，用户不需要维护它，也不会与实际分镜不一致。

## 接口

`GET /api/v1/studio/projects/{project_id}/character-recurrence`（只读）：

```json
{
  "project_id": "proj-1",
  "min_chapters": 2,
  "items": [{ "character_id": "char-1", "chapter_count": 2, "recurring": true }]
}
```

- 返回项目下**全部**角色（含 `chapter_count = 0` 的），前端因此拿到的是一张完整映射；
  缺项会让新建的角色查不到自己而被误判成主角级。
- 服务：`app/services/studio/character_recurrence.py`，三个函数分别是
  `character_chapter_counts()`（项目级映射）、`character_chapter_count()`（单角色，供生成链路用）、
  `get_project_character_recurrence()`（组装接口响应）。
- 前端 `front/src/pages/aiStudio/project/ProjectWorkbench/tabs/RolesTab.tsx` 在加载角色页时一并拉取，
  卡片上显示 `出现 N 集 · 可不绑演员` / `跨 N 集 · 已绑演员` / `跨 N 集 · 建议绑演员`；
  编辑主角级且未绑演员的角色时，表单顶部显示一条 `Alert`（**只提醒，不阻断保存**）。

## 开工预检

`GET /api/v1/studio/projects/{project_id}/production-readiness` 中的 `character_actor_ready` 检查项：

- **仅当存在「跨 ≥2 集且 `actor_id` 为空」的角色时**不通过，并给出数量与修复指引，同时说明只在一集内出现的不要求绑定。
- 与之相邻的 `character_voice_ready` 是另一件事：它只判断角色有没有可用音色（角色自带 **或** 所绑演员提供），
  与是否绑演员无关 —— 没绑演员的角色必须自己配 `voice_id`，否则配音时会因缺少音色失败。

## 生成期告警

`build_character_image_base_draft`（`backend/app/services/studio/generation/asset_image/build_base.py`）
在角色没有 `actor_id` 时，**先算该角色的章节数，仅当 `is_recurring()` 为真**才追加告警
「角色未绑定演员…该角色已出现在 N 个章节，属于跨集反复出现的主角级角色，建议在角色编辑里绑定演员…」。

- 对配角（`chapter_count ≤ 1`）不再产生该条告警：否则每张路人角色图都带一条无效提示，会淹没真正要处理的问题。
- 「所绑演员还没有生成任何图片」（已绑定但没出图）与「零参考图」两条告警不受影响，仍按原口径逐条判定。
  详见 [生成工作区：资产图片的参考图缺失说明](generation-workspace.md)。
