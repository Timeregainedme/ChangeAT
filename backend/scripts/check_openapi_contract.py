"""校验后端 OpenAPI 契约与前端已冻结的 `front/openapi.json` 是否一致。

为什么需要它：
- 后端重写的核心约束是「前端无感切换」——`/api/v1` 的 URL、响应信封、
  字段名都不允许悄悄变。而这恰恰是最容易失守的地方：改一个 Pydantic 字段、
  调整一个参数必填性，前端 generated client 就会在运行时才报错。
- 现状是 `front/package.json` 的 `openapi:update` 需要先起服务再 curl，CI 里
  没人跑，于是契约只能靠人工记得更新。本脚本从 `app.main:app` 直接生成
  规格，不需要数据库、不需要起服务，可以直接挂在 CI 上做门禁。

用法：
    cd backend && uv run python scripts/check_openapi_contract.py           # 校验
    cd backend && uv run python scripts/check_openapi_contract.py --update  # 写回 front/openapi.json

退出码：
    0 = 一致（或已成功写回）
    1 = 存在差异 / 生成失败，可直接阻断 CI
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
# 前端 generated client 的唯一输入源，也作为契约的冻结基线。
CONTRACT_PATH = REPO_ROOT / "front" / "openapi.json"

sys.path.insert(0, str(BACKEND_DIR))


def build_spec() -> dict[str, Any]:
    """从 FastAPI 应用对象直接生成 OpenAPI 规格。

    不使用 HTTP 拉取的原因：CI 里没有可用的服务进程，且拉取会引入
    「端口被占用/服务没起来」这类与契约无关的失败模式。
    """
    from app.main import app

    return app.openapi()


def _normalize(spec: dict[str, Any]) -> str:
    """归一化为可稳定比较的文本（键排序 + 固定分隔符）。"""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _operation_map(spec: dict[str, Any]) -> dict[str, set[str]]:
    """提取 `路径 -> 方法集合`，用于生成人类可读的差异摘要。"""
    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    result: dict[str, set[str]] = {}
    for path, item in (spec.get("paths") or {}).items():
        result[path] = {m for m in item if m.lower() in methods}
    return result


def _describe_drift(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """生成差异摘要：优先给出增删路径/方法，便于直接定位破坏点。"""
    lines: list[str] = []
    exp_ops = _operation_map(expected)
    act_ops = _operation_map(actual)

    removed = sorted(set(exp_ops) - set(act_ops))
    added = sorted(set(act_ops) - set(exp_ops))
    for path in removed:
        lines.append(f"  - 路径被删除：{path}")
    for path in added:
        lines.append(f"  + 新增路径：{path}")

    for path in sorted(set(exp_ops) & set(act_ops)):
        lost = sorted(exp_ops[path] - act_ops[path])
        gained = sorted(act_ops[path] - exp_ops[path])
        for method in lost:
            lines.append(f"  - 方法被删除：{method.upper()} {path}")
        for method in gained:
            lines.append(f"  + 新增方法：{method.upper()} {path}")

    exp_schemas = set((expected.get("components") or {}).get("schemas") or {})
    act_schemas = set((actual.get("components") or {}).get("schemas") or {})
    for name in sorted(exp_schemas - act_schemas):
        lines.append(f"  - schema 被删除：{name}")
    for name in sorted(act_schemas - exp_schemas):
        lines.append(f"  + 新增 schema：{name}")

    return lines


def main(argv: list[str]) -> int:
    """校验或写回契约基线，返回进程退出码。"""
    update_mode = "--update" in argv

    try:
        spec = build_spec()
    except Exception as exc:  # noqa: BLE001 - 生成失败必须以非零码暴露，而不是静默跳过
        print(f"[FAIL] 无法生成 OpenAPI 规格：{exc!r}", file=sys.stderr)
        return 1

    if not CONTRACT_PATH.exists():
        print(f"[FAIL] 契约基线不存在：{CONTRACT_PATH}", file=sys.stderr)
        return 1

    baseline_text = CONTRACT_PATH.read_text(encoding="utf-8")
    try:
        baseline = json.loads(baseline_text)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] 契约基线不是合法 JSON：{exc}", file=sys.stderr)
        return 1

    # 写回时保留 Pydantic 声明顺序（不 sort_keys）：字段顺序会影响
    # openapi-typescript-codegen 生成的 TS 类型属性顺序，排序会产生
    # 上百个纯粹由顺序变化构成的无意义 diff，掩盖真正的契约变更。
    actual_text = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"

    if _normalize(baseline) == _normalize(spec):
        print(f"[OK] 契约一致：{CONTRACT_PATH.relative_to(REPO_ROOT)}")
        return 0

    drift = _describe_drift(baseline, spec)

    if update_mode:
        CONTRACT_PATH.write_text(actual_text, encoding="utf-8")
        print(f"[UPDATED] 已写回契约基线：{CONTRACT_PATH.relative_to(REPO_ROOT)}")
        if drift:
            print("本次契约变更：")
            print("\n".join(drift))
        return 0

    print("[FAIL] 后端契约与前端基线不一致。", file=sys.stderr)
    if drift:
        print("\n结构性差异：", file=sys.stderr)
        print("\n".join(drift), file=sys.stderr)
    else:
        print(
            "\n未发现增删路径/方法/schema，差异应在字段级别"
            "（字段名、类型、必填性、枚举值等），请用 diff 查看。",
            file=sys.stderr,
        )
    print(
        "\n确认这些变更是有意的之后，执行：\n"
        "  cd backend && uv run python scripts/check_openapi_contract.py --update\n"
        "  cd front && pnpm run openapi:gen\n"
        "并把两处产物一起提交。",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
