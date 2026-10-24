from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import traceback

from app.common.config import settings
from app.api.wechat.scan import router as scan_router
from app.api.wechat.callback import router as wechat_router
from app.api.payment.order import router as pay_order_router
from app.api.payment.notify import router as pay_notify_router
from app.api.payment.merchant import router as pay_merchant_router

# 导入所有模型（确保 SQLAlchemy 可以发现它们）
import app.model  # noqa

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    yield
    # 关闭时执行
    print(f"👋 {settings.APP_NAME} 正在关闭...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="中心系统 - 统一服务平台",
    lifespan=lifespan
)


# 全局异常处理中间件
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常"""
    error_detail = {
        "error": exc.__class__.__name__,
        "message": str(exc),
        "path": request.url.path,
        "method": request.method
    }

    # 记录详细的异常信息
    logger.error(
        f"未处理的异常: {exc.__class__.__name__}: {str(exc)}\n"
        f"请求路径: {request.method} {request.url.path}\n"
        f"堆栈信息:\n{traceback.format_exc()}"
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "error": error_detail if settings.DEBUG else None
        }
    )


# 注册路由
app.include_router(scan_router)
app.include_router(wechat_router)
app.include_router(pay_order_router)
app.include_router(pay_notify_router)
app.include_router(pay_merchant_router)


@app.get("/")
async def root():
    """健康检查"""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
