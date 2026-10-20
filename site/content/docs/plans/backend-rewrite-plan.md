---
title: "Backend Rewrite Plan"
weight: 10
description: "DyeingTime 后端重写计划：Go 控制面 + Python AI 执行面，支撑 MCN 内部生产系统。"
---

> 本文属于“任务计划”文档，描述后端重写的目标、架构与分阶段实施路径。

## 1. 项目背景

- **项目名称**：DyeingTime（仓库历史名 Jellyfish）
- **定位**：AI 短剧生产工作台，服务 MCN 内部制作团队
- **当前后端**：Python 3.11+ / FastAPI / SQLAlchemy 2 async / Pydantic v2 / Celery + Redis / MySQL / S3-compatible 对象存储
- **当前规模**：约 3.6 万行 Python / 228 个文件 / 130 个接口 / 33 张表 / 320 个测试用例
- **决策方向**：**Go 控制面 + Python AI 执行面** 的混合架构

## 2. 重写目标

1. **多人协作**：引入 workspace / member / RBAC，让 MCN 团队可按项目协作
2. **安全合规**： provider API key 加密存储、操作审计、资源隔离
3. **性能与稳定性**：Go 承载高并发 HTTP 与任务调度，Python 专注 AI 生成
4. **可维护性**：控制面与执行面解耦，单张表单一写入方
5. **契约稳定**：保持 `/api/v1` URL 与响应结构不变，前端无感切换

## 3. 非目标

- 不迁移数据库（保留 MySQL）
- 不引入微服务（保持模块化单体）
- 不改前端路由或页面结构
- 不一次性重写全部 130 个接口

## 4. 当前状态速览

| 模块 | 路径 | 状态 |
|---|---|---|
| HTTP 路由 | `backend/app/api/v1/routes/` | 需迁到 Go |
| 业务服务 | `backend/app/services/` | 21 个 service 仍返回 `ApiResponse`，10 个反向 import `app.api.utils`，需解耦 |
| 数据模型 | `backend/app/models/` | 33 张表，20 个 JSON 列，无 `workspace_id` / `owner_id` |
| AI Agent | `backend/app/chains/agents/` | 保留在 Python，LangChain 使用很轻 |
| 供应商适配 | `backend/app/core/integrations/` | 保留在 Python |
| 任务执行器 | `backend/app/core/tasks/` | 保留在 Python |
| 任务调度 | `backend/app/core/task_manager/` + Celery | 状态机迁到 Go，队列由 asynq 替代 |
| 数据库引擎 | `backend/app/core/db.py` + `db_sync.py` | 双 runtime，Go 化后删除同步引擎 |
| 迁移 | `backend/sql/001~019` | 无 Alembic，需补 baseline |

## 5. 目标架构

```text
backend/
  go/                          # 新增：Go 控制面
    cmd/api/                   # 入口
    internal/
      config/                  # 环境配置
      db/                      # sqlc + MySQL
      queue/                   # asynq 客户端
      storage/                 # S3/R2 SDK
      auth/                    # JWT、bcrypt
      workspace/               # workspace、member、role
      project/                 # 项目、章节
      shot/                    # 镜头、资产关联
      asset/                   # 角色/场景/道具/服装
      file/                    # 上传/下载/代理
      task/                    # 任务状态机、创建、取消、查询
      audit/                   # 审计日志
      llmconfig/               # provider/model 配置的只读/管理 API
      middleware/              # 鉴权、workspace scoping、request_id、日志
      openapi/                 # oapi-codegen 生成代码
  app/                         # 缩减后的 Python AI Worker
    workers/                   # asynq 消费入口
    chains/agents/             # 剧本拆分、提取、分析 Agent
    core/integrations/         # 供应商适配器
    core/tasks/                # 任务执行器
    services/studio/generation/# 生成准备（base/context/submission/preview）
    core/storage.py            # worker 上传生成物
  alembic/                     # 新增：数据库迁移（先 baseline，后续用）
```

## 6. 核心边界

| 数据 | 写入方 | Python 如何更新 |
|---|---|---|
| `users`, `workspaces`, `workspace_members`, `roles` | Go | Python 只读 |
| `projects`, `chapters`, `shots`, `assets` | Go | Python 只读 |
| `files` | Go 创建；Python worker 上传生成物时创建 | 通过 internal API 或 queue 消息 |
| `generation_tasks` | Go 创建；Python worker 更新 status/result/error | 通过 asynq 任务结果回写 |
| `generation_task_links` | Go | Python 只读 |
| `audit_logs` | Go | Python 不写 |

## 7. 技术选型

- **Go**：chi / echo + oapi-codegen + sqlc + asynq + aws-sdk-go-v2 + slog + OpenTelemetry
- **Python worker**：保留 FastAPI 无关，仅保留 worker 入口；用 `asynq` Python 客户端消费任务
- **数据库**：MySQL 8，新增 Alembic baseline
- **队列**：Redis + asynq（替代 Celery）
- **对象存储**：R2 / S3，Go 与 Python 共用
- **认证**：Go 签发/校验 JWT；Python worker 只信任内部 queue

## 8. 数据库变更（必须在 Go 化前完成）

1. 新增 `workspaces` 表
2. 新增 `workspace_members` 表（user_id + workspace_id + role）
3. 新增 `roles` / `permissions` 或 enum
4. 给 `projects` 加 `workspace_id`、`created_by`
5. 给所有业务查询加 `workspace_id` 过滤
6. `providers.api_key` 改为加密存储（Fernet）
7. 新增 `audit_logs` 表
8. 新增 `cost_usage` 或扩展 `audit_logs` 记录每次生成的模型、token、预估费用

## 9. 90 天实施计划

### Phase 0：地基（第 1–14 天）

- `uv sync --frozen` 修好测试环境，pytest collection 0 error
- 引入 Alembic，以当前 schema 为 baseline
- 设计 workspace / member / role / audit 表
- 冻结 `/api/v1` OpenAPI，加 contract test
- CI 加 pytest + tsc + openapi-diff
- 配置 DB 连接池、Celery 并发上限（短期兜底）

### Phase 1：多租户（第 15–30 天）

- 在现有 Python 后端实现 workspace 模型、RBAC、project 归属
- provider API key 加密
- audit log 中间件
- 所有业务接口强制 workspace scoping
- 测试覆盖多租户场景

### Phase 2：Go 控制面 MVP（第 31–60 天）

- Go 项目骨架：config / db / queue / storage / middleware
- oapi-codegen 从 OpenAPI 生成类型与路由
- 迁移顺序：
  1. `health`, `auth`, `me`
  2. `workspace`, `project` CRUD
  3. `file` upload/download/proxy
  4. `task` create / status / cancel / list（含 SSE）
  5. `shot`, `chapter`, `asset` read/CRUD
- Python 侧删除对应 HTTP 路由，仅保留 worker
- Nginx 按路径分流，旧接口保留可回滚

### Phase 3：Python AI Worker 改造（第 61–75 天）

- 接入 asynq Python 客户端
- `generation_tasks` 状态机由 Go 管理，worker 仅汇报
- worker 上传生成物后通过 queue 或 internal API 回写 `files` / `generation_task_links`
- 删除 Celery，删除 `core/db_sync.py`

### Phase 4：收尾（第 76–90 天）

- 删除旧 Python HTTP 层死代码
- 统一日志、trace、metrics
- 压力测试与慢查询优化
- 文档更新（architecture + plans）

## 10. API 契约规则

- URL 路径不变：`/api/v1/*`
- 响应信封保持 `{code, message, data, meta}`
- 新增聚合接口：
  - `GET /api/v1/studio/projects/{id}/board`（看板聚合）
  - `GET /api/v1/tasks/{id}/events`（SSE）
- 错误码新增字符串 `error_code` 用于业务分类，保留数字 `code` 兼容前端
- 所有接口携带 `workspace_id`（路径或 header）

## 11. 测试策略

- **契约测试**：Go 返回与 Python 旧实现字段级一致
- **集成测试**：testcontainers-go + MySQL + Redis
- **Python worker 测试**：保留现有 320 个测试，只跑 worker 相关
- **双跑对比**：Nginx shadow 模式对比 Go vs Python 响应

## 12. 部署与迁移

- 本地：新增 `deploy/go/Dockerfile`，compose 中替换 `backend` 服务为 Go API
- 生产：systemd 新增 `dyeingtime-api.service`（Go），逐步停掉 Python API
- 回滚：Nginx 路径改回 Python 即可
- 数据库：Alembic 管理，Go 和 Python 共用同一张 MySQL

## 13. 风险与规避

| 风险 | 规避 |
|---|---|
| Go/Python 双写冲突 | 按表划分写入 owner，禁止双写 |
| 任务状态不一致 | 状态机在 Go，worker 只汇报，不自主改状态 |
| 前端契约破坏 | OpenAPI contract test + CI 拦截 |
| 测试不可复用 | 320 个 Python 测试保留给 worker；Go 写新测试 |
| 团队不熟悉 Go | Phase 0 先 spike auth + project，2 周内验证 |

## 14. 验收标准

- [ ] 多用户登录后只能看到自己 workspace 的项目
- [ ] provider API key 在 DB 中不是明文
- [ ] Go API 承载 80% 以上 HTTP 流量
- [ ] Python worker 仍能正常执行图片/视频/音频生成
- [ ] 前端无代码改动即可连上新后端
- [ ] Celery 完全下线
- [ ] CI 绿（pytest + Go test + tsc + openapi-diff）

## 15. 关键参考文件

- `backend/app/main.py`
- `backend/app/dependencies.py`
- `backend/app/core/db.py`
- `backend/app/core/db_sync.py`
- `backend/app/core/task_manager/`
- `backend/app/core/tasks/`
- `backend/app/models/`
- `backend/app/services/`
- `backend/app/api/v1/`
- `backend/pyproject.toml`
- `deploy/compose/docker-compose.yml`
- `部署说明.md`
- `技术评审报告.md`
