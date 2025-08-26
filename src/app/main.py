from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.app.routers.health import router as health_router
from src.app.routers.metrics import router as metrics_router
from src.app.routers.chat import router as chat_router
from src.app.routers.embedding import router as embedding_router
from src.app.routers.collections import router as collections_router
from src.app.routers.admin import router as admin_router
from src.app.routers.tools import router as tools_router
from src.app.routers.alerts import router as alerts_router
from src.app.routers.ask import router as ask_router
from src.app.routers.db import router as db_router
from src.app.core.middleware import RequestContextMiddleware
from src.app.core.errors import register_exception_handlers
from src.app.config import settings
from src.app.core.logging_config import setup_logging
from src.app.core.tool_executor import REQ_TOTAL, ERR_TOTAL, RL_TOTAL, CB_OPEN_TOTAL, CACHE_HIT_TOTAL, RETRY_TOTAL, LATENCY_SEC

setup_logging()
app = FastAPI(title="AI Support System API")

# 预热 Prometheus 指标（确保关键标签组合的时间序列可见）
@app.on_event("startup")
async def _warmup_metrics() -> None:
    labels = {"tool_type": "http_get", "tool_name": "simple", "tenant": "demo"}
    # 使用极小微增量，确保导出器暴露时间序列（部分实现不会导出 0 值）
    epsilon = 1e-12
    REQ_TOTAL.labels(**labels).inc(epsilon)
    ERR_TOTAL.labels(**{**labels, "reason": "exec_failure"}).inc(epsilon)
    RL_TOTAL.labels(**labels).inc(epsilon)
    CB_OPEN_TOTAL.labels(**labels).inc(epsilon)
    CACHE_HIT_TOTAL.labels(**labels).inc(epsilon)
    RETRY_TOTAL.labels(**labels).inc(epsilon)
    LATENCY_SEC.labels(**labels).observe(epsilon)

# Middlewares
app.add_middleware(RequestContextMiddleware)
origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
if not origins:
    origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
register_exception_handlers(app)

# Routers
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(chat_router)
app.include_router(embedding_router)
app.include_router(collections_router)
app.include_router(admin_router)
app.include_router(tools_router)
app.include_router(alerts_router)
app.include_router(ask_router)
app.include_router(db_router)
