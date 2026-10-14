---
title: "分镜状态流转说明"
description: "面向开发者说明 shot.status、skip_extraction、资产候选和对白候选的职责与流转规则。"
weight: 7
---

> 本文属于“当前架构”文档，描述当前已经生效的状态模型与后端判定规则。

## 背景

为了让“分镜是否具备生成视频条件”有统一、可追溯的判定来源，当前后端已经将 `shots.status` 收敛为**系统流程状态**，并引入两张候选表记录镜头提取确认过程中的中间状态。

这次调整的目标不是增加更多前端判断，而是把正式状态统一交给后端维护，前端只消费结果。

## 核心结论

- `shots.status`：系统流程状态，只由后端更新
- `shots.skip_extraction`：用户明确声明“当前镜头无需提取”
- `shot_extracted_candidates`：记录每一条资产提取候选项的处理状态
- `shot_extracted_dialogue_candidates`：记录每一条对白提取候选项的处理状态

也就是说：

```text
shots.status
  = 系统流程状态

skip_extraction
  = 是否跳过提取

shot_extracted_candidates
  = 资产候选的确认明细

shot_extracted_dialogue_candidates
  = 对白候选的确认明细
```

## `shot.status` 的语义

当前只保留两种正式状态：

- `pending`
  - 当前镜头还没有完成视频生成前的确认流程
- `ready`
  - 当前镜头已经具备进入视频生成的前置条件

这里的 `ready` 不再表示“看起来差不多了”，而是明确表示：

> 当前分镜已经完成信息提取确认，因此具备进入视频生成的条件。

需要特别注意：

> 运行中的生成任务不再写入 `shots.status`。
> “生成中”应通过 `GenerationTask / GenerationTaskLink`
> 动态聚合得到，而不是复用 `pending / ready` 这类静态状态。

## `ready` 的判定规则

后端统一按以下规则重算：

1. 如果 `skip_extraction = true`，状态为 `ready`
2. 如果从未提取过，状态为 `pending`
3. 如果提取过但没有任何候选项，状态为 `ready`
4. 如果所有资产候选和对白候选都已经处理完，状态为 `ready`
5. 其他情况为 `pending`

其中“所有资产候选都处理完”指的是：

- `candidate_status = linked`
- 或 `candidate_status = ignored`

其中“所有对白候选都处理完”指的是：

- `candidate_status = accepted`
- 或 `candidate_status = ignored`

只要还有任意一条资产候选或对白候选处于 `pending`，镜头就不能进入 `ready`。

如果某个镜头提取后没有任何对白候选，这不会阻塞 `ready`。

### 前置条件：分镜必须存在配套的 `shot_details` 行

`Shot` 与 `ShotDetail` 是**一对一、同主键**的关联（`shot_details.id` 外键指向 `shots.id`）。上面前四条规则都要读 `ShotDetail`，所以**没有 `shot_details` 行的分镜永远停留在 `pending`**：

- `PATCH /shots/{id}/skip-extraction`（规则 1）会找不到行而报错；
- `GET /shots/{id}/preparation-state`（规则 2–5）同样无法工作。

因此**任何创建 `Shot` 的路径都必须在同一事务里一并创建 `ShotDetail`**。默认值由单一工厂给出：

```python
# backend/app/services/studio/shot_details.py
def build_default_shot_detail(shot_id: str) -> ShotDetail: ...
```

`shot_details.build_default_shot_detail()` 是唯一来源，`backend/app/services/studio/shots.py` 的 `create()` 与 `backend/app/services/studio/script_division.py` 都调用它。不要在新建路径里各写一份默认值——历史上正是因为两条路径不对称（一键提取会插 `ShotDetail`，手工创建不会），导致手工创建的分镜永久卡在 `pending`（见 `v0.4.1` 发布说明）。

补充一个易错点：`CameraShotType` / `CameraAngle` / `CameraMovement` 的**枚举值**是全大写（`MS` / `EYE_LEVEL` / `STATIC`），而 Python 属性名是小写（`CameraShotType.ms`）。直接传小写值给接口会得到 422。

## `shot_extracted_candidates` 表结构职责

这张表记录的是**镜头级资产提取确认明细**，而不是最终资产本身。

核心字段包括：

- `shot_id`
- `candidate_type`
  - `character / scene / prop / costume`
- `candidate_name`
- `candidate_status`
  - `pending / linked / ignored`
- `linked_entity_id`
- `source`
- `payload`
- `confirmed_at`

建议理解为：

```text
一条提取候选
→ 先进入 pending
→ 用户确认后变成 linked 或 ignored
```

## `shot_extracted_dialogue_candidates` 表结构职责

这张表记录的是**镜头级对白提取确认明细**。

核心字段包括：

- `shot_id`
- `index`
- `text`
- `line_mode`
- `speaker_name`
- `target_name`
- `candidate_status`
  - `pending / accepted / ignored`
- `linked_dialog_line_id`
- `source`
- `payload`
- `confirmed_at`

建议理解为：

```text
一条对白候选
→ 先进入 pending
→ 用户接受后写入 ShotDialogLine，并变成 accepted
→ 或用户明确忽略，变成 ignored
```

## 典型流转

### 路径 A：正常提取确认

```text
extract
→ shot_extracted_candidates 写入资产 pending
→ shot_extracted_dialogue_candidates 写入对白 pending
→ 用户处理资产候选：linked / ignored
→ 用户处理对白候选：accepted / ignored
→ 全部资产候选和对白候选已 resolved
→ shot.status = ready
```

### 路径 B：明确无需提取

```text
用户设置 skip_extraction = true
→ shot.status = ready
```

### 路径 C：取消关联 / 替换

```text
原 candidate = linked
→ 用户删除关联 / 替换关联对象 / 清空 scene
→ candidate 回退到 pending
→ shot.status 重新计算
```

## 已接入的自动回写点

当前后端已经接入这些回写动作：

- 提取接口完成后，按镜头同步 `shot_extracted_candidates`
- 提取接口完成后，按镜头同步 `shot_extracted_dialogue_candidates`
- 角色关联成功后，匹配角色候选回写为 `linked`
- 场景 / 道具 / 服装关联成功后，匹配候选回写为 `linked`
- `ShotDetail.scene_id` 设置成功后，场景候选回写为 `linked`
- 删除场景 / 道具 / 服装关联后，对应候选回退为 `pending`
- 同 index 角色被替换时，被顶掉的旧角色候选回退为 `pending`
- `scene_id` 从 A 切到 B，或清空时，旧场景候选回退为 `pending`
- 接受对白候选后，写入 `ShotDialogLine` 并将对白候选回写为 `accepted`
- 忽略对白候选后，将对白候选回写为 `ignored`

## 前端约束

前端页面现在必须遵守下面这条规则：

> 不再自行推导正式 `shot.status`，也不再手动把 `pending/ready` 写回本地状态。

正确做法是：

- 调后端接口
- 使用后端返回的最新 `ShotRead`
- 准备页优先消费后端聚合状态 `ShotPreparationState`
- 用 `shot_extracted_candidates` 展示资产待确认项
- 用 `shot_extracted_dialogue_candidates` 展示对白待确认项

目前 `ChapterStudio` 与 `ChapterShotEditPage` 已经接入这一约束。

## OpenAPI 同步约定

这次改动新增了：

- `GET /api/v1/studio/shots/{shot_id}/preparation-state`
- `GET /api/v1/studio/shots/{shot_id}/extracted-candidates`
- `PATCH /api/v1/studio/shots/{shot_id}/skip-extraction`
- `PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/link`
- `PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/ignore`
- `GET /api/v1/studio/shots/{shot_id}/extracted-dialogue-candidates`
- `PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/accept`
- `PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/ignore`

前端在接口更新后，应主动执行：

```bash
cd front
pnpm run openapi:update
```

不要继续手写一层额外的 request 封装去复制 generated client。

## 准备页聚合状态约定

为了避免前端在“关联/忽略候选”之后自己猜测要刷新哪些局部状态，当前后端已经补了一层准备页聚合状态协议：

- 查询接口：
  - `GET /api/v1/studio/shots/{shot_id}/preparation-state`
- 准备页专用现有关联接口：
  - `POST /api/v1/studio/shots/{shot_id}/preparation-link`
- 聚合状态：
  - `shot`
  - `assets_overview`
  - `dialogue_candidates`
  - `saved_dialogue_lines`
  - `pending_confirm_count`
  - `ready_for_generation`

当前资源候选相关命令接口：

- `PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/link`
- `PATCH /api/v1/studio/shots/extracted-candidates/{candidate_id}/ignore`
- `PATCH /api/v1/studio/shots/{shot_id}/skip-extraction`
- `PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/accept`
- `PATCH /api/v1/studio/shots/extracted-dialogue-candidates/{candidate_id}/ignore`

已经统一返回：

- `ShotPreparationMutationResult`
  - `action`
  - `state`

也就是说，准备页前端后续不应继续在这些动作成功后手写：

- `loadAssetsOverview()`
- `refreshCurrentShot()`
- 再自己拼 `pendingConfirmCount`

而应直接消费后端返回的最新聚合状态。

## 开发建议

后续如果继续扩这条链路，优先级建议是：

1. 继续补“取消关联 -> candidate 回退”的更多边界场景
2. 让章节页、分镜列表页更多消费正式 `status`
3. 如果后续真的出现高频人工语义，再单独引入“人工标记”字段

当前阶段，不建议把人工返工、优先级、跳过等语义混进 `shots.status`。

## 页面职责边界

随着 `shot.status`、候选确认链路和 `video-readiness` 的收口，分镜相关页面现在也有了更明确的职责边界。

### `ChapterShotEditPage`：分镜准备页

这一页的核心任务是：

- 提取资产与对白候选
- 确认资产候选
- 确认对白候选
- 调整标题、备注与基础信息
- 把当前镜头推进到 `shot.status = ready`

可以把它理解成：

```text
单镜头准备台
```

也就是说，凡是会直接影响：

- `skip_extraction`
- 资产候选 `pending / linked / ignored`
- 对白候选 `pending / accepted / ignored`
- `shot.status = pending / ready`

的动作，都应优先放在分镜编辑页完成。

### `ChapterStudio`：分镜生成工作台

这一页的核心任务是：

- 查看单镜头与批量 `video-readiness`
- 生成关键帧与参考图
- 调整视频生成参数
- 生成视频
- 在章节内连续推进多个镜头

可以把它理解成：

```text
章节内的生成工作台
```

它关注的是：

- 当前镜头能不能生成视频
- 还差哪些生成前置条件
- 先生成关键帧还是直接生成视频
- 如何批量推进多个镜头

### 两页的协作关系

推荐主流程如下：

```text
ChapterShotEditPage
→ 提取与确认
→ shot.status = ready
→ 进入 ChapterStudio
→ 查看 video-readiness
→ 关键帧 / 参考图 / 视频参数
→ 生成视频
```

对应到页面职责上，就是：

- 分镜编辑页负责“准备”
- 分镜工作室负责“生成”

因此，`ChapterStudio` 里的“信息确认状态 / 对白状态”更适合作为**诊断入口**，而不是继续承担主要确认动作。
