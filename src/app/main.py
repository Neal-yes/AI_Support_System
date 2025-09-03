import asyncio
import logging
import time
from contextlib import asynccontextmanager

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
from src.app.clients import ollama
from src.app.clients import qdrant as qcli
from src.app.core.logging_config import setup_logging
from src.app.core.tool_executor import REQ_TOTAL, ERR_TOTAL, RL_TOTAL, CB_OPEN_TOTAL, CACHE_HIT_TOTAL, RETRY_TOTAL, LATENCY_SEC

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 预热 Prometheus 指标（确保关键标签组合的时间序列可见）
    labels = {"tool_type": "http_get", "tool_name": "simple", "tenant": "demo"}
    epsilon = 1e-12
    REQ_TOTAL.labels(**labels).inc(epsilon)
    ERR_TOTAL.labels(**{**labels, "reason": "exec_failure"}).inc(epsilon)
    RL_TOTAL.labels(**labels).inc(epsilon)
    CB_OPEN_TOTAL.labels(**labels).inc(epsilon)
    CACHE_HIT_TOTAL.labels(**labels).inc(epsilon)
    RETRY_TOTAL.labels(**labels).inc(epsilon)
    LATENCY_SEC.labels(**labels).observe(epsilon)

    # 轻量模型预热（后台异步），降低首请求冷启动时延且不阻塞启动
    logger = logging.getLogger("startup")

    async def _task():
        await asyncio.sleep(0.5)
        t_gen = time.perf_counter()
        try:
            await ollama.generate("warmup", model=settings.OLLAMA_MODEL, timeout=60, num_predict=8)
            dt = (time.perf_counter() - t_gen) * 1000.0
            logger.info("warmup_generate_ok latency_ms=%.2f model=%s", dt, settings.OLLAMA_MODEL)
        except Exception as e:
            dt = (time.perf_counter() - t_gen) * 1000.0
            logger.warning("warmup_generate_failed latency_ms=%.2f model=%s error=%s: %s", dt, settings.OLLAMA_MODEL, type(e).__name__, e)

        t_emb = time.perf_counter()
        try:
            emb_model = getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL
            await ollama.embeddings(["warmup"], model=emb_model, timeout=60)
            dt2 = (time.perf_counter() - t_emb) * 1000.0
            logger.info("warmup_embeddings_ok latency_ms=%.2f model=%s", dt2, emb_model)
        except Exception as e:
            dt2 = (time.perf_counter() - t_emb) * 1000.0
            emb_model = getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL
            logger.warning("warmup_embeddings_failed latency_ms=%.2f model=%s error=%s: %s", dt2, emb_model, type(e).__name__, e)

        # 预热 RAG 检索链路（embedding + Qdrant search），非强制
        try:
            coll = settings.QDRANT_COLLECTION
            if qcli.collection_exists(coll):
                t_rag = time.perf_counter()
                vecs = await ollama.embeddings(["warmup"], model=(getattr(settings, "OLLAMA_EMBED_MODEL", None) or settings.OLLAMA_MODEL), timeout=30)
                dim = len(vecs[0]) if vecs and vecs[0] else 0
                try:
                    _ = qcli.search_vectors(coll, query=vecs[0], top_k=1, filters=None)
                    dt_rag = (time.perf_counter() - t_rag) * 1000.0
                    logger.info("warmup_rag_ok latency_ms=%.2f dim=%s collection=%s", dt_rag, dim, coll)
                except Exception as e:
                    dt_rag = (time.perf_counter() - t_rag) * 1000.0
                    logger.warning("warmup_rag_search_failed latency_ms=%.2f dim=%s collection=%s error=%s: %s", dt_rag, dim, coll, type(e).__name__, e)
            else:
                logger.info("warmup_rag_skipped: collection '%s' not found", settings.QDRANT_COLLECTION)
        except Exception as e:
            logger.warning("warmup_rag_failed error=%s: %s", type(e).__name__, e)

    asyncio.create_task(_task())

    yield

app = FastAPI(title="AI Support System API", lifespan=lifespan)

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
# Also expose certain routers under '/api' for proxy compatibility
app.include_router(health_router, prefix="/api")
app.include_router(embedding_router, prefix="/api")
app.include_router(collections_router, prefix="/api")
