# 生产 Nginx 配置

本目录是生产机 `/etc/nginx/` 相关配置的**权威副本**。

## 为什么放在仓库里

切流改造前，生产的 `sites-enabled/dyeingtime` 只存在于服务器上，
每次改动只有 `/root` 下的手工备份 —— 没有 review、没有历史、重建服务器时无法恢复。
切流后这份文件成了「哪条路径走 Go、哪条走 Python」的唯一事实来源，
再不纳入版本管理，就无法回答「上周切了哪些路径」。

## 文件对应关系

| 仓库路径 | 服务器路径 |
|---|---|
| `deploy/nginx/sites-enabled/dyeingtime` | `/etc/nginx/sites-enabled/dyeingtime` |
| `deploy/nginx/snippets/dyeingtime-proxy.conf` | `/etc/nginx/snippets/dyeingtime-proxy.conf` |

## 同步方向

**仓库 → 服务器**（唯一方向）。服务器上的手工改动必须回写到仓库，
否则下次部署会覆盖掉它们 —— 这里踩过一次：服务器有 15 个后端文件的
未提交改动，导致 `git pull` 直接 `Aborting`，生产代码处于「旧版本 + 本地补丁」
的混合状态，无法追溯实际运行的是什么。

```bash
# 部署
scp deploy/nginx/sites-enabled/dyeingtime aws-ubuntu-2:/tmp/nginx-site
scp deploy/nginx/snippets/dyeingtime-proxy.conf aws-ubuntu-2:/tmp/nginx-snippet
ssh aws-ubuntu-2 'sudo mv /tmp/nginx-site /etc/nginx/sites-enabled/dyeingtime && \
  sudo mv /tmp/nginx-snippet /etc/nginx/snippets/dyeingtime-proxy.conf && \
  sudo nginx -t && sudo systemctl reload nginx'

# 反向核对：服务器上有改动时，先拉回来对比再提交
ssh aws-ubuntu-2 'cat /etc/nginx/sites-enabled/dyeingtime' > /tmp/remote-site
diff -u deploy/nginx/sites-enabled/dyeingtime /tmp/remote-site
```

## 结构说明

### 探针分工

| 路径 | 目标 | 语义 |
|---|---|---|
| `/health` | Go :8001 | 边缘进程存活（**不查库**） |
| `/api/v1/ready` | Go :8001 | 可接业务流量（**查库**） |
| `/api/v1/health` | Python :8000 | 应用存活 |

`/health` 曾落进 `location /` 的 SPA fallback，返回 200 + index.html，
导致外部探活永远「健康」、监控形同虚设。已用精确匹配修掉。

### 切流开关

Go 已接管的路径逐条列出，每块都带注释说明回滚方式：

```nginx
location = /api/v1/studio/projects {   # 精确匹配，优先级最高
    proxy_pass http://127.0.0.1:8001;
    include snippets/dyeingtime-proxy.conf;
}
location ~ ^/api/v1/studio/(projects|chapters)/[^/]+$ {   # 正则，单段 ID
    proxy_pass http://127.0.0.1:8001;
    include snippets/dyeingtime-proxy.conf;
}
```

**回滚 = 注释掉对应块 + `nginx -t` + reload**，不需要停 Go 进程。

### 两个必须知道的 Nginx 细节

1. **`/api/v1/` 前缀块不能加 `^~`**。加了之后正则 location 不参与匹配，
   切流会静默失效——请求照常走回 Python，表面看一切正常。
2. **正则 `[^/]+$` 才能只匹配单段 ID**。写成 `[^/]+` 会吃掉
   `/projects/{id}/production-readiness` 这类子路径，把未实现的接口转给 Go。

### 公共转发头

`dyeingtime-proxy.conf` 抽出了 6 行公共配置（`Host` / `X-Real-IP` /
`X-Forwarded-For` / `X-Forwarded-Proto` / `X-Request-ID` / HTTP 版本）。
7 条切流路径就是 42 行重复，漏掉 `X-Forwarded-For` 会让审计只看到 127.0.0.1，
漏掉 `Host` 会让 CORS 与重定向判断出错——两者都不报错，只在下游显现。

## 与 `deploy/docker/nginx.conf` 的关系

那份是 **docker-compose 本地环境**用的，只有 `env.js` 与 SPA fallback，
不涉及 API 分流。两者不要混用：本地没有 Go 控制面，也不做逐路径切流。
