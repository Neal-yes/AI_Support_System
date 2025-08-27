from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Union, Optional


class Settings(BaseSettings):
    # Pydantic v2 settings config
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # 忽略未在 Settings 中声明的额外环境变量，避免 ValidationError
    )
    # API
    API_PORT: int = 8000

    # Postgres
    POSTGRES_USER: str = "ai_support"
    POSTGRES_PASSWORD: str = "ai_support_pw"
    POSTGRES_DB: str = "ai_support"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # Qdrant
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "default_collection"

    # Ollama
    OLLAMA_HOST: str = "ollama"
    OLLAMA_PORT: int = 11434
    OLLAMA_MODEL: str = "qwen2.5:7b"
    OLLAMA_KEEP_ALIVE: Union[str, int] = "5m"

    # Timeouts (seconds)
    GENERATE_TIMEOUT: float = 300.0
    EMBED_TIMEOUT: float = 120.0

    # Defaults for search/generation
    DEFAULT_TOP_K: int = 5
    DEFAULT_NUM_PREDICT: int = 256

    # CORS
    CORS_ORIGINS: str = "*"  # 逗号分隔，* 表示全部允许

    # Auth/JWT（可选）
    AUTH_JWT_SECRET: Optional[str] = None  # 若配置则启用 Bearer Token 校验
    AUTH_JWT_ALG: str = "HS256"
    AUTH_TENANT_CLAIM: str = "tenant"  # JWT 中的租户字段名
    AUTH_REQUIRE_TENANT: bool = False  # 是否要求请求头必须提供 tenant
    AUTH_ENFORCE_JWT_TENANT: bool = False  # 若提供 JWT，是否强制校验与请求头一致

    # Multi-tenant
    HEADER_TENANT_KEY: str = "X-Tenant-Id"  # 请求头中租户字段名

    # 旧版 pydantic v1 风格的 Config 已由上面的 model_config 取代


class ServiceStatus(BaseModel):
    healthy: bool
    detail: Optional[str] = None


settings = Settings()
