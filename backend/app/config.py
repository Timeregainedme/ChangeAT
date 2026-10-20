"""应用配置，从环境变量加载。"""

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "DyeingTime API"
    debug: bool = False

    # API
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "sqlite+aiosqlite:///./dyeingtime.db"

    # Redis / Celery Broker
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    celery_broker_url: str | None = None

    # CORS：环境变量中建议使用逗号分隔（更贴近 docker-compose 用法）
    # 也兼容 JSON 数组：'["http://a","http://b"]'
    cors_origins: str = "http://localhost:7788,http://127.0.0.1:7788"

    @property
    def cors_origins_list(self) -> list[str]:
        s = (self.cors_origins or "").strip()
        if not s:
            return []
        if s.startswith("["):
            loaded = json.loads(s)
            if isinstance(loaded, list):
                return [str(x).strip() for x in loaded if str(x).strip()]
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    # S3 / 对象存储（用于素材文件）
    s3_endpoint_url: str | None = None
    s3_region_name: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_name: str | None = None
    # 可选：统一前缀，方便按环境/项目隔离，如 "dyeingtime/dev"
    s3_base_path: str = ""
    # 可选：对外访问基址（CDN 或自定义域名），为空则使用 S3 自带 URL 或预签名 URL
    s3_public_base_url: str | None = None
    # 可选：S3 寻址风格，"virtual"（默认，AWS 常用）或 "path"。
    # 自建 S3 兼容服务（RustFS / MinIO 等）通常需要 "path"，
    # 因为 Docker 内置 DNS 无法解析 `<bucket>.<service>` 这类虚拟主机名。
    s3_addressing_style: str = "virtual"

    # --- 认证（JWT）---
    # 密钥必须通过环境变量注入；空值会让 app.core.security 拒绝签发/校验 token，
    # 这是刻意设计：避免用内置默认值签发可被伪造的令牌。
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60 * 12

    # --- Google 登录 ---
    # client_id 会下发给前端（通过 nginx 生成的 env.js），不属于机密；
    # client_secret 只存服务端，保留给后续「服务端 code 交换」流程使用，
    # 当前采用的是 GIS ID Token 校验流程（不需要 secret）。
    google_client_id: str = ""
    google_client_secret: str = ""
    # 允许登录的 Google 邮箱，逗号分隔；支持 `@domain.com` 形式按域放行。
    # 留空表示「任何已验证邮箱都可登录」——公网部署建议务必填写。
    google_allowed_emails: str = ""
    # Google ID Token 校验端点（测试可替换）
    google_tokeninfo_url: str = "https://oauth2.googleapis.com/tokeninfo"

    @property
    def google_allowed_email_set(self) -> set[str]:
        return {x.strip().lower() for x in (self.google_allowed_emails or "").split(",") if x.strip()}

    def model_post_init(self, __context: object) -> None:
        if not self.celery_broker_url or not str(self.celery_broker_url).strip():
            password_part = f":{self.redis_password}@" if self.redis_password else ""
            self.celery_broker_url = f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
