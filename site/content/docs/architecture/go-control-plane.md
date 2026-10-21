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

## 写方法回落机制（重要）

Nginx 的 `location = ` / `location ~ ` **只匹配路径、不区分 HTTP 方法**。
所以把 `GET /studio/projects` 切给 Go 时，`POST /studio/projects` 也会一起被转过去。

如果 Go 直接返回 405，用户点「创建项目」就会失败 —— 这样踩过一次线上。

因此 Go 侧统一处理：

```go
r.MethodNotAllowed(func(w, r) {
    pythonFallback.ServeHTTP(w, r)   // 透传给 Python
})
```

效果：

| 请求 | 走向 |
|---|---|
| `GET /studio/projects` | Go 实现 |
| `POST /studio/projects` | 回落 Python |
| `PATCH /studio/chapters/{id}` | 回落 Python |

**为什么不按方法在 Nginx 里再分一次**：每条路径要复制一份配置，
漏一条就是一次线上故障，而且新增写方法时要同步两处。

**回落的副作用**：真正应该 405 的请求（如 `DELETE /health`）会变成 404。
这个取舍是有意的 —— 宁可回落保证写操作可用，也不要让一次方法不匹配阻断业务。

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

| 路径 | 状态 | 切流 |
|---|---|---|
| `GET /health` | ✅ | ✅（Nginx `/health` 仍指 Python，探针在 Go 侧独立可用） |
| `GET /api/v1/health` | ✅ | ❌ |
| `GET /api/v1/ready` | ✅ Go 独有 | — |
| `GET /api/v1/auth/me` | ✅ 影子逐字节一致 | ✅ 已切 |
| `GET/HEAD /api/v1/studio/files/{id}/download` | ✅ 影子头级一致 | ✅ 已切 |
| `GET /api/v1/film/tasks/{id}/status` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/film/tasks/{id}/result` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/projects` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/projects/style-options` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/projects/{id}` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/chapters` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/chapters/{id}` | ✅ 影子逐字段一致 | ✅ 已切 |
| `GET /api/v1/studio/files` | ✅ 影子逐字段一致 | ✅ 已切 |

其余 `/api/v1/*` 全部仍由 Python 处理。

## 项目统计（stats）

`GET /api/v1/studio/projects` 与 `{id}` 返回的 `stats` 由 Go 侧**实时聚合**得出，
而不是读 `projects.stats` 列。

背景：`projects.stats` 这一列从建表起就没有写入方，全库都是 `{}`，
前端拿到的章节/角色/场景/道具数量始终是 0。

实现要点（`internal/store/project.go` 的 `LoadStats`）：

| 键 | 口径 |
|---|---|
| `chapters` | `chapters` 表按 `project_id` 计数 |
| `roles` | `characters` 表按 `project_id` 计数（角色是项目内实体） |
| `scenes` | `project_scene_links` 按 `project_id` 去重计数 |
| `props` | `project_prop_links` 按 `project_id` 去重计数 |

- 四条查询**并发**发出，一次 `IN (...)` 覆盖整页项目，不逐项目查。
- 结果与存量 JSON **合并**：只覆盖上面四个键，保留 Python 可能写入的其它键。
- 同时补 `updated_at`（UTC RFC3339），前端按本地时区展示。
- **统计失败不阻断列表**：查询出错时沿用存量 `stats`，不让一次聚合超时把列表变成 500。

## 切流方式

Nginx 里逐条加 location，删掉即回滚：

```nginx
# 精确匹配（优先级最高）
location = /api/v1/auth/me {
    proxy_pass http://127.0.0.1:8001;
}

# 正则匹配（优先于 /api/v1/ 前缀，但低于 = 与 ^~）
location ~ ^/api/v1/studio/files/([^/]+)/download$ {
    proxy_pass http://127.0.0.1:8001;
}
```

注意：`/api/v1/` 前缀 location **不能加 `^~`**，否则正则 location 不参与匹配。
回滚流程：注释该块 → `nginx -t` → `systemctl reload nginx`，无需停 Go 进程。

回滚已验证：注释后请求确实回到 Python（用 Go 日志行数不增长确认），恢复后重新走 Go。

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

## 素材下载的两个细节

**为什么 Go 只做 302。** 生产 21 个文件的 `thumbnail` 全部是 R2 公开 URL，302 覆盖
100% 实际流量。流式代理需要正确处理 `Range` / `206` / `416` / `Content-Range`，
写错会让 `<video>` 无法拖动进度条，因此私有桶（未配公开域名）场景透传给 Python。

**为什么不用 `http.Redirect`。** 它会为 GET 补一段 HTML 提示体（`Content-Length: 144`），
而 Python 的 `RedirectResponse` 是空体。浏览器会忽略 302 的 body，功能无差异，
但影子对比会一直报不一致。改为直接写 `Location` + `302`，两边逐字节相同。

**为什么只认 http/https。** `data:` / `javascript:` 若被当作跳转目标，
一个匿名可访问的下载端点就变成开放重定向与 XSS 入口。

## 任务状态查询的一个隐式依赖

Python 的 `_datetime_ts` 用 `datetime.timestamp()` 转换 MySQL 的 naive datetime，
这会**按进程本地时区**解释。当前服务器 `TZ=UTC` 且 `.env` 未设 `TZ`，
所以等价于「按 UTC 取 Unix 秒」，Go 侧因此可以直接 `t.Unix()`。

**如果将来服务器改成非 UTC 时区，两套实现必须一起调整**，否则同一任务的
`started_at_ts` 在切流前后会差整个时区偏移。写在这里是因为这种依赖不会报错，
只会在某天换机器后静默偏 8 小时。

另外 `elapsed_ms` 的语义是「未开始 → null」，不是 0；进行中的任务用
`now - started` 实时计算，已结束用 `finished - started`。前端据此区分
「还没开始」与「刚开始 0 毫秒」。

## 只读先行的原因

项目/章节目前只接管了 `GET`。这是刻意的：

- 读接口出错，表现是「看到错数据」，用户能发现、也能回滚；
- 写接口出错，表现是「数据被写坏」，可能不可逆，且影子对比无法验证
  （同一个写请求不能同时发给两个服务）。

因此写路径的处理方式是：先让只读接口在生产跑一段时间、确认无差异，
再单独设计写操作的对比方案（例如镜像写到影子库，而不是镜像到同一张表）。

## 分页参数必须严格解析

Python 用 FastAPI 的 `Query(ge=1, le=100)` 声明分页参数，非法输入直接 422。
Go 侧若「解析失败就回退默认值」，`page_size=abc` 会静默变成 10，
前端拿到第一页却以为翻页生效 —— 这种不报错的错误比直接失败更难排查。

422 的文案也复刻了 FastAPI 的格式：

```text
query.page_size: Input should be less than or equal to 100
query.page: Input should be a valid integer, unable to parse string as an integer
```

目的是让切流前后逐字节一致，影子对比不用逐条解释差异。

## 只读接口的切流现状

真正有流量的只读接口已基本迁完：

```
鉴权     auth/me
素材     files 列表 + files 下载（含 302 到对象存储）
项目     projects 列表 + style-options + 单条
章节     chapters 列表 + 单条
任务     tasks 列表 + status + result
```

剩下的 `studio/*` 厚业务（镜头提取、资产合并、生成准备）都在
`services/studio/` 的 11k 行里，迁移等于重写，长期由 Go 反代。

## 尚未接管

`studio/*`、`film/*` 的其余接口。按计划只有薄接口值得迁：

| 类别 | 迁移建议 |
|---|---|
| `auth` / `me` / `workspace` | 迁 Go（薄、鉴权密集） |
| `project` / `chapter` 元数据 | 迁 Go（薄 CRUD） |
| `file` 上传/下载/代理 | 迁 Go（IO 密集，Go 优势明显） |
| `task` 创建/状态/取消/SSE | 迁 Go（长连接与状态机） |
| `shot` / `asset` / 提取 / 合并 | **长期留 Python**（`services/studio/` 11k 行，迁等于重写） |

厚业务由 Go 反代 `/internal/*`，前端仍只看到 `/api/v1/*`。
