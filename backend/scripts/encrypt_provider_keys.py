"""把 `providers` 表里的明文密钥就地加密。

为什么需要它：
`app/models/llm.py` 用 `EncryptedString` 让「写入即加密」，但这条规则只对**新写入**生效。
存量行的 `api_key` 是明文，读取时靠兼容分支原样返回，因此不会报错、也不会被自动改写
—— 明文会一直留在库里，数据库备份里也就一直有明文。

用法：
    cd backend && uv run python scripts/encrypt_provider_keys.py --dry-run   # 先看会改哪些
    cd backend && uv run python scripts/encrypt_provider_keys.py             # 实际写入

安全性质：
- **幂等**：已带 `enc:v1:` 前缀的行直接跳过，可重复执行；
- **只读不删**：空值（表示「未配置」）保持空串，不做占位加密；
- **不打印明文**：日志里只出现供应商 id 与字段名，避免密钥落到终端历史/CI 日志；
- **预览模式**：`--dry-run` 只统计，不写库。

退出码：0 = 成功（含「无需处理」）；1 = 有行处理失败，需人工介入。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

from app.core.crypto import encrypt_secret, is_encrypted  # noqa: E402
from app.core.db import async_session_maker, close_db  # noqa: E402

# 需要加密的列。新增敏感列时在这里登记即可。
SENSITIVE_COLUMNS = ("api_key", "api_secret")


async def _run(*, dry_run: bool) -> int:
    """扫描并加密明文密钥，返回进程退出码。"""
    scanned = 0
    updated_rows = 0
    updated_fields = 0
    failed: list[str] = []

    async with async_session_maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, " + ", ".join(f"`{c}`" for c in SENSITIVE_COLUMNS) + " FROM providers"
                )
            )
        ).all()

        for row in rows:
            scanned += 1
            provider_id = row[0]
            changes: dict[str, str] = {}
            for offset, column in enumerate(SENSITIVE_COLUMNS, start=1):
                value = row[offset]
                if not value:
                    # 空串表示未配置，加密成密文会让 `if not api_key` 判断失效。
                    continue
                if is_encrypted(value):
                    continue
                changes[column] = encrypt_secret(value)

            if not changes:
                continue

            if dry_run:
                print(f"[dry-run] 将加密 provider={provider_id} 字段={','.join(changes)}")
                updated_rows += 1
                updated_fields += len(changes)
                continue

            try:
                await session.execute(
                    text(
                        "UPDATE providers SET "
                        + ", ".join(f"`{c}` = :{c}" for c in changes)
                        + " WHERE id = :pid"
                    ),
                    {**changes, "pid": provider_id},
                )
                await session.commit()
                print(f"[updated] provider={provider_id} 字段={','.join(changes)}")
                updated_rows += 1
                updated_fields += len(changes)
            except Exception as exc:  # noqa: BLE001 - 单行失败不应中断整批
                await session.rollback()
                failed.append(provider_id)
                print(f"[failed] provider={provider_id}: {exc!r}", file=sys.stderr)

    print(
        f"\n扫描 {scanned} 行，"
        f"{'预计' if dry_run else '已'}更新 {updated_rows} 行 / {updated_fields} 个字段"
    )
    if failed:
        print(f"失败 {len(failed)} 行：{', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="加密 providers 表中的明文密钥")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计将要处理的行，不写库",
    )
    args = parser.parse_args(argv)
    try:
        return await _run(dry_run=args.dry_run)
    finally:
        await close_db()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
