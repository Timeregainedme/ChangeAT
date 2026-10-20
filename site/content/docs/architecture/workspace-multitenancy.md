---
title: "多租户与工作区隔离"
description: "记录当前已生效的工作区模型、角色矩阵、请求上下文与数据隔离范围。"
weight: 18
---

> 本文属于“当前架构”文档，描述**已经生效**的多租户实现与隔离边界。
> 尚未覆盖的部分在文末单列，不要把它当成“多租户已完成”来读。

## 为什么需要

改造前，`/api/v1` 只区分“已登录 / 未登录”。任何登录账号都能：
列出全部项目、按 ID 读取任意镜头、上传与下载任意素材、看到全公司的生成任务。

对一个内部 MCN 制作团队，这意味着实习生账号与项目负责人看到的是同一份数据。
引入工作区是为了给“数据属于谁”一个可判定的边界，而不是只加一个 UI 概念。

## 数据模型

```text
workspaces                 (id, name, slug, owner_id, is_active)
  └── workspace_members    (workspace_id, user_id, role, is_active)  -- (ws, user) 唯一
  └── projects             (workspace_id NOT NULL, created_by)
        └── chapters
              └── shots
                    └── shot_details / shot_dialog_lines / shot_frame_images
        └── characters / scenes / props / costumes  （经 project_*_links 关联）
```

关键取舍：

**只有 `projects` 加 `workspace_id`，其余 53 张表不动。**
章节、镜头、资产都通过项目间接归属，鉴权时只需校验一次项目归属就能覆盖其下全部资源；
若给每张表都加列，等于把同一个条件在几十处查询里重复一遍，漏一处就是一次泄露。

**角色放在成员表里，不建 `roles` / `permissions` 两张表。**
当前团队是“个位数成员、权限只有能否改内容这一层”，完整 RBAC 会让每次鉴权多两次 join，
收益不足。等出现“按项目授权”的真实需求再升级，`WorkspaceRole` 枚举可平滑映射为初始数据。

**成员退出置 `is_active=false`，不删行。**
否则历史操作记录里的 `user_id` 会变成悬空引用。

**`workspaces.owner_id` 用 `ON DELETE RESTRICT`。**
工作区是有价值的业务容器，不允许因为误删账号而连带删除全部项目。

## 角色矩阵

| 角色 | 等级 | 读 | 写（增删改 / 触发生成） | 管理成员 |
|---|---|---|---|---|
| `viewer` | 1 | ✅ | ❌ | ❌ |
| `editor` | 2 | ✅ | ✅ | ❌ |
| `admin` | 3 | ✅ | ✅ | ✅（预留） |
| `owner` | 4 | ✅ | ✅ | ✅ |

`viewer` 只读的设计意图：外部审片 / 甲方预览账号不应能触发模型生成，
因为生成会真实消耗供应商额度。

## 请求上下文

工作区经 **`X-Workspace-ID` 请求头**传递，不塞进 URL：

- 不必给 119 个路径批量加路径参数，前端只需设一个全局头；
- 与“项目归属哪个工作区”解耦，同一项目 ID 不会被拼进另一个租户的 URL。

解析优先级（`app/dependencies.py::get_workspace_context`）：

1. `X-Workspace-ID` 请求头；
2. 路径参数 `workspace_id`（为将来 REST 风格路由预留）；
3. 都没有时，取该用户加入的第一个工作区。

第 3 条是刻意保留的兼容路径：当前全部存量用户只属于一个工作区，
因此前端不改一行也能正常工作。等前端真正支持切换工作区时再依赖请求头。

## 失败语义：越权一律 404

访问自己不是成员的工作区、或读取别的工作区的资源，统一返回：

```json
{ "code": 404, "message": "工作区不存在", "data": null, "meta": null }
```

**不返回 403。** 403 等于告诉调用方“这个 ID 是真的，只是你没权限”，
把其他租户的资源 ID 变成可枚举的探测面。

例外：用户一个工作区都没加入时返回 403（`当前账号未加入任何工作区`）。
这不是资源不存在，而是账号没被分配，需要明确提示而不是给一个空列表
——空列表会被误读为“项目都删了”。

## 隔离实现

`app/api/scoping.py` 是唯一的归属校验入口，路由不再直接 `db.get(Project, id)`。

核心机制是 router 级守卫：

```python
router = APIRouter(dependencies=[
    Depends(require_scoped_resource("shot_id", get_shot_in_workspace)),
])
```

为什么挂 router 而不是逐个端点：`shots` 有 23 个端点、`entities` 有 11 个，
逐个加依赖时漏一个就是一个越权口子，而且新增端点极易忘记补。
router 级守卫让**新端点默认受保护**。

守卫行为：

- 路径里没有该参数（列表接口、`/runtime-summary`）→ 跳过归属校验，
  列表自身的工作区过滤由 service 的 `workspace_id` 参数负责；
- 有该参数 → 校验归属，不通过抛 404；
- 写方法（`POST/PUT/PATCH/DELETE`）额外要求 editor 及以上。

### 归属链的两类资产（容易搞错）

| 资产 | 归属方式 |
|---|---|
| `characters` | 项目内资产，**自身直接持有 `project_id`** |
| `scenes` / `props` / `costumes` / `actors` | **全局资产**，可跨项目复用，自身没有 `project_id`，归属经 `project_{scene,prop,costume,actor}_links` 确定 |

对全局资产采用「任一关联项目属于当前工作区即放行」的语义：
同一场景被两个工作区的项目引用时，两个工作区都能看到它，但都改不到对方的关联。

## 隔离覆盖范围

### 已隔离

| 路由 | 方式 |
|---|---|
| `studio/projects` | 项目级 + `apply_workspace_filter` |
| `studio/chapters` | 经 project join |
| `studio/shots`（含 5 个子 router） | router 级守卫 |
| `studio/entities` | router 级守卫（含资产两类归属链） |
| `studio/image-tasks` | router 级守卫（actor/character/asset/project/shot） |
| `studio/timeline` | router 级守卫（project） |

### 尚未隔离

| 路由 | 阻塞原因 |
|---|---|
| `studio/files` | `files` 表自身无 `project_id`，归属只在 `file_usages` 里 |
| `film/task_status` | `generation_tasks` 无 `workspace_id`，只能经多态 `task_links` 反查 |
| `studio/audio-tasks` | 资源 ID 在请求体里，非路径参数 |
| `film/generated_video`、`film/tasks_images` | 同上 |
| `studio/shot-character-links` | 无路径 ID |

补齐这几处需要新增 `files.workspace_id` 与 `generation_tasks.workspace_id` 两列
（迁移 023），并把 `workspace_id` 贯通到任务创建链路（`TaskManager.create` 的
5 个调用点）。**在此之前，不要认为多租户已经完整。**

## 迁移注意事项

### 022 必须幂等

compose 的启动顺序是 `init_db`（SQLAlchemy `create_all`）→ `mysql-init-sql`
（按文件名排序 apply 全部 SQL）。在全新库上 `create_all` 已按 models 建好新表，
脚本硬写 `CREATE TABLE` 会直接撞车让整条 compose 起不来；存量库则需要脚本补列。
两种场景都要跑通，所以：建表用 `IF NOT EXISTS`，加列/索引查 `information_schema`，
回填用 `INSERT IGNORE`。

### 字符集必须先对齐

生产库的存量表是 `utf8mb4_unicode_ci`，而 MySQL 8/9 的建库默认是
`utf8mb4_0900_ai_ci`。新表若用默认 collation，
`projects.workspace_id → workspaces.id` 的外键会直接失败：

```text
ERROR 3780 (HY000): Referencing column 'workspace_id' and referenced column 'id'
in foreign key constraint 'fk_projects_workspace' are incompatible
```

022 因此把 collation 修正放在**所有 CREATE 之前**。
原因：`CREATE TABLE IF NOT EXISTS` 遇到已存在的表时，MySQL 仍会校验外键列兼容性，
此时若引用表 collation 未对齐，一样报 3780。

## 存量数据回填策略

在这台生产库上执行 022 的实际结果：

| 项 | 结果 |
|---|---|
| 默认工作区 | `ws-default`（owner 取最早创建的账号） |
| 成员 | 2 人全部加入：最早账号为 `owner`，其余为 `editor` |
| 项目 | 2 个项目全部挂到 `ws-default` |
| 外键 | 5 条全部建立（projects×2、workspace_members×2、workspaces×1） |

回填原则是**宁可多给权限，也不能让存量用户登录后发现自己的项目全没了**。
因此既有用户一律先给 `editor`（而非 `viewer`），后续按需下调。

## 验证方式

```bash
# 契约与测试
cd backend && uv run pytest -q
cd front && pnpm run typecheck

# 线上冒烟（token 由 JWT_SECRET 签发）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health          # 200
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/studio/projects  # 200
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" -H "X-Workspace-ID: ws-nope" \
  http://127.0.0.1:8000/api/v1/studio/projects                                   # 404
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8000/api/v1/studio/projects                                   # 401
```
