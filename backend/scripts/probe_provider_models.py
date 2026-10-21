"""探测某个供应商账号下「哪些模型真正可用」。

背景：
    供应商的 `/models` 只返回「这个网关支持哪些模型」，不代表**你的账号**能调通。
    OpenCode Zen 就是典型：付费模型返回 402（账户余额不足），
    免费模型返回 403（只允许在 OpenCode 客户端内使用）。
    只看 /models 会误以为一切正常，直到业务调用时才炸。

做法：
    对每个模型发一次极小请求（`max_tokens=5`），按 HTTP 状态码分类，
    并用供应商返回的错误 message 说明原因。

用法：
    cd backend
    uv run python scripts/probe_provider_models.py "OpenCode Go"
    uv run python scripts/probe_provider_models.py "DeepSeek" --max-models 5

退出码：
    0 = 至少一个模型可用；1 = 没有可用模型。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from sqlalchemy import select

# 允许直接 `python scripts/...` 运行时找到 app 包
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.core.crypto import decrypt_secret  # noqa: E402
from app.core.db import async_session_maker  # noqa: E402
from app.models.llm import Provider  # noqa: E402

# 并发不易过高：供应商对探测请求同样计费/限流。
_CONCURRENCY = 4
# 每个模型只生成极少量 token，避免探测本身产生明显费用。
_PROBE_MAX_TOKENS = 5

_STATUS_MEANING = {
    200: "可用",
    401: "密钥无效",
    402: "余额不足",
    403: "无权限/免费层限制",
    404: "模型不存在或不支持 chat",
    429: "限流",
    500: "供应商内部错误",
    503: "供应商不可用",
}


async def _probe_one(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, int, str]:
    """对单个模型发一次最小 chat 请求，返回 (模型, 状态码, 说明)。"""
    headers = {"Authorization": f"Bearer {api_key}", **(extra_headers or {})}
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": _PROBE_MAX_TOKENS,
            },
            timeout=45,
        )
    except httpx.HTTPError as exc:
        return model, -1, f"网络错误: {exc}"

    if resp.status_code == 200:
        return model, 200, ""

    detail = ""
    try:
        body = resp.json()
        err = body.get("error") or {}
        if isinstance(err, dict):
            detail = " ".join(
                str(err.get(k) or "").strip() for k in ("type", "message", "code")
            ).strip()
        else:
            detail = str(err)
    except ValueError:
        detail = resp.text[:120]
    return model, resp.status_code, detail[:140]


async def main() -> int:
    parser = argparse.ArgumentParser(description="探测供应商账号下可用的模型")
    parser.add_argument("provider", help="供应商名称（数据库 providers.name，例如 'OpenCode Go'）")
    parser.add_argument("--max-models", type=int, default=0, help="只测前 N 个模型（0=全部）")
    args = parser.parse_args()

    async with async_session_maker() as db:
        provider = (
            await db.execute(select(Provider).where(Provider.name == args.provider))
        ).scalar_one_or_none()
    if provider is None:
        print(f"找不到供应商：{args.provider}")
        return 1

    api_key = decrypt_secret(provider.api_key) or ""
    if not api_key:
        print(f"供应商 {provider.name} 没有配置 api_key")
        return 1

    base_url = provider.base_url
    print(f"供应商：{provider.name}\nBase URL：{base_url}\n")

    # 某些网关（OpenCode Zen /go 通道）要求额外的路由头，探测时必须一并带上，
    # 否则会把「缺头 400」误判成「模型不可用」。
    from app.services.llm.provider_registry import extra_headers_for_provider

    extra_headers = extra_headers_for_provider(provider.name, base_url)
    if extra_headers:
        print(f"附加请求头：{sorted(extra_headers)}\n")

    async with httpx.AsyncClient() as client:
        listing = await client.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        if listing.status_code != 200:
            print(f"拉取 /models 失败：HTTP {listing.status_code} {listing.text[:200]}")
            return 1
        payload = listing.json()
        items = payload.get("data") if isinstance(payload, dict) else payload
        models = [str(it.get("id")) for it in (items or []) if isinstance(it, dict)]
        if args.max_models:
            models = models[: args.max_models]
        print(f"共 {len(models)} 个模型，开始探测（每个 {_PROBE_MAX_TOKENS} token）…\n")

        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def run(model: str) -> tuple[str, int, str]:
            async with semaphore:
                return await _probe_one(
                    client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    extra_headers=extra_headers,
                )

        results = await asyncio.gather(*(run(m) for m in models))

    # 可用优先，其余按状态码分组
    results.sort(key=lambda r: (0 if r[1] == 200 else 1, r[1], r[0]))
    ok = [r for r in results if r[1] == 200]

    print(f"✅ 可用：{len(ok)} / {len(results)}")
    for model, _, _ in ok:
        print(f"   - {model}")

    others = [r for r in results if r[1] != 200]
    if others:
        print("\n❌ 不可用：")
        for status in sorted({r[1] for r in others}):
            meaning = _STATUS_MEANING.get(status, "未知")
            rows = [r for r in others if r[1] == status]
            print(f"\n   HTTP {status}（{meaning}）· {len(rows)} 个")
            for model, _, detail in rows:
                suffix = f"  → {detail}" if detail else ""
                print(f"     {model}{suffix}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
