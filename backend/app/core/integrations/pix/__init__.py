"""PIX 中转平台集成（https://pix.token6688.com）。

协议要点（对齐 /Applications/data/providers/pix.ts）：
- 鉴权：`Authorization: Bearer <apiKey>`；
- 图片：`POST /api/v1/model-runtime/invoke`（body: model_id / modality / params）；
- 视频：`POST /v1/media/generate`（body: model / prompt / params）；
- 轮询：统一 `GET /v1/tasks/{taskId}`，`is_final === true` 时读 `output_url`。
"""

from __future__ import annotations

DEFAULT_PIX_BASE_URL = "https://pix.token6688.com"
