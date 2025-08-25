from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from src.app.core.tool_executor import executor

router = APIRouter(prefix="/api/v1/tools", tags=["tools"]) 

# 结构化日志（指标在 core.tool_executor 内统一注册）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ToolInvokeRequest(BaseModel):
    tenant_id: Optional[str] = Field(default=None, description="租户标识，用于限流/配额/审计")
    tool_type: str = Field(..., description="工具类型，如 http/db/kv 等")
    tool_name: str = Field(..., description="工具名称，如 http_get/http_post/db_query 等")
    params: Dict[str, Any] = Field(default_factory=dict, description="工具入参（后续按模板治理）")
    options: Dict[str, Any] = Field(default_factory=dict, description="执行选项：超时/重试/缓存键/预算等")


class ToolInvokeResponse(BaseModel):
    request_id: str = Field(...)
    tool_type: str
    tool_name: str
    result: Dict[str, Any]

 


@router.post("/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(payload: ToolInvokeRequest) -> ToolInvokeResponse:
    # 生成 request_id（可替换为全局中间件注入的 trace_id/request_id）
    import uuid

    request_id = str(uuid.uuid4())
    # 把所有执行逻辑下沉到 core 执行器
    result = await executor.execute(
        tenant_id=(payload.tenant_id or "_anon_"),
        tool_type=payload.tool_type,
        tool_name=payload.tool_name,
        params=payload.params,
        options=payload.options,
    )
    return ToolInvokeResponse(
        request_id=request_id,
        tool_type=payload.tool_type,
        tool_name=payload.tool_name,
        result=result,
    )
