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

> 本次部署在 forwarding、redeployment、reading-only 这些动作中没有修改任何你 jellyfish 仓库源文件。部署与仓库完全独立：仓库的源代码 + EC2 上的 \`/srv/changeAT\` 是两份独立副本，必要时你可以 \`rm -rf /srv/changeAT\` 同步环境重拉。
