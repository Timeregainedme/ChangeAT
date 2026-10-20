---
title: "密钥加密与操作审计"
description: "记录供应商密钥的加密存储方式、密钥来源与轮换代价，以及写操作审计的范围与边界。"
weight: 19
---

> 本文属于“当前架构”文档，描述**已经生效**的密钥保护与审计实现。

## 为什么

两件事都指向同一个问题：内部系统的风险往往不来自外部攻击，而来自
「常规运维动作」与「事后无法追溯」。

- 供应商 `api_key` 直接产生费用。明文落库意味着数据库备份、慢查询日志、
  `SELECT *` 之类的日常操作都会把它带出去。
- 出了问题要能回答「谁删的、谁改的、什么时候」。没有审计时只能靠日志翻找，
  而访问日志在容器重启后就没了。

## 密钥加密

### 实现

`app/core/crypto.py`（算法与密钥）+ `app/models/types_encrypted.py`（SQLAlchemy 接入）。

供应商密钥列由 `EncryptedString` 承接，**写入即加密、读取即解密**：

```python
api_key: Mapped[str] = mapped_column(EncryptedString(), nullable=False, default="")
```

业务代码继续把 `provider.api_key` 当普通字符串用，不需要任何改动。

为什么用 `TypeDecorator` 而不是在 service 里手动加解密：
`provider.api_key` 的读取点散布在 6 个供应商适配器、任务运行器与准备度检查里。
逐个改必然漏，而漏一处的后果是**把密文当 Authorization 头发给供应商**，
只会在线上暴露。

### 算法与密钥

选用 Fernet（`cryptography`，PyJWT 已依赖）：

- 自带 HMAC 完整性校验，密文被截断或篡改会直接抛错，而不是解出一段乱码再发给供应商；
- 支持 `MultiFernet` 轮换，后续换密钥不需要停机重写全表。

密钥来源优先级：

| 来源 | 适用 | 说明 |
|---|---|---|
| `SECRETS_KEY` | 生产**必须** | URL-safe base64 的 32 字节 |
| 由 `JWT_SECRET` 派生 | 本地开发 / 测试 | 会自动打印告警 |
| 都没有 | — | 直接抛错，拒绝启动 |

生成密钥：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**派生回退的代价必须知道**：轮换 `JWT_SECRET` 会导致所有已加密的 API Key 无法解密。
生产环境应配置独立的 `SECRETS_KEY`，两者互不影响。

### 密文格式与兼容

密文带 `enc:v1:` 前缀。三个作用：

1. 避免重复加密（迁移脚本可重复执行）；
2. 快速筛出未加密的历史行；
3. 读取时区分「密文」与「历史明文」。

**兼容策略是刻意设计的**：非密文输入在解密时原样返回。
上线顺序是「先发代码、再跑迁移脚本」，窗口期内旧数据仍是明文；
若读取直接解密失败，供应商配置会在这段时间内全部不可用。

解密失败（例如密钥被换过）时返回空串并记 `error` 日志，
让上层按「未配置密钥」处理，而不是让接口 500。

空串**不加密**：空 `api_key` 在业务上表示「未配置」，
加密成密文会让 `if not provider.api_key` 这类判断全部失效。

### 存量迁移

```bash
cd backend && uv run python scripts/encrypt_provider_keys.py --dry-run   # 预览
cd backend && uv run python scripts/encrypt_provider_keys.py             # 写入
```

脚本幂等、只改不删、日志只输出供应商 ID 与字段名（不打印明文）。

## 操作审计

### 记录范围

只记录 `/api/v1` 下的**写操作**（POST / PUT / PATCH / DELETE）。

不记读操作：读操作占请求量九成以上，价值低而存储成本高；
需要追责的是「谁改了什么、删了什么」。

### 三个关键边界

**不记录请求体。** 请求体里可能含剧本全文、提示词，以及供应商 `api_key`
（`providers` 的创建/更新就带着它）—— 落库等于把敏感信息复制一份。
需要还原变更内容时，靠 `resource_type` + `resource_id` 回查业务表。

**失败也记录。** 审计的价值恰在于知道「谁尝试删了别人的项目但被拒绝」。
只记成功等于放走最有信息量的样本。未认证的写尝试同样留痕（`user_id` 为空）。

**审计失败不影响业务。** 写库异常被吞掉并记 `warning`，
否则一次磁盘抖动会让全站写操作返回 500。

### 为什么用独立 session

业务事务可能因异常回滚，而审计恰恰要记录被回滚的那次尝试。
复用请求 session 会导致「失败的操作没有记录」，与审计目的相反。

### 为什么身份可以容错

中间件在 FastAPI 依赖注入之前运行，拿不到 `get_current_user` 的结果。
这里直接解码 JWT 的 `sub`（不查库、不校验用户是否停用）：

- 用户是否有效由路由层判定，审计只负责「这条请求声称是谁发起的」；
- 解析失败记 `None`，不阻断请求。

### 字段与索引

| 字段 | 说明 |
|---|---|
| `workspace_id` / `user_id` | 可空：未进入租户上下文或未认证即失败 |
| `action` | `create` / `update` / `delete` / `other`（由 HTTP 方法映射） |
| `method` / `path` | 不含 query string |
| `resource_type` / `resource_id` | 由路径启发式推断 |
| `status_code` / `duration_ms` | 记录失败与慢请求 |
| `ip` / `user_agent` / `request_id` / `detail` | 辅助定位 |

索引按 `(workspace_id, created_at)` 与 `(user_id, created_at)` 建，
覆盖「某工作区最近发生了什么」「某人最近做了什么」两类高频查询。

`resource_type` / `resource_id` 的推断是**启发式**的：
末段匹配 UUID 或纯数字时视为 ID，否则视为资源集合。
真实业务 ID 都是 UUID 或自增数字，因此实际准确；
非标准 ID（如手工构造的字符串）会退化为「类型=末段、ID 为空」。

审计表只追加，不提供 ORM 更新路径。

## 验证方式

```bash
# 落库是密文（绕过 ORM，否则读出来总是明文）
mysql -e "SELECT LEFT(api_key, 14), LENGTH(api_key) FROM providers"

# 应用内能正常解密
cd backend && uv run python -c "
import asyncio
from sqlalchemy import select
from app.core.db import async_session_maker
from app.models.llm import Provider
async def main():
    async with async_session_maker() as s:
        for p in (await s.execute(select(Provider))).scalars():
            print(p.id[:8], len(p.api_key or ''))
asyncio.run(main())"

# 审计：写操作留痕，读操作不留
mysql -e "SELECT action, method, resource_type, status_code, user_id FROM audit_logs ORDER BY id DESC LIMIT 5"
```
