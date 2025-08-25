from fastapi import APIRouter, Request
from typing import Any, Dict
import logging

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"]) 
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def alertmanager_webhook(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    # 简单记录接收到的告警事件，生产可扩展：签名校验、异步处理、路由分发等
    logger.info("[Alertmanager] Received webhook: %s", payload)
    return {"status": "ok"}
