"""集成测试包。

这些测试会访问真实外部服务（真实 LLM 供应商），因此默认被
`backend/pyproject.toml` 的 `addopts = "-m 'not integration'"` 排除。
运行方式：`cd backend && uv run pytest tests -m integration -q`。
"""
