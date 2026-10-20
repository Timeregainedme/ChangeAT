# DyeingTime Site

DyeingTime 官网与文档站基于 Hugo + Hextra 构建。

## 本地开发要求

- Hugo extended `>= 0.146.0`
- Go `>= 1.22`

## 安装主题模块

```bash
cd site
hugo mod tidy
```

## 本地预览

```bash
cd site
hugo server --buildDrafts --disableFastRender
```

本地开发默认访问：

- `http://localhost:1313/`

## 构建

```bash
cd site
hugo --minify
```

GitHub Pages 发布时会在 CI 中显式传入生产环境的 `baseURL`。

当前仓库不保存 Hextra 主题源码，开发和 CI 都通过 Hugo Modules 即时拉取主题。

## 模块依赖约定

- 本地更新或新增主题模块时，使用 `hugo mod tidy`
- GitHub CI 中只执行模块下载与校验，不在发布时重写依赖锁文件
- `go.mod` 与 `go.sum` 需要随模块变更一并提交

## 目录说明

- `content/`：官网与文档内容
- `layouts/`：首页等自定义模板
- `data/`：首页文案块等结构化数据
- `static/`：logo、截图等静态资源

## SEO 与分享图

- 默认分享图：`static/images/og-default.svg`
- 站点级元信息：`hugo.yaml`
- 自定义 head 补充：`layouts/_partials/custom/head-end.html`
