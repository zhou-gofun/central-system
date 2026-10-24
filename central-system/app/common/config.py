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

    # 支付模块
    # 支付渠道回调地址的对外前缀，用于拼接 /api/v1/pay/notify/{provider}/{merchant_id}
    PAY_NOTIFY_BASE_URL: str = ""
    # 支付管理端密钥（商户配置 CRUD），留空则相关接口返回 503
    PAY_ADMIN_KEY: str = ""
    # 支付通知业务平台的重试次数
    PAY_NOTIFY_RETRY: int = 3

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
