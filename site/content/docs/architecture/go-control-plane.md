---
title: "Go 控制面"
description: "记录已上线的 Go 控制面：进程拓扑、已接管接口、影子对比机制与切流原则。"
weight: 20
---

> 本文属于“当前架构”文档，描述**已经运行**的 Go 控制面。
> 尚未接管的接口在文末列出，不要按「已经迁完」理解。

## 当前拓扑

```text
浏览器
  └── Nginx :443
        ├── /api/v1/*  → 127.0.0.1:8000  (Python API，全部流量)
        ├── /api/v1/auth/me → 127.0.0.1:8001  (Go 控制面，尚未切流，仅影子验证)
        └── 静态资源    → /srv/dyeingtime/front/dist

Go 控制面 :8001  systemd: dyeingtime-go.service
Python API :8000  systemd: dyeingtime-api.service
Python worker     systemd: dyeingtime-celery.service
```

Go 进程常驻内存约 **8 MB**（RSS），对 4 GiB 的机器几乎没有影响。

## 目录结构

```text
backend/go/
  cmd/api/main.go          入口 + 优雅关闭
  internal/config          环境变量加载、DATABASE_URL → Go DSN 转换
  internal/db              MySQL 连接池（启动即 Ping）
  internal/response        {code,message,data,meta} 信封
  internal/middleware      request_id / 访问日志 / panic 恢复 / RequireAuth
  internal/auth            HS256 JWT 校验
  internal/store           只读查询（按主键取一行）
  internal/handler         health / auth
  internal/oapi            由 front/openapi.json 生成的 400 个类型
  Makefile                 build / test / vet / generate
```

## 配置来源

**只读环境变量，不引入第二份配置文件。**

生产由 systemd 的 `EnvironmentFile=/srv/dyeingtime/backend/.env` 注入，
与 Python 共用同一份 `.env`。这是刻意的：让两个进程连同一个库、用同一个
`JWT_SECRET`，避免「切流后 Go 连了另一个库」这类最难排查的事故。

`internal/config.ParseMySQLDSN` 负责把 Python 风格的
`mysql+aiomysql://user:pass@host:3306/db` 转成 driver DSN：

```text
user:pass@tcp(host:3306)/db?parseTime=true&loc=UTC&charset=utf8mb4
```

密码含 `@` 时按**最后一个** `@` 切分；缺省端口补 3306。

## 探针语义

| 端点 | 语义 | 查库 |
|---|---|---|
| `GET /health` | 进程存活 | 否 |
| `GET /api/v1/health` | 与 Python 的 `/api/v1/health` 对齐 | 否 |
| `GET /api/v1/ready` | 可接收业务流量 | **是** |

`Live` 不查库是刻意的：存活探针若依赖外部组件，数据库抖动会导致进程被误杀重启，
反而放大故障。`Ready` 会真 Ping，切流后 Nginx 用它决定是否把请求转给 Go。

`/api/v1/ready` 是 Go 独有端点，Python 侧没有对应实现，因此不改动既有契约。

## 切流原则

**只注册已经真正实现的路径。**

未接管的路径保持 404，让 Nginx 明确把流量留给 Python。
若提前注册空 handler，前端会拿到 200 空壳并把它误读成「没有数据」。

这也是 `oapi-codegen` **只生成模型、不生成 server 路由**的原因：
整表生成会产出一堆「已注册但未实现」的空 handler，把「这条路径还没接管」藏起来。

## 契约对齐

### 响应信封

`internal/response` 定义 `{code, message, data, meta}`，与 Python 的 `ApiResponse`
逐字段一致。`code` 恒等于 HTTP 状态码，`meta` 恒为 `null`（非分页时）。

### 时间序列化（已踩过的坑）

Python 的 `datetime.isoformat()` 对 MySQL 的 naive datetime **不输出时区后缀**：

```text
Python: "created_at": "2026-10-20T12:33:30"
Go(错): "created_at": "2026-10-20T12:33:30Z"
```

`Z` 会被前端 `new Date()` 当 UTC，而无后缀串被当本地时间 —— 同一行数据相差 8 小时。
Go 侧必须用 `2006-01-02T15:04:05.999999`（`.999999` 使尾随零被省略，
对齐 Python 在微秒为 0 时不输出小数部分的行为）。

**这类问题只有影子对比能发现**：tsc 不报错、JSON 能解析、11 个叶子字段只差 1 个。

### 鉴权失败语义

| 场景 | 响应 |
|---|---|
| 缺令牌 / 令牌非法 / 已过期 | 401「未登录，请先登录」+ `WWW-Authenticate: Bearer` |
| 用户已删除或已停用 | 401「登录状态无效，请重新登录」 |

停用账号不返回 200 + `is_active=false`：停用后不应能继续读写业务数据，
前端看到 401 会回到登录页。

JWT 校验固定 HS256（`WithValidMethods`）、强制 `exp`、30 秒 leeway 容忍时钟漂移。
`alg=none` 与 RS256 一律拒绝 —— 后者是经典的算法混淆攻击面。

## 已接管接口

| 路径 | 状态 |
|---|---|
| `GET /health` | ✅ 实现并验证 |
| `GET /api/v1/health` | ✅ 实现并验证 |
| `GET /api/v1/ready` | ✅ 实现并验证（Go 独有） |
| `GET /api/v1/auth/me` | ✅ 实现，影子对比逐字节一致，**尚未切流** |

其余 `/api/v1/*` 全部仍由 Python 处理。

## 影子对比方法

不切流量，同时请求两个端口，做字段级 diff：

```bash
TOKEN=$(... 用 JWT_SECRET 签发 ...)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/auth/me > /tmp/py.json
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8001/api/v1/auth/me > /tmp/go.json
# 递归展开 JSON 后逐叶子比较，输出 DIFF 行
```

判定标准：**0 个字段差异**才允许切流。存在差异时先判断是哪边错了
——本次就是 Go 侧错了（多出 `Z`），而非 Python。

## 构建与部署

交叉编译（服务器不装 Go 工具链）：

```bash
cd backend/go
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /tmp/dyeingtime-api ./cmd/api
scp /tmp/dyeingtime-api aws-ubuntu-2:/tmp/dyeingtime-api
ssh aws-ubuntu-2 'sudo systemctl stop dyeingtime-go && \
  sudo mv /tmp/dyeingtime-api /srv/dyeingtime-go/api && \
  sudo chmod +x /srv/dyeingtime-go/api && \
  sudo systemctl start dyeingtime-go'
```

二进制放在 `/srv/dyeingtime-go/`（仓库外），避免污染 git 工作区。

## 尚未接管

`studio/*`、`film/*` 的全部其余接口。按计划只有薄接口值得迁：

| 类别 | 迁移建议 |
|---|---|
| `auth` / `me` / `workspace` | 迁 Go（薄、鉴权密集） |
| `project` / `chapter` 元数据 | 迁 Go（薄 CRUD） |
| `file` 上传/下载/代理 | 迁 Go（IO 密集，Go 优势明显） |
| `task` 创建/状态/取消/SSE | 迁 Go（长连接与状态机） |
| `shot` / `asset` / 提取 / 合并 | **长期留 Python**（`services/studio/` 11k 行，迁等于重写） |

厚业务由 Go 反代 `/internal/*`，前端仍只看到 `/api/v1/*`。
