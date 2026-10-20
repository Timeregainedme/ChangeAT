# ChangeAT（= jellyfish）Staging 部署记录

- **主机**：`ip-172-31-2-3`（EC2 us-east-2a，公网 EIP `18.225.232.63`）
- **域 / 网络**：`ChangeAT-Staging / AWS / Albany, OH`
- **起止时间**：UTC `08:18 ~ 08:55` （2026-10-17）
- **本机部署位置**：`/srv/changeAT`（HEAD = `32fe12a Add acknowledgment section in README`）
- **仓库原型**：`github.com/Timeregainedme/ChangeAT`（仓名是习惯名，内容上是 jellyfish，请参阅 jellyfish 的 README）

> 本文档由 OpenCode 协助产出；**仅作 staging**，未启用 CA、CN2/CUG 等生产姿态。

---

## 1. 部署的实成 / 未实成

**实成**：
- FastAPI、Celery worker、Redis、Nginx、前端 SPA 都在跑
- 公网 HTTPS（自签）已上线，公网 http(80) → 强制 301 跳 https(:9443)

**未做**（按你“晚点时间”安排）：
- 真实域名 / DNS 调整 / Let's Encrypt 证书
- `/srv/changeAT/backend/.env` 里的真实 API key
- SG 中的进一步收紧、ufw 启动

---

## 2. 服务拓扑

| 服务             | systemd unit              | 内部地址               | 公网端口                | 是否 TLS |
|------------------|---------------------------|----------------------|-----------------------|----------|
| FastAPI          | `changeat-api`            | 127.0.0.1:8000       | （仅 nginx 代理）       | —        |
| Celery worker    | `changeat-celery`         | (worker, no port)    | —                     | —        |
| Redis 7          | `redis-server` (apt)      | 127.0.0.1:6379       | —                     | —        |
| Nginx 1.24       | `nginx` (apt)             | 80, 9443             | **80, 9443**          | 9443 only |
| sshd             | `sshd` + `ssh.socket`     | 22, 2222, 443, 8443  | **22, 2222, 443, 8443** | ssh-only |

**ssh 端口** 仍为 443/2222/8443（9222 并未在 ssh.config，但 system 上也启动了）。AGENTS.md 里写的 ` ssh aws-ubuntu-2` 走的是 **443**。

---

## 3. 提供的 URL

| URL                                  | 说明 |
|--------------------------------------|------|
| `http://18.225.232.63/`               | 301 跳到 `https://18.225.232.63:9443/` (HSTS 1 年) |
| `https://18.225.232.63:9443/`         | 前端 SPA（self-signed 会在浏览器里跳红屏） |
| `https://18.225.232.63:9443/api/v1/` | 反代到 127.0.0.1:8000 |
| `https://18.225.232.63:9443/docs`     | FastAPI Swagger |
| `https://18.225.232.63:9443/openapi.json` | FastAPI OpenAPI |

**SHA-256 指纹**（用来验证你访问到的 cert 是同一份）：
`D9:96:66:C0:17:9B:46:C6:AA:49:C6:EC:45:F2:69:80:14:35:B1:E8:B4:C3:BC:F2:CE:F9:CF:32:B6:DC:7D:FF`

**SHA-1 指纹**：
`0C:4E:D5:89:55:18:97:B1:E3:77:F1:02:D2:53:B1:60:C5:74:66:62`

---

## 4. 安装到 EC2 的变动点（可全量回退）

### 4.1 apt 包
- 额外安装：`python3.12-venv python3-pip python3-dev redis-server build-essential pkg-config default-libmysqlclient-dev npm`

### 4.2 系统服务
- 新增 `/etc/systemd/system/changeat-api.service`、`changeat-celery.service`（都已 enable + start）
- `/var/log/nginx/changeat.error.log` 包含 nginx 起失败的记录（其中 8443 / 443 bind 失败被 sshd 占用、后来改 9443）

### 4.3 自签证书
- `/etc/nginx/ssl/changeat-selfsigned.crt` （**365 天、CN=18.225.232.63、SAN IP:18.225.232.63 + DNS:changeat.local,DNS:localhost**）
- `/etc/nginx/ssl/changeat-selfsigned.key` （mode 0600）
- `/etc/nginx/ssl/dhparam.pem` （2048 位，DHE cipher 套件需要）

### 4.4 Nginx vhost
- `/etc/nginx/sites-available/changeat`（active）
- `/etc/nginx/sites-enabled/default` 已删除

### 4.5 AWS Security Group
- 在 `sg-09edda7519c794964`（`atk-ubuntu-sg`）上加了：
  - **ingress TCP 9443 from `0.0.0.0/0`**（本次新增）
  - 现有 ingress 包括：80/0.0.0.0/0、22/18.138.232.218/32、8443/0.0.0.0/0

### 4.6 后端
- `/srv/changeAT/backend/.venv` 是 uv 创建的 venv，全部包从 `uv.lock` 解
- `/srv/changeAT/backend/jellyfish.db` 是空 sqlite schema，由 `init_db.py` 创建

---

## 5. 环境/主机信息备忘

| 资源 | 值 |
|------|----|
| CPU    | 2 vCPU (Intel Xeon Platinum 8488C) |
| RAM    | 3.7 GiB total, 已用 ~1.3 GiB |
| Disk   | 19 GB gp3 / 已用 4.3 GB |
| OS     | Ubuntu 24.04.5 LTS (Noble), kernel `7.0.0-1014-aws` |
| 用户     | ubuntu（sudo NOPASSWD）、root（密码未启用） |
| Python | 3.12.3（apt） |
| pnpm   | 9.15.9（`npm i -g pnpm@9.15.9`）|
| uv     | 0.13.1（在 `/root/.local/bin/uv`） |
| nginx  | 1.24.0（apt） |
| redis  | 7.0.15（apt） |

---

## 6. 下一步（你刚才说“晚点”才做）

### 6.1 域名 / 证书

待你提供以下三项后才能 从 自签 → Let’s Encrypt：

1. 域名（样例：`stage.jellyfish.example.cn`）
2. DNS 服务商后台访问能力（你手动加一条 A 记录指向 `18.225.232.63`）
3. 何时改（计划重启时间 / 零人访问窗口）

**计划动作**：
- 在 DNS 后台加 `stage.jellyfish.example.cn → 18.225.232.63`
- 在 EC2 上 `certbot --nginx -d stage.jellyfish.example.cn`（HTTP-01 challenge，需要 80 通且 SG 已开 80）
- 让 nginx 改为 `listen 443 ssl`（需要先释放 sshd 当前占的 443 —— 可能被同 SG 依赖，必要时调 sshd 到另一个口）

### 6.2 API key 填充顺序

打开 `/srv/changeAT/backend/.env`，按下面表格填。填好后 `sudo systemctl restart changeat-api changeat-celery`。

| Key | 填什么 | 影响 / 备注 |
|-----|--------|-------|
| `IMAGE_API_PROVIDER`              | `pix` / `openai` / `volcengine` | 演员 / 角色 / 道具 / 场景 / 服装 / 镜头帧图片 |
| `IMAGE_API_BASE_URL`              | 例如 `https://example.com/v1/images/generations` | |
| `IMAGE_API_KEY`                   | API key | 填后重启服务 |
| `VIDEO_API_PROVIDER`              | `pix` / `compshare_model_api` / `openai` / `volcengine` | 镜头视频生成 |
| `VIDEO_API_BASE_URL`              | 例如 `https://example.com/v1/videos/generations` | |
| `VIDEO_API_KEY`                   | API key | |
| （可选）`TEXT_API_*`               | 文本供应商 | agent / 剧本提取 |
| （可选）`S3_*`                    | 素材存储 | 本地存储默认为项目内 `\`.local/\` 之类位置 |
| （可选）`CELERY_BROKER_URL`       | Redis URL | 默认是本机 redis，不填即可 |
| （可选）`REDIS_HOST/PORT/PASSWORD` | 如你的 redis 不是 localhost | |
| `CORS_ORIGINS`                   | 逗号分隔 | 默认已含 `http://localhost:7788`、你到时候加 9443 取用 |

填后看 `journalctl -u changeat-api -n 50 -f` 跟踪启动是否 success。

### 6.3 其他以后可能做的几件事

- 起 **ufw**，限制 22/2222/8443/443/80/9443 以外都没必要入口
- 调 SG：加入自己本机公网 IP 的 `22/0.0.0.0/0`，代替现在 `22/18.138.232.218/32`
- 补 **HSTS preload** / **OCSP stapling** （这里在 cert certbot 阶段会默认开）
- 起轮转证书（Let's Encrypt **90d 有效**）
- 调研起点 commit 的 README Acknowledgment section（你要不要看一眼）

---

## 7. 全部动作的完整回退命令（一份留给以后要不要 full uninstall）

```bash
# 1. 停服务
sudo systemctl disable --now changeat-api changeat-celery
sudo rm /etc/systemd/system/changeat-*.service
sudo systemctl daemon-reload

# 2. nginx 还原默认
sudo rm /etc/nginx/sites-enabled/changeat
sudo ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
# backup 现 conf 以防误操
sudo mv /etc/nginx/sites-available/changeat /etc/nginx/sites-available/changeat.bak-$(date +%s)
sudo nginx -t && sudo systemctl reload nginx

# 3. 拿掉自签证书
sudo rm -rf /etc/nginx/ssl/changeat-selfsigned.crt /etc/nginx/ssl/changeat-selfsigned.key /etc/nginx/ssl/dhparam.pem

# 4. 拿掉 SG 里的 9443
aws ec2 revoke-security-group-ingress \
  --group-id sg-09edda7519c794964 \
  --protocol tcp --port 9443 --cidr 0.0.0.0/0 \
  --region us-east-2

# 5. 拿掉部署本体
sudo rm -rf /srv/changeAT

# 6. （可选）拋弃 apt 装的东西。 **需慎重**：可能影响其他项目
sudo apt purge --autoremove \
  python3.12-venv python3-pip python3-dev \
  redis-server build-essential pkg-config default-libmysqlclient-dev npm
```

SSH 接口（22 / 443 / 2222 / 8443）未动，全过程不清零。

---

## 8. 遇到过的几件磕绊（贴在 README 里避免以后重蹈）

1. **nginx `listen 443` 撞 sshd**——ssh.socket 里设了 `ListenStream=443`、`8443`、`2222`。一开始的 443 TLS 尝试 bind 后 0 worker active。后改 9443。
2. **nexttrace 参数 parsing bug**——v1.7.4 --target 必须以唯一 positional 参数传，不能带 flag。报 `unknown arguments 1.1.1.1`。
3. **ChangeAT 仓名 vs jellyfish 名同名**——仓库叫 `Timeregainedme/ChangeAT`，内容上完全与 jellyfish 一致；jellyfish 项目是从 `Forget-C/Jellyfish` fork + 改名的。HEAD 多一个 `32fe12a Add acknowledgment section in README`。
4. **后端 `WorkingDirectory` 必须为 \`/srv/changeAT/backend\`**——sqlite 是相对路径 `jellyfish.db`，不设 systemd working dir 会建到 `/jellyfish.db`。
5. **`pnpm` 在 apt nodejs 18.19 下不默认提供**——装了 npm 然后 `npm i -g pnpm@9.15.9`。corepack 未启用是因为 apt nodejs 不带。

---

## 9. 2026-10-20 增补：MySQL / RustFS / R2 / 前端加载修复

### 9.1 数据库：SQLite → MySQL 8.0

| 项 | 值 |
| --- | --- |
| 版本 | MySQL 8.0.46（Ubuntu apt） |
| 库 / 用户 | `jellyfish` / `jellyfish`（仅 127.0.0.1） |
| 密码存储 | `/root/.mysql_app_pw`、`/home/ubuntu/.mysql_app_pw`（0600） |
| 认证插件 | **必须 `mysql_native_password`**——MySQL 8 默认 `caching_sha2_password`，`aiomysql 0.3` 不支持，会报 `Access denied (1045)` |
| 建表 + seed | `init_db.py` 建 33 张表 → 依次执行 `backend/sql/*.sql`（18 个，纯 MySQL 方言） |
| 结果 | `prompt_templates` 26 条（此前 SQLite 为 0 条，是「提示词页空白」的根因） |
| 回退 | `.env` 里删掉 `DATABASE_URL` 即回到 SQLite |

### 9.2 对象存储：RustFS（自建）→ Cloudflare R2

自建 RustFS 已跑通（1.0.3 + 20GB gp3 EBS + XFS `/data/rustfs0`），随后切换到 R2：

| 项 | 值 |
| --- | --- |
| 桶 | `ai-jellyfish`（APAC） |
| Endpoint | `https://101ba930ddfdac280604d0d4303084ea.r2.cloudflarestorage.com` |
| Region | `auto` |
| 寻址 | `path` |
| 公共读 | **r2.dev Public Development URL**（R2 不支持 `put_bucket_policy`，`NotImplemented`） |
| `S3_PUBLIC_BASE_URL` | `https://pub-6dcd8c3d787044fab566bdda29f8b64b.r2.dev` |

**踩坑**：
1. **R2 不支持 `put_bucket_policy` / `get_bucket_policy`** → 项目里的 `init_storage_public.py` 在 R2 上会失败，公共读必须走 Custom Domain 或 r2.dev。
2. **r2.dev 公共 URL 不含桶名**（由 R2 按桶路由）。写成 `<pub>/<bucket>/<key>` 会 404，正确是 `<pub>/<key>`。
3. RustFS 仍保留（`rustfs.service` + `/data/rustfs0`），可随时回退；确认 R2 稳定后可 `systemctl disable --now rustfs` 并 detach 20GB 卷。

### 9.3 前端加载失败的两个真 bug（已修）

**Bug 1：`env.js` 运行时注入失效**

- 现象：浏览器拿到的 `window.__ENV.BACKEND_URL` 是 `http://localhost:8000`，前端所有 API 请求打到「用户自己电脑的 8000」，全部失败。
- 根因：原用 `sub_filter "BACKEND_URL: ''"` 做替换，但**重新部署 dist 时 `public/env.js` 原版覆盖了 `dist/env.js`**，字面量对不上，注入静默失效。
- 修法：nginx 用 `return 200` 直接生成文件内容，彻底不依赖 `dist/env.js`：

```nginx
location = /env.js {
    add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" always;
    default_type application/javascript;
    return 200 'window.__ENV = window.__ENV || {};\nwindow.__ENV.BACKEND_URL = "";\n';
}
```

**Bug 2：`assets/utils.ts` 把空串兜底成 localhost**

- `window.__ENV?.BACKEND_URL || ... || 'http://localhost:8000'` 用 `||`，空串（合法的「同源」语义）会被兜底成 `localhost:8000`，导致缩略图与素材直链全部失效。
- 修法：优先用 `OpenAPI.BASE`；当其为空时用 `window.location.origin` 作为 `new URL()` 基准，而不是兜底到 localhost。

**Bug 3（附带）：`index.html` 缓存策略**

- dist 每次部署会换 bundle hash 并删除旧文件；入口 HTML 若被缓存，用户会请求**已不存在的旧 chunk** → 白屏 / 加载失败。
- 修法（SPA 标准做法）：

| 资源 | Cache-Control |
| --- | --- |
| `index.html` | `no-cache, no-store, must-revalidate` |
| `env.js` | `no-store, no-cache, must-revalidate, max-age=0` |
| `/assets/*` | `max-age=604800`（7d，文件名带 hash 所以安全） |

### 9.4 页面滚动（`MainLayout` 的 `overflow:hidden` 约束）

`MainLayout` 是 `height:100vh + overflow:hidden` 的应用壳，**每个页面必须自带滚动容器**，否则内容超出视口后被裁切且无法滚动。

- 修复 `ProjectWorkbench`：Tab 内容区 `overflow-hidden` → `overflow-y-auto`（这是「分集 / 分镜页面不能滚」的根因）。
- 修复 `AssetManager`：根节点补 `h-full overflow-y-auto`。
- 已正确的页面：`ChapterShotsPage`（表格自带 `scroll={{y}}`）、`AssetEditPageBase`（`h-full overflow-auto`）、`PromptTemplateManager`、`ChapterStudio`、`VideoEditor`、`VoiceManager`。
- 新增审计脚本 `scripts/audit_page_scroll.py`，用于后续排查同类问题。

### 9.5 域名与 TLS 现状

- 目标 URL：`https://tim.run.place`。
- `run.place` 的 NS 目前仍在 `dnsexit.com`（`freedomain.one` 提供的免费域名），**尚未切到 Cloudflare**，因此 Cloudflare 全托管（含自定义域名、Universal SSL）暂未生效。
- 当前可访问地址仍是 `https://18.225.232.63:9443`（自签证书，浏览器会提示不安全）。
- 已就绪、等 DNS 生效即可启用：ACME 挑战路径（公网 200）、`certbot 2.9.0`、`server_name tim.run.place`、Cloudflare real_ip（22 个官方网段）。

### 9.6 2026-10-20 晚：标准 443 + Let's Encrypt + gzip（已完成）

免费域名的根域 NS 无法改到 Cloudflare（`freedomain.one` 只给子域面板），
因此放弃 Cloudflare 全托管，改走「DNSExit 加 A 记录 + Let's Encrypt」。

**结果**：`https://tim.run.place` 已可用，浏览器绿锁。

| 项 | 值 |
| --- | --- |
| A 记录 | `tim.run.place → 18.225.232.63`（DNSExit，TTL 8h） |
| 证书 | Let's Encrypt，`CN=tim.run.place`，2026-10-20 → 2027-01-18 |
| 自动续期 | `certbot.timer` enabled |
| 证书链校验 | `Verify return code: 0 (ok)` |

**SSH 端口调整**（为腾出 443）：

| 项 | 改前 | 改后 |
| --- | --- | --- |
| sshd 监听 | 22, 2222, 443, 8443 | **22, 2222, 8443** |
| 本机 `~/.ssh/config` | `Port 443` | **`Port 8443`** |

- 配置源：`/etc/ssh/sshd_config.d/99-atk-ports.conf`（移除 `Port 443`）。
  注意 443/8443/2222 是 `sshd-socket-generator` 从该文件自动生成的，不是手写 socket 单元。
- 迁移脚本带自动回滚，日志：`/var/log/ssh-port-migration.log`。
- 兜底：AWS SSM（`amazon-ssm-agent` active）。

**nginx 监听**：

| 端口 | 用途 |
| --- | --- |
| 80 | 301 → `https://$host$request_uri`（不再带端口） |
| **443** | **主入口**，Let's Encrypt 证书 |
| 9443 | 兼容旧链接，同一张 LE 证书 |

**证书权限**（`www-data` 需读私钥）：

- `/etc/letsencrypt/{live,archive}` → `0750 root:ssl-cert`
- `privkey*.pem` → `0640 root:ssl-cert`
- `www-data` 加入 `ssl-cert` 组
- deploy-hook `/etc/letsencrypt/renewal-hooks/deploy/10-nginx-perms.sh`：续期后自动修权限并 reload nginx（续期会新建私钥文件，权限会重置，所以必须靠 hook）

**⚠️ 关键性能修复：gzip**

`/etc/nginx/nginx.conf` 只有 `gzip on;`，`gzip_types` 全被注释 →
**默认只压缩 text/html，JS/CSS/JSON 全部裸传**。

叠加 us-east-2→中国 约 40KB/s 的国际带宽：

| 资源 | 修复前 | 修复后 |
| --- | --- | --- |
| `index-*.js` | 1.79 MB / **44.7 s** | 539 KB / **2.5 s** |
| `index-*.css` | 38 KB | 8 KB / 1.6 s |
| `openapi.json` | 307 KB | 38 KB / 1.3 s |

**这是「前端各种加载失败」的真正主因** —— 不是报错，是 45 秒加载超时。

已启用：`gzip_static`、`gzip_vary`、`gzip_proxied any`、`gzip_comp_level 6`，
`gzip_types` 覆盖 js/css/json/xml/svg/wasm/manifest。

**回退方式**：

```bash
# 恢复 SSH 443
sudo cp /etc/ssh/sshd_config.d/99-atk-ports.conf.bak.<stamp> /etc/ssh/sshd_config.d/99-atk-ports.conf
sudo systemctl daemon-reload && sudo systemctl restart ssh.socket ssh.service
# 本机 ~/.ssh/config 把 Port 8443 改回 443

# 恢复 nginx（自签 9443）
sudo cp /etc/nginx/sites-available/changeat.bak-before443.<stamp> /etc/nginx/sites-available/changeat
sudo nginx -t && sudo systemctl reload nginx

# 恢复 gzip
sudo cp /etc/nginx/nginx.conf.bak.<stamp> /etc/nginx/nginx.conf && sudo systemctl reload nginx
```

---

> 本次部署在 forwarding、redeployment、reading-only 这些动作中没有修改任何你 jellyfish 仓库源文件。部署与仓库完全独立：仓库的源代码 + EC2 上的 \`/srv/changeAT\` 是两份独立副本，必要时你可以 \`rm -rf /srv/changeAT\` 同步环境重拉。
