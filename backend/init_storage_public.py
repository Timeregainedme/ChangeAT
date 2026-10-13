"""初始化对象存储：确保 bucket 存在，并把素材设为公共读。

为什么需要：
- `init_storage.py` 只保证 bucket 存在，但自建 S3（RustFS/MinIO）默认 bucket 为私有，
  前端拿到的素材直链会返回 403，图片/视频无法在页面上展示；
- 本脚本在其基础上追加一条只允许 `s3:GetObject` 的公共读策略，幂等可重复执行。

用法（在 backend 容器内，工作目录 /app）：
    uv run python init_storage_public.py
"""

import asyncio
import json

from app.config import settings
from app.core.storage import _build_s3_client, init_storage


def _apply_public_read_policy() -> None:
    """给素材 bucket 写入公共读策略（仅 GetObject），幂等。"""
    bucket = settings.s3_bucket_name
    if not bucket:
        raise RuntimeError("S3 未配置：缺少 s3_bucket_name")

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadForAssets",
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }

    client = _build_s3_client()
    client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))


async def _main() -> None:
    """先确保 bucket 存在，再应用公共读策略。"""
    # init_storage 是同步的（boto3），放线程池避免阻塞事件循环
    await asyncio.to_thread(init_storage)
    await asyncio.to_thread(_apply_public_read_policy)
    print(f"[init_storage_public] bucket={settings.s3_bucket_name} 就绪，已应用公共读策略")


if __name__ == "__main__":
    asyncio.run(_main())
