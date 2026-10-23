from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""

    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system"

    # 应用配置
    APP_NAME: str = "Central System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DOMAIN: str = "localhost"

    # ULID生成
    ULID_ENABLED: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
