---
title: "安装说明"
weight: 1
description: "安装 DyeingTime 所需的基础环境与依赖。"
---

## 环境要求

- Hugo extended `>= 0.146.0`（官网与文档站）
- Go `>= 1.22`（用于 Hugo Modules 拉取 Hextra）
- Node.js 与 pnpm
- Python 3.11+
- `uv`
- Docker 与 Docker Compose（可选）

## 获取代码

```bash
git clone https://github.com/Forget-C/DyeingTime.git
cd DyeingTime
```

## 目录建议

如果你只是使用应用，优先关注：

- `front/`
- `backend/`
- `deploy/`

如果你还要维护官网与文档站，再关注：

- `site/`

## 安装前端依赖

```bash
cd front
pnpm install
```

## 安装后端依赖

```bash
cd backend
uv sync
```

## 安装站点主题模块

```bash
cd site
hugo mod tidy
```

## 建议的安装顺序

1. 先安装后端依赖，确保 API 能跑起来。
2. 再安装前端依赖，用于本地联调。
3. 如果需要维护官网和文档，再初始化 `site/` 的 Hugo Modules。
