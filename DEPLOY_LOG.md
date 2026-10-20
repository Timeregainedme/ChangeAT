# ChangeAT（= jellyfish）Staging 部署记录

> **2026-10-21 品牌变更**：产品对外名称改为 **DyeingTime**，仓库同步改名为
> `Timeregainedme/DyeingTime`（GitHub 侧改名；历史条目中的 `ChangeAT / jellyfish`
> 字样保留原样，仅作为历史记录）。服务端目录 `/srv/changeAT`、systemd 单元
> `changeat-api` / `changeat-celery`、内部包名 `jellyfish-backend` / `jellyfish-frontend`
> 均属于内部标识，未做重命名（改动需要重建 venv/lock 与服务单元，收益低风险高）。

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

### 9.7 2026-10-20：模型供应商配置 + 账号登录

**供应商与模型**（按 `供应商配置.md` 落库，api_key 留空待填）

| 供应商 | base_url | 能力 | 状态 |
| --- | --- | --- | --- |
| `DeepSeek` | `https://api.deepseek.com/v1` | 文本 | active |
| `PIX` | `https://pix.token6688.com` | 图片、视频 | active |
| `优云智算 模型 API` | `https://cp.compshare.cn` | 视频、音频 | active |

- 8 个模型记录：`deepseek-flash` / `deepseek-v4-pro`（text）、`gpt-image-2.5-flare` / `gpt-image-2.5-sunburst`（image）、
  `minimax-h3`（PIX 备用）/ `MiniMax-H3`（优云智算，**默认**）（video）、`IndexTTS-2.5` / `IndexTTS-2.5-custom`（audio）
- `model_settings` 单行已指向四个默认模型
- **api_key 全部为空**，需登录后在「模型管理 → 供应商」逐个填写

**认证**

| 项 | 值 |
| --- | --- |
| 账号 | `admin`（可用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 覆盖重建） |
| 密码存储 | bcrypt 哈希，仅存 `password_hash`，接口不回显 |
| 令牌 | JWT HS256，默认 12 小时（`JWT_EXPIRE_MINUTES`） |
| 密钥 | `JWT_SECRET`（48 字节 url-safe，写入 `.env`，**无默认值**；缺失时拒绝签发） |
| 建表 | `users`（`init_db.py` 依赖 `app.models.auth` 导入，已补） |
| 初始化 | `cd backend && .venv/bin/python init_admin.py`（幂等，已存在则重置密码） |

**鉴权范围**

| 路径 | 是否需要登录 |
| --- | --- |
| `/api/v1/health` | 否 |
| `/api/v1/auth/login` `/auth/me` `/auth/logout` | 否 |
| `/api/v1/film/*` `/llm/*` `/studio/*` `/script_processing/*` | **是** |

Celery worker 内部为函数调用，不经 HTTP，不受影响。

**⚠️ 待办**

1. **立即修改默认密码**：`admin` / `admin123` 是公开在对话里的弱口令，
   staging 可接受，但接入真实团队前必须更换。
2. **填写三个供应商 API Key**（DeepSeek / PIX / 优云智算），否则提交生成任务会报
   `Provider api_key is empty`。
3. **Google 登录尚未接入**，需先在 Google Cloud Console 建 OAuth 2.0 Client：
   - 授权重定向 URI：`https://tim.run.place/api/v1/auth/google/callback`
   - 拿到 `client_id` / `client_secret` 后即可实现（后端加 `/auth/google/*`，
     前端加一个按钮；账号密码登录作为兜底保留）。

### 9.8 2026-10-20：修复 /assets 路由与静态目录同名冲突（404）

**现象**：访问资产编辑页 `/assets/costumes/<id>/edit` 返回 404，nginx 日志：

```
open() "/srv/changeAT/front/dist/assets/costumes/costume-xxx/edit" failed (2: No such file or directory)
```

**根因**：前端路由与静态资源目录重名。

| 角色 | 路径 |
| --- | --- |
| 前端路由 | `/assets/costumes/:costumeId/edit` 等 |
| nginx 静态目录 | `location /assets/` → `dist/assets/`（vite 默认 `assetsDir`） |

`location /assets/` 的前缀匹配优先级高于 `location /` 里的 SPA fallback，
因此这些前端路由被当作静态文件请求，永远走不到 `try_files ... /index.html`。

**修复**：静态资源目录改名 `assets` → `static`。

- `front/vite.config.ts`：`build.assetsDir = 'static'`
- nginx：`location /assets/ { alias .../dist/assets/ }` → `location /static/ { alias .../dist/static/ }`

**验证**（14 条前端路由全部 200 + `text/html`）：

```
/assets                                    200  text/html
/assets/costumes/<id>/edit                 200  text/html
/assets/actors|scenes|props/<id>/edit      200  text/html
/projects/<p>/chapters/<c>/shots           200  text/html
/projects/<p>/chapters/<c>/studio          200  text/html
/projects/<p>/editor                       200  text/html
```

静态资源 `/static/*` 正常，gzip 生效（主 chunk 1,023,089 → 319,655 字节）。

**教训**：给 SPA 配置静态资源目录时，必须检查是否有同名前端路由。
若前端保留 `/assets` 路径，静态目录应改用 `/static` 或其他不冲突的名字。

### 9.9 2026-10-20：修复生成图片在前端裂图（thumbnail 走了受鉴权代理）

**现象**：R2 里图片存在且公开可访问，但前端资产页图片全部裂图。

**排查结论**：数据关联完全正确，问题在 API 返回的 `thumbnail` 形态。

| 访问方式 | 结果 |
| --- | --- |
| `<img src="/api/v1/studio/files/<id>/download">`（无 token） | **401** ❌ |
| 同一路径带 `Authorization` 头 | 200 ✅ |
| `files.thumbnail` 里的 R2 公开 URL（无鉴权） | 200 ✅ |

**根因**：`backend/app/services/studio/entity_thumbnails.py` 硬编码
`DOWNLOAD_URL_TEMPLATE = "/api/v1/studio/files/{file_id}/download"`。
而 `studio` 路由整体挂了 `require_auth`，浏览器 `<img>` 无法携带
`Authorization` 头，因此一律 401。R2 桶已配置公共读，本不需要后端代理。

**修复**：优先返回 `files.thumbnail`（对象存储的公开 URL），
仅当该列为空（例如换成私有桶、未配公开域名）时才回退到受鉴权代理路径。
批量查询避免 N+1：一次 `select id, thumbnail from files where id in (...)`。

**验证**（10 个实体全部通过）：

```
prop     5 个  → 全部 200，R2 公开 URL
scene    3 个  → 全部 200
costume  2 个  → 全部 200
character 3 个 → 无缩略图（未发起过角色图生成任务，character_images.file_id 为 NULL）
```

**注意**：`character` / `actor` 的图片需要单独发起生成任务；仅创建
`*_images` 占位记录（`file_id = NULL`）不会产生缩略图。

### 9.10 2026-10-20：素材下载端点改为匿名 + 302 重定向到对象存储

**现象**：视频生成提示词预览里的参考图（角色/场景/道具/服装）全部显示不出来。

**根因**：前端全站 **24 处** 使用 `buildFileDownloadUrl(fileId)`，拼出的是
`/api/v1/studio/files/{fileId}/download`。该端点挂在 `studio` 路由下，
整体受 `require_auth` 保护；而浏览器 `<img src>` / `<video src>` **无法携带
Authorization 头**，于是全部 401 → 裂图。

这与 9.9 的 `thumbnail` 问题是同一根因的不同表现，区别在于：
- 9.9 修的是「API 返回的 URL 字段」
- 9.10 修的是「前端按 file_id 自行拼出的下载 URL」

**修复（两处）**：

1. `backend/app/api/v1/routes/studio/files.py`
   把 `download` 端点从受保护的 `router` 移到新增的 `public_router`。
2. `backend/app/api/v1/__init__.py`
   单独挂载 `studio_files.public_router`（不附带 `require_auth`），
   其余 studio 路由保持不变。

3. `backend/app/services/studio/files.py`
   `build_download_response` 增加短路：若 `files.thumbnail` 是绝对 URL
   （对象存储公开地址），直接 **302** 重定向，不再后端流式代理。

**为什么匿名是可接受的**：
- 素材本就存放在已配置公共读的 R2 上，`files.thumbnail` 就是公开 URL；
- `file_id` 为 UUID、对象 key 带随机 hash，均不可枚举；
- 匿名按 file_id 取用**不比现状更不安全**，却能让浏览器直接渲染。

**额外收益**：视频不再经 EC2 转发（数百 MB 级别），
Range 请求交给 R2 处理，出网带宽与 CPU 都省下来。

**验证**：

| 检查 | 结果 |
| --- | --- |
| 匿名 `GET /studio/files/<id>/download` | **302 → R2 → 200 image/jpeg** |
| 带 token 同上 | 302（同样重定向） |
| `GET /studio/files`（列表）无 token | **401**（仍受保护） |
| `/studio/projects`、`/llm/*`、`/film/*` 无 token | 401（仍受保护） |
| `Range: bytes=0-1023` | **206**、1024 字节（视频 seek 正常） |

视频提示词预览的 4 类参考图实测：

```
characters 护工           200  233,246 bytes
props      手表           200  293,753 bytes
costumes   护工护理工作服   200  228,155 bytes
scene      深夜卧室        200  263,004 bytes
```

### 9.11 2026-10-20：修复图片任务失败（下载供应商 CDN 超时 + error 字段为空）

**现象**：`image_generation` 任务失败，`error` 字段为**空字符串**，无法定位。

**排查**：`journalctl -u changeat-celery` 拿到完整 traceback：

```
httpx.ReadTimeout
  image_task_runner.py:417  run_image_generation_task
  image_task_runner.py:83   _persist_images_to_assets
  utils/files.py:84         create_file_from_url_or_b64
                            resp = await client.get(url, ...)
```

**根因（两个叠加）**：

1. **下载超时过短**：`create_file_from_url_or_b64` 在 `httpx_timeout is None`
   时没有显式设置 timeout，于是落回 **httpx 默认 5 秒**。
   而供应商（PIX）出图后返回的是它自己的 CDN 直链，后端需要把图抓回来再上传
   R2。在 us-east-2 跨洋链路上，抓 200-300KB 图片经常超过 5 秒 → `ReadTimeout`。
   此时供应商侧**已经扣费出图**（日志 `billing.actual_cost_micro_usd: 5258`），
   属于纯损失。

2. **error 字段为空**：`httpx.ReadTimeout("")` 的 `str()` 返回空字符串，
   `task_executor._mark_failed(task_id, str(exc))` 写库即为空，
   前端与数据库都看不到失败原因。

**修复**：

- `utils/files.py`：
  - `DEFAULT_DOWNLOAD_TIMEOUT_S = 120.0`（不再落回 5s）
  - `DEFAULT_DOWNLOAD_RETRIES = 3`，对 `ReadTimeout` / `ConnectTimeout` /
    `RemoteProtocolError` / `ReadError` 做指数退避重试（1s、2s）
  - 显式 `follow_redirects=True`（CDN 常见 302 到实际存储）
  - 重试耗尽后抛 `RuntimeError`，消息内拼接**异常类型**与 URL，
    避免上层再遇到「str 为空」
- `services/worker/task_executor.py`：
  - 新增 `_format_task_error(exc)`，`str(exc)` 为空时回退为
    `"{异常类型}（该异常无文本消息）"`
  - 全部 4 处异常分支（HTTPException / Exception ×2 / TimeoutError）统一走该函数

**验证**：拿日志里那张真实导致超时的 CDN 图片重跑：

```
修复前：81.7s 后 httpx.ReadTimeout，任务 failed，物品丢失
修复后：3.61s 成功写入 R2
```

`_format_task_error` 单测式验证：

```
httpx.ReadTimeout('')     → 'ReadTimeout（该异常无文本消息）'
httpx.ReadTimeout('timed out') → 'timed out'
ValueError('明确错误')      → '明确错误'
```

**遗留**：失败任务 `84b7bd310e07470b90575b8dcc2a2580`（角色图，13:29）不会自动
重跑，需要在前端重新发起生成。

### 9.12 2026-10-20：修复分镜参考图显示不全（复用实体时未建立镜头关联）

**现象**：分镜编辑页「关联图片（参考图）」显示不全，部分镜头一张图都没有。

**排查**：不是前端渲染问题，是**关联数据缺失**。

| 表 | 修复前 | 说明 |
| --- | --- | --- |
| `shot_extracted_candidates` 中 `linked` 状态 | 角色 12 / 道具 6 / 场景 6 / 服装 6 | 候选都说「已关联」 |
| `shot_character_links` | **3** | 实际只写了 3 条 |
| `project_prop_links` | 5 | |
| `project_scene_links` | 3 | |
| `project_costume_links` | 2 | |

典型例子：镜头 2「护工推门手电光束照向卧床老人」的 6 个候选全部 `linked`，
但 `linked-assets` 只返回 1 条（手电筒）。

**根因**：`batch_candidate_assets.py`（一键提取资产）的循环里：

```python
if existing_id is None:
    entity_id = await _create_entity_from_candidate(...)  # create_entity 内部会写关联表
else:
    entity_id = existing_id                               # ← 只复用 ID，没有任何关联写入

await mark_linked_by_name(...)                            # 只把候选标记为 linked
```

`create_entity` 内部会调用 `upsert_project_link` / `upsert_shot_character_link`
建立关联，但「复用已有实体」的分支完全跳过了这一步。
于是只有**首次出现该实体的那个镜头**建立了关联，后续镜头虽然候选显示
已关联，`linked-assets` 却查不到 → 参考图缺失。

这正是「7 个镜头引用 12 次角色，但 `shot_character_links` 只有 3 条」的成因。

**修复（代码）**：

- `batch_candidate_assets.py` 新增 `_link_existing_entity_to_shot()`：
  对已存在实体补写对应关联（character → `shot_character_links`，
  scene/prop/costume → `project_*_links`），带幂等判断避免重复插入。
- existing 分支改为调用该函数。

**修复（历史数据）**：一次性回填脚本遍历所有 `linked` 且
`linked_entity_id` 非空的候选，补写缺失关联。

```
检查 30 个 linked 候选
  补写关联: 30
  跳过    : 0
  失败    : 0
```

**验证**：

| 关联类型 | 修复前 | 修复后 |
| --- | --- | --- |
| 角色 | 3 | **12** |
| 道具 | 5 | **6** |
| 场景 | 3 | **6** |
| 服装 | 2 | **6** |

`linked-assets` 返回的参考图总数 **7 → 26 张**；镜头 2 由 1 条变 6 条。

**遗留**：镜头 7 的「场景」仍为空，属提取阶段未识别出场景，与关联写入无关。
部分资产无缩略图（如「旁白」角色）是因为从未发起过该实体的图片生成任务。

### 9.13 2026-10-20：补齐系统依赖 ffmpeg/ffprobe（时间线导出成片）

**现象**：导出成片失败，报「服务器未安装 ffprobe，无法导出成片」。

**根因**：时间线导出走 `app/services/studio/timeline.py`，通过
`asyncio.create_subprocess_exec` 调用系统 `ffmpeg` / `ffprobe`，
用于「先把各分镜视频归一化到统一规格（scale+pad+setsar+fps），再 concat 拼接」。

仓库的 `deploy/docker/backend.Dockerfile` 第 11 行**已声明** `ffmpeg`，
但本环境是 **apt + systemd 部署（非 Docker）**，构建阶段不会执行 Dockerfile，
因此这个系统依赖被漏掉了。

**修复**：

```bash
apt-get install -y --no-install-recommends ffmpeg
# → ffmpeg 6.1.1-3ubuntu5 / ffprobe 6.1.1，/usr/bin/ 下，ubuntu 用户可直接执行
```

**完整的外部命令依赖清单**（全仓库仅此两个）：

| 命令 | 用途 |
| --- | --- |
| `ffmpeg` | 分镜视频归一化 + concat 拼接成片 |
| `ffprobe` | 探测输入视频规格（分辨率/帧率/是否有音轨） |

**导出链路烟雾测试（实测通过）**：

```
1. 造两段不同规格视频：640x360@25（无音轨）+ 1280x720@30（有音轨）
2. 规格统一：都转成 720x1280@30；无音轨的自动用 anullsrc 补静音轨
3. concat 拼接：-f concat -c copy（无损）
4. ffprobe 校验产物：h264 + aac，时长 4.04s，86KB
```

所需滤镜/源全部可用：`scale` / `pad` / `setsar` / `fps` / `anullsrc` / `concat`，
编码器 `libx264` / `aac` 齐全（Ubuntu 官方包为完整版，非精简构建）。

**注意（重建实例时必做）**：apt + systemd 部署路径没有 Dockerfile 自动带依赖，
重建主机后需手动补齐：`python3.12-venv redis-server build-essential pkg-config
default-libmysqlclient-dev npm mysql-server ffmpeg xfsprogs`。

### 9.14 2026-10-20：完成一次全项目跑通，修复导出成片与下载端点问题

用户完整跑了一遍「剧本 → 分镜 → 图片 → 视频 → 导出成片」，暴露三处问题。

**① 视频生成失败 ×2：`seconds must be >= 4`**

- 优云智算 MiniMax-H3 要求单段时长 ≥ 4 秒。
- 失败发生在 14:20–14:21，当时镜头 `duration` 尚未设置。
- 后续把镜头时长设为 4/4/8/8/10/5/7 秒后，7 个镜头的视频**全部生成成功**。
- 属参数约束，非代码缺陷；如需支持更短镜头，应在前端提交前就拦截并提示。

**② 导出成片 400（14:38）→ 重试成功（14:40）**

- 首次导出时部分镜头还没有视频，时间线导出前置校验返回 400。
- 补齐视频后重试即 200，成片已生成：`纸尿裤-成片.mp4`。

**③ 下载端点 HEAD 返回 405**

- 浏览器 `<video>` / 下载器会先发 **HEAD** 探测 `Content-Length`、`Accept-Ranges`。
- `download` 端点原只注册了 `@router.get`，HEAD 请求报 `405 Method Not Allowed`。
- 修复：改为 `@public_router.api_route(..., methods=["GET", "HEAD"])`。

**④ 导出成片的 `thumbnail` 为空（隐藏问题）**

`timeline.py` 导出时写死 `thumbnail=""`：

```python
file_item = await create_and_refresh(db, FileItem(..., thumbnail="", storage_key=key))
```

后果：
- 成片无法用 CDN 直链访问，`build_download_response` 只能回退后端流式代理；
- 8.4 MB 视频每次播放都占用 EC2 出网带宽。

修复：改用 `storage.upload_file` 的返回值 `StoredFileInfo.url`
（`upload_file` 本就返回公开 URL，之前被丢弃了）：

```python
stored = await storage.upload_file(...)   # StoredFileInfo(key, url, etag)
... FileItem(..., thumbnail=stored.url, ...)
```

**历史数据回填**：扫描 `thumbnail` 为空的 `files` 记录并补写公开 URL：

```
发现 1 条 thumbnail 为空的记录
  [ok] 纸尿裤-成片.mp4 -> https://pub-6dcd8c3d...r2.dev/exports/073ab715-...mp4
回填 1 条，失败 0 条
```

**验证**：

| 检查 | 结果 |
| --- | --- |
| `HEAD /studio/files/<id>/download` | **302**（原 405） |
| `GET` 跟随重定向 | 302 → R2 → **200, 8,387,958 bytes, video/mp4** |
| `Range: bytes=0-1023` | **206, 1024 字节**（seek 正常） |

**全项目当前状态**：

| 项 | 数量 |
| --- | --- |
| 项目 / 章节 / 镜头 | 1 / 1 / 7 |
| 图片 | 12 |
| 视频（分镜） | 7 |
| 成片 | 1（`纸尿裤-成片.mp4`，8.4 MB） |
| 失败任务 | 3（均为上述已解决的历史失败） |

### 9.15 2026-10-20：修复批量提取漏掉末尾镜头（需单独点一次才出现候选）

**现象**：用户先做章节级「一键提取」，完成后又在某个分镜里点「刷新并提取」，
才发现该镜头此前**完全没有候选**，看起来像是「又冒出新的」。

**排查**（数据库时间线）：

| 时刻 | 事件 |
| --- | --- |
| 13:03:40 | 7 个镜头**同一批创建** |
| 13:04:22→13:04:39 | 提取任务产出 27 条候选，覆盖镜头 1–6 |
| 14:15:56 | 用户单独提取镜头 7，补出 7 条候选 |

- 候选表**没有重复**（同镜头+类型+名称唯一），说明写入是 replace 语义、不是追加。
- 问题在于**镜头 7 从未被那次批量提取处理**。

**根因**：`sync_from_extraction_draft_sync` 只遍历 **LLM 返回的**
`for shot_draft in draft.shots`，而代码里没有任何「返回结果是否覆盖输入镜头」的校验。
prompt 虽已写明「shots.index 必须覆盖并对应输入分镜中的 index，不要跳号」，
但 LLM 仍会偶发漏掉末尾镜头，且漏了也无日志、无告警。

**修复**（`script_processing_worker.generate_extraction_result`）：

1. LLM 返回后计算 `expected_indexes - got_indexes`；
2. 若有缺失，用只包含缺失镜头的 `script_division` **自动补提取一次**；
3. 用 `_merge_extraction_drafts` 合并：shots 按 index 去重，
   characters/scenes/props/costumes 按 name 去重
   （全局实体必须一起合并，否则补提取的 shots 引用的名字在主结果里找不到，候选会被跳过）；
4. 仍缺失则记 `ERROR` 日志（需人工重试）；补提取本身异常也不影响首轮结果。
5. 缓存写入移到校验/补提取之后，避免把不完整结果缓存下来。

**为什么不是「前端问题」**：候选数量、资产数量在两个时点对比都与「漏了一个镜头」一致，
单镜头提取只是把被漏掉的那次补上。

**遗留观察**：镜头 7 补提取产生的实体名与其他镜头不一致
（`护理病房`/`病床`/`护工工作服`/`病号服` vs `深夜卧室`/`手表`/`护工护理工作服`/`老人睡衣`），
这是 LLM 命名漂移，属于另一类问题（同一实体被提取成不同名称），
本次未处理，需要时可通过「合并实体」或人工改名校正。

### 9.16 2026-10-21：项目级开关「视频生成是否使用台词配音作为参考音频」

**需求**：配音不应硬编码为始终参与视频生成，需要在设置里提供「全部使用 / 不使用」的开关。

**实现**：

1. 迁移 `backend/sql/020-add-project-dialog-audio-reference.sql`：

```sql
ALTER TABLE `projects`
  ADD COLUMN `use_dialog_audio_as_reference` TINYINT(1) NOT NULL DEFAULT 1
  COMMENT '视频生成时是否自动带上镜头台词已生成的配音作为参考音频（1=使用 0=不使用）';
```

默认 `1`，即保持本次上线的既有行为（自动带上配音）。

2. 模型 / Schema：`Project.use_dialog_audio_as_reference`，
   `ProjectRead` / `ProjectUpdate` 同步加字段。

3. `services/film/generated_video.py`：`build_run_args` 在未显式指定
   `reference_audio_file_ids` 时，先读项目开关
   （`_project_use_dialog_audio_as_reference`），为真才自动带上该镜头台词配音（≤3）。
   找不到镜头/章节/项目时保守返回 True，避免因缺数据静默关闭功能。

4. 前端 `SettingsTab` 由占位页改为真实设置页：
   - 项目信息（只读）：名称、题材、画面表现形式、默认视频比例、项目 ID
   - 视频生成：开关「使用台词配音作为参考音频」，切换即 PATCH 保存并提示，
     失败自动回滚本地状态
   - 附前置条件说明（音频不能单独使用、2–15 秒、角色需配音色）

**验证**：

| 开关 | `build_run_args` 产出的 input keys |
| --- | --- |
| 关闭 | `[prompt, reference_file_ids, model, ratio, seconds]`（无音频） |
| 开启 | `[..., reference_audio_file_ids: ['45e42bf2-…']]` |

**注意**：该开关是项目级，不同项目可独立设置；已有项目升级后默认开启。

### 9.17 2026-10-21：实体合并入口（数据库层合并）

**需求**：提取阶段 LLM 命名漂移，同一资产会落库成多条（如「护工工作服」与「护工护理工作服」），
需要一个入口把两条记录合成一条。

**与既有 `/script-processing/merge-entities` 的区别**：

| 能力 | 时机 | 输入 | 输出 |
| --- | --- | --- | --- |
| `script-processing/merge-entities` | 落库前 | 多镜头提取结果 | 合并后的实体库（LLM 语义） |
| 本次新增 `studio/entities/{type}/merge` | 落库后 | 两条已存在实体 | 一条保留 + 迁移统计 |

**后端**：

- `POST /api/v1/studio/entities/{entity_type}/merge`，body `{source_id, target_id}`，
  返回 `EntityMergePairResult`（images_moved / images_dropped / links_moved /
  links_dropped / cross_refs_moved / candidates_repointed）。
- 服务 `services/studio/entity_merge.py`，合并范围：

| 目标 | 迁移内容 |
| --- | --- |
| 所有类型 | `*_images`（含 `(quality_level, view_angle)` 去重、主图唯一化）、`project_*_links`（同作用域去重）、`shot_extracted_candidates.linked_entity_id` |
| character | `shot_character_links`、`shot_dialog_lines.speaker/target_character_id`、`character_prop_links`（含 index 重排避让唯一约束） |
| scene | `shot_details.scene_id` |
| costume | `characters.costume_id` |
| actor | `characters.actor_id` |
| prop | `character_prop_links.prop_id`（按角色去重） |

- 错误语义：自合并 / 非法类型 → 400；实体不存在 → 404；整体在 `get_db` 事务内，失败回滚。

**前端**：

- 新增通用 `EntityMergeModal`（保留项 + 被合并项 双下拉、远程搜索、不可逆提示、结果统计）。
- 入口：资产页「场景 / 道具 / 服装 / 演员」工具栏「合并 X」；项目角色 Tab「合并角色」。

**验证（staging，事务回滚方式，未改动真实数据）**：

| 用例 | 统计结果 |
| --- | --- |
| scene 深夜卧室 → 木质桌面 | images_dropped 1（同档同视角）、links_moved 4、candidates_repointed 4；事后源归零、目标主图 ≤1 |
| costume 护工护理工作服 → 老人睡衣 | images_dropped 1、links_moved 1、links_dropped 2、cross_refs_moved 1、candidates 3 |
| character 老人 → 护工 | images_dropped 1、links_moved 1、links_dropped 3、cross_refs_moved 4（台词说话人/对象）、candidates 4；源已删除 |

HTTP 错误分支：自合并 400、不存在 404、非法类型 400。

### 9.18 2026-10-21：P4 章节检查流程（参考图 → 分镜 → 对话）

**需求**：进入工作室付费生成前，需要一个按顺序过一遍素材的自检位。

**新增页面**：`/projects/:projectId/chapters/:chapterId/review`

| 段 | 能力 | 写接口 |
| --- | --- | --- |
| ① 参考图 | 聚合本章镜头引用的角色/服装/场景/道具；缺图补图、有图重抽；列出待确认候选并跳分镜编辑页 | `POST /studio/image-tasks/assets/batch-image-tasks` |
| ② 分镜 | 逐镜头就地改 时长/景别/角度/运镜/场景 | `PATCH /studio/shot-details/{shot_id}` |
| ③ 对话 | 就地改台词与情绪、单句配音/重抽、镜头级补配音 | `PATCH /studio/shot-dialog-lines/{line_id}` + `POST /studio/audio-tasks/speech` |

顶部三段进度：有图数 / 字段完整数 / 已配音数 + 待确认候选数。

**入口**：章节列表卡片「检查」图标 + 操作菜单「检查流程（参考图 → 分镜 → 对话）」。

**顺带修复（真实缺陷）**：多处 `pageSize: 200` 超过后端 `le=100` 上限，会直接 422：

- `ChapterReviewPage` 镜头列表
- `ChaptersTab.generateChapterAudio`（P3 引入的「一键配音」在镜头 >100 时会失败）
- `ChapterPrepareWizard` 资产列表（P1 引入）

统一改为 100。

**顺带重构（去重）**：

- 新增 `shots/tts.ts`（`runSpeechTaskForLine` / `describeSpeechError`），
  `ChapterShotEditPage` 与 `ChaptersTab` 的 TTS 轮询改用该助手；
- 新增 `shots/shotOptions.ts` 统一景别/角度/运镜中文选项，
  `ChapterShotBasicInfoSection` 与检查页共用。

**验证**：

- 数据链路：章节 7 镜头 → prep-state 资产总览 4 项（含 R2 缩略图）、台词 1 条（已有配音）；
- `PATCH shot-details` 200；`PATCH shot-dialog-lines` 200；
- `pnpm typecheck` 通过，前端构建产出独立 `ChapterReviewPage` chunk（18.4 kB）。

### 9.19 2026-10-21：品牌更名为 DyeingTime + 新 logo

**品牌名**：

- 浏览器标题：`Jellyfish` → `DyeingTime`
- 侧边栏标题 / 登录页主标题：`DyeingTime`（i18n `layout.title`，中英同步）
- 欢迎语：`欢迎使用 DyeingTime` / `Welcome to DyeingTime`
- 登录页与侧边栏 logo 的 `alt` 同步为 `DyeingTime`

**Logo**（源图 `logo无字.png`，1254×1254 RGBA）：

| 产物 | 尺寸 | 用途 |
| --- | --- | --- |
| `front/public/logo.png` | 512×512 | 侧边栏（32px）、登录页（56px） |
| `front/public/favicon.png` | 64×64 | 浏览器标签页（高分屏） |
| `front/public/favicon-32.png` | 32×32 | 浏览器标签页（标准） |
| `front/public/apple-touch-icon.png` | 180×180 | iOS 添加到主屏 |
| `docs/img/logo.png` | 320×320 | README 顶部展示 |

`index.html` 增加 `<meta name="theme-color" content="#ff5a52">`（取自 logo 主色）。
旧 `logo.svg`（front/public、front、docs/img 三处）已删除，避免与新图标混淆。

**仓库**：`origin` 改为 `git@github.com:Timeregainedme/DyeingTime.git`。

**未改动（内部标识）**：`/srv/changeAT` 部署目录、`changeat-*` systemd 单元、
`jellyfish-backend` / `jellyfish-frontend` 包名、`jellyfish_*` 本地存储 key
（改 key 会让已登录用户被登出、偏好重置）。

**验证**：`pnpm typecheck` 通过；`/` 的 `<title>` 为 `DyeingTime`；
`/logo.png`、`/favicon.png`、`/favicon-32.png`、`/apple-touch-icon.png` 均 200。
