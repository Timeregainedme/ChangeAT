"""优云智算「模型 API」集成（https://cp.compshare.cn）。

协议要点（对齐 `/Users/mac/Desktop/03-公司业务/短剧/优云智算/compshareModelApi.ts`）：
- 鉴权：`Authorization: Bearer sk-ml-...`，写操作另带 `Idempotency-Key`；
- 视频：`POST /minimax/v2/video_generation` + `GET /minimax/v2/query/video_generation/{task_id}`；
- 语音：`POST /audio/v1/speech/jobs` + `GET /audio/v1/speech/jobs/{task_id}`，音色 `GET /audio/v1/voices`；
- 业务错误：HTTP 200 但 `RetCode` 非 0 同样按失败处理。
"""

from __future__ import annotations

DEFAULT_COMPSHARE_BASE_URL = "https://cp.compshare.cn"
