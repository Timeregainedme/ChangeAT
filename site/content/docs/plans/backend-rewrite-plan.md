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
- **当前规模**（2026-10-21 实测）：37,554 行 Python / 232 个文件 / 119 个路径（156 个 operation）/ 54 张表 / 541 个测试用例
- **当前基线**：`pytest` 539 passed（2 deselected）；`tsc --noEmit` 通过；OpenAPI 契约比对通过
- **决策方向**：**Go 控制面 + Python AI 执行面** 的混合架构

> 数字口径说明：早期版本记为「3.6 万行 / 228 文件 / 130 接口 / 33 张表 / 320 测试」，
> 已随 Google 登录、动作拍点、音频、演员音色等功能落地而增长。后续每次更新本文件请以
> `pytest --collect-only -q | tail -1`、`front/openapi.json` 的 paths/operations 数与
> `grep -rh __tablename__ app/models | sort -u | wc -l` 的实测值为准，禁止手抄旧数。

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

| 模块 | 路径 | 状态（2026-10-21 实测） |
|---|---|---|
| HTTP 路由 | `backend/app/api/v1/routes/` | 119 路径 / 156 operation，需迁到 Go |
| 业务服务 | `backend/app/services/` | 16,056 行；21 个 service 仍返回 `ApiResponse`，10 个反向 import `app.api`，需解耦 |
| 数据模型 | `backend/app/models/` | 54 张表，25 处 JSON 列，无 `workspace_id` / `owner_id` |
| AI Agent | `backend/app/chains/agents/` | 保留在 Python，LangChain 使用很轻 |
| 供应商适配 | `backend/app/core/integrations/` | 保留在 Python |
| 任务执行器 | `backend/app/core/tasks/` | 保留在 Python |
| 任务调度 | `backend/app/core/task_manager/` + Celery | 1,037 行；状态机迁到 Go |
| 数据库引擎 | `backend/app/core/db.py` + `db_sync.py` | 双 runtime，Go 化后删除同步引擎 |
| 迁移 | `backend/sql/001~021` | 无 Alembic，需补 baseline |
| 鉴权 | `backend/app/api/v1/__init__.py` | 统一挂 `require_auth`；尚无 workspace 维度 |
| 契约基线 | `front/openapi.json` + `backend/scripts/check_openapi_contract.py` | 已冻结，CI 门禁已生效 |

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
- **Python worker**：保留 FastAPI 无关，仅保留 worker 入口；**跨语言任务投递走 Redis Stream**
- **数据库**：MySQL 8，新增 Alembic baseline
- **队列**：Redis + asynq（Go 侧）／Redis Stream（跨语言边界），替代 Celery
- **对象存储**：R2 / S3，Go 与 Python 共用
- **认证**：Go 签发/校验 JWT；Python worker 只信任内部 queue

> **关于 asynq 与 Python 的边界（重要修正）**
>
> 早期版本写「用 asynq Python 客户端消费任务」，这个前提不成立：asynq 是 Go 库，
> 其队列协议是自定义 protobuf over Redis，官方**只提供 Go 实现**（另有非官方 Rust 移植），
> 没有可用的 Python 客户端。
>
> 因此跨语言投递统一改用 **Redis Stream**：Python 侧的 `redis` 库原生支持 `XADD`/`XREADGROUP`，
> Go 侧同样可读，双方不需要共享序列化协议之外的东西。asynq 若引入，仅限 Go 进程内部的
> 任务编排，不承担跨语言职责。
>
> 若评估后认为换队列收益不足，可退化为「Go 通过 internal HTTP 端点投递给 Python worker」，
> 保持一把 Redis 锁的语义即可。该决策点见 §9 Phase 3。

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

### Phase 0：地基（第 1–14 天）—— 基本完成

- [x] `uv sync --frozen` 修好测试环境，pytest collection 0 error
  - 根因是包名 `jellyfish-backend` → `dyeingtime-backend` 后未重新 sync，
    `bcrypt` / `pyjwt` 实际未安装，表现为 23 个 collection error。
- [x] 修复契约漂移导致的测试失败：130 failed → 0 failed（539 passed）
  - 121 例是 `require_auth` 未被测试覆盖导致的假失败（统一挂依赖后集体 401）；
  - 9 例是改名/契约漂移（库名期望、`thumbnail` 字段、草稿对象形态、`shots` 属性）。
  - 「取消任务被标记为 failed」经排查**不是**取消逻辑缺陷，而是测试替身缺属性抛
    `AttributeError` 走异常路径所致。
- [x] 冻结 `/api/v1` OpenAPI，加 contract 门禁
  - 新增 `backend/scripts/check_openapi_contract.py`，直接由 `app.main:app` 生成规格，
    不需要起服务；`--update` 写回，默认只比对。
  - 顺带修掉一个随机性缺陷：文件下载端点用 `api_route(methods=["GET","HEAD"])` 注册，
    FastAPI 取 `route.methods` 首个元素生成 operationId，而 `methods` 是 set，
    顺序随 `PYTHONHASHSEED` 变化 —— 同一份代码在不同机器产出不同 operationId，
    前端已因此生成出 `...DownloadHead` 与 `...DownloadHead1` 两个重名方法。
    现已拆成独立端点并显式声明 `operation_id`。
  - 契约基线由 minified 单行改为格式化，使契约变更的 diff 可审。
- [x] CI 加 pytest + tsc + openapi-contract 三门禁
- [x] 设计 workspace / member / role / audit 表（见 Phase 1）
- [ ] 引入 Alembic baseline —— **推迟到 Phase 1 表结构定型后**
  - 原因：baseline 必须对真实 MySQL 做 autogenerate 才准确（JSON 列、索引前缀长度等
    方言差异），而当前只有 compose 里的 MySQL，本机没有可连实例；
  - 且 Phase 1 马上新增 6 张表与多个列，此时建 baseline 需要立刻重建；
  - 过渡期继续用 `sql/022` 起顺序编号，等 Phase 1 收口后一次性 `alembic stamp head` 接管。
- [ ] 配置 DB 连接池、Celery 并发上限（短期兜底）

### Phase 1：多租户（第 15–30 天）

- 在现有 Python 后端实现 workspace 模型、RBAC、project 归属
- provider API key 加密
- audit log 中间件
- 所有业务接口强制 workspace scoping
- 测试覆盖多租户场景

### Phase 2：Go 控制面 MVP（第 31–60 天）

**接管边界（重要）**：Go 只接管「薄资源」——鉴权、用户、workspace、项目/章节元数据、
文件、任务状态查询、审计。**不接管「厚业务」**：`app/services/studio/` 现有 11,251 行，
其中分镜提取候选、实体合并、视频准备度等逻辑密度极高，迁 Go 等于重写且收益接近零。
这类接口长期保留在 Python，由 Go 反向代理 `/internal/*` 暴露，前端仍只看到 `/api/v1/*`。

- Go 项目骨架：config / db / queue / storage / middleware
- oapi-codegen 从**冻结的** `front/openapi.json` 生成类型与路由
- 迁移顺序（每步单独可回滚）：
  1. `health`, `auth`, `me`
  2. `workspace`, `project` CRUD
  3. `file` upload/download/proxy
  4. `task` create / status / cancel / list（含 SSE）
  5. `chapter` 元数据读写（不含分镜提取）
- 厚业务反代：`studio/*`、`film/*` 透传到 Python `/internal/*`
- Python 侧删除已迁走的 HTTP 路由，仅保留 worker 与 internal 入口
- Nginx 按路径分流，旧接口保留可回滚
- **切流前必须完成 shadow compare**：Nginx 镜像双发，逐字段比对 Go 与 Python 响应，
  0 字段不一致才允许切换。这是唯一的回滚安全网，不可跳过。

### Phase 3：Python AI Worker 改造（第 61–75 天）

- 跨语言投递接入 **Redis Stream**（不是 asynq，理由见 §7）
- `generation_tasks` 状态机由 Go 管理，worker 仅汇报
- worker 上传生成物后通过 stream 消息或 internal API 回写 `files` / `generation_task_links`
- 删除 Celery，删除 `core/db_sync.py`
- **决策点**：若 Redis Stream 的改造收益不足（Celery 当前稳定、Go 投递也可用 internal
  HTTP 绕过），本阶段可整体放弃，退回「Go → internal HTTP → Python worker」。
  该阶段是全计划中性价比最低的一段，不应为了一致性强行推进。

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

- **契约测试**：Go 返回与 Python 旧实现字段级一致；基线由 `check_openapi_contract.py` 冻结
- **契约门禁**：任何 PR 改动后端 schema 而未同步 `front/openapi.json` 与 generated client 一律红
- **集成测试**：testcontainers-go + MySQL + Redis
- **Python worker 测试**：保留现有 541 个测试，只跑 worker 相关
- **接口测试约定**：`conftest.py` 的 autouse fixture 默认放行 `require_auth`，用例只验响应壳；
  需要断言未登录行为的用例显式 `pop` 该覆盖
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
| 前端契约破坏 | `check_openapi_contract.py` + CI 拦截（已生效） |
| 契约基线不稳定 | 禁止用 `api_route(methods=[...])` 注册多方法端点；多方法必须拆开并显式 `operation_id`，否则 operationId 随 `PYTHONHASHSEED` 漂移 |
| 测试不可复用 | 541 个 Python 测试保留给 worker，Go 另写测试；接口测试统一放行 `require_auth`，避免鉴权变更再次引发集体假失败 |
| 团队不熟悉 Go | Phase 0 先 spike auth + project，2 周内验证 |
| 多会话并发改同一工作区 | 提交前必须 `git status` 逐文件确认；禁止 `git add -A`。本项目曾发生并发会话把无关改动合并进单个提交的情况，需按文件分组提交 |
| 单机容量不足 | 现部署为 2 vCPU / 4 GiB，同时跑 Go + Python worker + MySQL + Redis 内存紧张（MySQL ≈500 MB，Python worker 峰值 ≈1 GB）；上 Go 前先测内存上限，否则先扩配置 |

## 14. 验收标准

- [ ] 多用户登录后只能看到自己 workspace 的项目
- [ ] provider API key 在 DB 中不是明文
- [ ] Go API 承载 80% 以上 HTTP 流量（含反代到 Python 的部分）
- [ ] Python worker 仍能正常执行图片/视频/音频生成
- [ ] 前端无代码改动即可连上新后端
- [ ] Celery 完全下线（若 Phase 3 按 §9 决策点整体放弃，则本条改为「Celery 可继续运行」）
- [x] CI 绿（pytest + tsc + openapi-contract）

## 15. 关键参考文件

- `backend/app/main.py`
- `backend/app/dependencies.py`
- `backend/app/api/v1/__init__.py`（统一鉴权挂载点）
- `backend/app/core/db.py`
- `backend/app/core/db_sync.py`
- `backend/app/core/task_manager/`
- `backend/app/core/tasks/`
- `backend/app/models/`
- `backend/app/services/`
- `backend/app/api/v1/`
- `backend/pyproject.toml`
- `backend/scripts/check_openapi_contract.py`（契约门禁）
- `front/openapi.json`（冻结的契约基线）
- `deploy/compose/docker-compose.yml`
- `部署说明.md`
- `技术评审报告.md`
