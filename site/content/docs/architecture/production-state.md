---
title: "生产环境当前状态"
description: "记录生产机的服务拓扑、已执行迁移、已切流路径与回滚方式，供运维与故障排查时快速定位。"
weight: 21
---

> 本文是**运维快照**，随部署更新。架构原理见
> [Go 控制面](/docs/architecture/go-control-plane/) 与
> [多租户与工作区隔离](/docs/architecture/workspace-multitenancy/)。

## 服务拓扑

| 服务 | systemd unit | 端口 | 说明 |
|---|---|---|---|
| Nginx | `nginx` | 80 / 443 / 9443 | 静态资源 + API 分流 |
| Python API | `dyeingtime-api` | 127.0.0.1:8000 | FastAPI，厚业务与写操作 |
| Python Worker | `dyeingtime-celery` | — | Celery，生成任务执行 |
| Go 控制面 | `dyeingtime-go` | 127.0.0.1:8001 | 已接管的高频只读接口 |

数据库 MySQL 本机 `127.0.0.1:3306`，Redis 本机，对象存储 Cloudflare R2。

Go 二进制在 `/srv/dyeingtime-go/api`（**仓库外**，不污染 git 工作区）。
Python 代码与 `.env` 在 `/srv/dyeingtime/backend`。

## 配置来源

- Python 与 Go 共用 `/srv/dyeingtime/backend/.env`（Go 由 systemd `EnvironmentFile` 注入）
- 关键变量：`DATABASE_URL`、`JWT_SECRET`、`SECRETS_KEY`、`S3_*`
- **`SECRETS_KEY` 轮换会导致既有 provider API Key 无法解密**，改动前须重新录入

## 已执行的数据迁移

| 文件 | 内容 | 状态 |
|---|---|---|
| `sql/022-add-workspaces.sql` | workspaces / workspace_members / projects.workspace_id | ✅ |
| `sql/023-add-workspace-to-tasks.sql` | generation_tasks.workspace_id | ✅ |
| `sql/024-add-audit-logs.sql` | audit_logs | ✅ |

三份脚本均幂等，可重复执行。**字符集必须是 `utf8mb4_unicode_ci`**：
存量表用的是这个，MySQL 8/9 建库默认是 `0900_ai_ci`，混用会让外键报 3780。

回填结果：默认工作区 `ws-default`，存量用户 2 人全部加入，存量项目全部挂载。

## 已切流路径（Nginx → Go）

| 路径 | 备注 |
|---|---|
| `/api/v1/auth/me` | 精确匹配 |
| `/api/v1/studio/files` | 精确匹配 |
| `/api/v1/studio/files/{id}/download` | 正则，302 到 R2 |
| `/api/v1/studio/projects` | 精确 |
| `/api/v1/studio/projects/style-options` | 精确 |
| `/api/v1/studio/projects/{id}` | 正则 |
| `/api/v1/studio/chapters` | 精确 |
| `/api/v1/studio/chapters/{id}` | 正则 |
| `/api/v1/film/tasks` | 精确 |
| `/api/v1/film/tasks/{id}/status` | 正则 |
| `/api/v1/film/tasks/{id}/result` | 正则 |

其余路径仍由 Python 处理。**写操作（POST/PATCH/DELETE）全部在 Python**。

## 回滚方式

### 回滚单条路径

```bash
sudo cp /etc/nginx/sites-enabled/dyeingtime /root/nginx-backup-$(date +%s)
sudo vim /etc/nginx/sites-enabled/dyeingtime   # 注释对应 location 块
sudo nginx -t && sudo systemctl reload nginx
```

无需停 Go 进程，不影响其他路径。**已实测**：注释后请求回到 Python，
以 Go 日志行数不增长为证。

### 回滚全部切流

```bash
sudo python3 - <<'EOF'
from pathlib import Path
p = Path("/etc/nginx/sites-enabled/dyeingtime")
s = p.read_text()
start = s.index("    # ---- Go 控制面已接管路径")
end = s.index("    location /api/v1/ {")
p.write_text(s[:start] + s[end:])
EOF
sudo nginx -t && sudo systemctl reload nginx
```

### 回滚 Go 代码

保留上一版二进制即可：

```bash
sudo systemctl stop dyeingtime-go
sudo cp /srv/dyeingtime-go/api.prev /srv/dyeingtime-go/api
sudo systemctl start dyeingtime-go
```

## 验证命令

```bash
# 服务状态
systemctl is-active nginx dyeingtime-api dyeingtime-celery dyeingtime-go

# Go 侧
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/api/v1/ready   # 200（含 DB ping）

# Python 侧
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health         # 200

# 经 Nginx（需 token）
TOKEN=$(cd /srv/dyeingtime/backend && .venv/bin/python -c "...")
curl -s -o /dev/null -w '%{http_code}\n' \
  --resolve tim.run.place:443:127.0.0.1 \
  -H "Authorization: Bearer $TOKEN" https://tim.run.place/api/v1/studio/projects
```

## 部署 Go 新版本

交叉编译后上传（服务器不装 Go 工具链）：

```bash
cd backend/go
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /tmp/dyeingtime-api ./cmd/api
scp /tmp/dyeingtime-api aws-ubuntu-2:/tmp/dyeingtime-api
ssh aws-ubuntu-2 'sudo systemctl stop dyeingtime-go && \
  sudo cp /srv/dyeingtime-go/api /srv/dyeingtime-go/api.prev && \
  sudo mv /tmp/dyeingtime-api /srv/dyeingtime-go/api && \
  sudo chmod +x /srv/dyeingtime-go/api && \
  sudo systemctl start dyeingtime-go'
```

## 片段打包导出

`GET /api/v1/studio/timeline/projects/{project_id}/clips-archive` 返回 zip：
把项目下每个已生成视频的片段原样打包，未生成的片段写进包内 `MANIFEST-未打包片段.txt`。

- 与「导出成片」互补：成片用 ffmpeg 串成一个 mp4，要求全部片段都有视频；
  打包允许部分缺失，用于先把素材交出去。
- 在内存里构建 zip（中央目录在末尾，真正流式需先算偏移，几十个片段场景不划算）。
- 单个片段读对象存储失败只跳过并记入 MANIFEST，不整包失败。

## 部署前端

前端是纯静态产物，部署 = 替换 `/srv/dyeingtime/front/dist`，不需要重启任何服务。

```bash
cd front
pnpm exec tsc --noEmit && pnpm test && pnpm test:e2e   # 本地验证
pnpm exec vite build

# 服务器侧先留存上一版，便于回滚
ssh aws-ubuntu-2 'mv /srv/dyeingtime/front/dist /srv/dyeingtime/front/dist.old-$(date +%Y%m%d-%H%M%S)'
rsync -az ./dist/ aws-ubuntu-2:/srv/dyeingtime/front/dist/
```

要点：

- **不要 reload nginx**：root 目录替换即时生效。
- `/env.js` 由 nginx 的 `location = /env.js` 直接返回内容，**不读 dist 里的文件**，
  因此换 dist 不会把 `BACKEND_URL` 变回 `localhost:8000`。
- `/index.html` 是 `no-store`，用户刷新即拿到新 bundle；旧 hash 的 chunk 会 404，
  这是刻意取舍（不保留历史版本）。需要平滑过渡时保留 `dist.old-*` 并回滚。
- 静态资源在 `dist/static/`（`assetsDir` 特意改名，避免与 `/assets` 路由冲突）。

验证：

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://tim.run.place/          # 200
curl -s https://tim.run.place/env.js | grep BACKEND_URL                  # ""
```

回滚：

```bash
ssh aws-ubuntu-2 'cd /srv/dyeingtime/front && rm -rf dist && mv dist.old-<时间戳> dist'
```

## 已知风险

| 风险 | 说明 |
|---|---|
| 时区依赖 | Python 的 `datetime.timestamp()` 按进程本地时区解释；当前 TZ=UTC 才与 Go 的 `t.Unix()` 等价。**换非 UTC 时区需两侧同时改** |
| 平台配置无权限分级 | `prompts` / `llm providers` 任何 editor 都可修改。团队内部使用是设计取舍，对外多租户前必须收敛 |
| 写路径未切 | 若将来要切，需要先设计「镜像写影子库 + 结果比对」，不能直接镜像到同一张表 |
| Go 侧无审计 | 审计中间件只在 Python。切写路径前需给 Go 补 |
