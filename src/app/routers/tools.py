from __future__ import annotations

from typing import Any, Dict, Optional
import logging
import json
import os
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field
from src.app.core.tool_executor import executor

router = APIRouter(prefix="/api/v1/tools", tags=["tools"]) 

# 结构化日志（指标在 core.tool_executor 内统一注册）
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---- Policy loading & merge (best-effort, optional file) ----
_POLICY_CACHE: Dict[str, Any] = {"loaded_at": 0.0, "data": {}}
_POLICY_TTL_SEC = 15
_POLICY_PATHS = [
    os.path.join("configs", "tools_policies.json"),
]


def _load_policies(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and (now - _POLICY_CACHE.get("loaded_at", 0.0) < _POLICY_TTL_SEC):
        return _POLICY_CACHE.get("data", {})
    data: Dict[str, Any] = {}
    for p in _POLICY_PATHS:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                    if isinstance(obj, dict):
                        data = obj
                        break
        except Exception as e:
            logger.warning("policy_load_failed", extra={"path": p, "error": str(e)})
    _POLICY_CACHE["loaded_at"] = now
    _POLICY_CACHE["data"] = data
    return data


def _merge_options(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(base or {})
    if isinstance(override, dict):
        out.update(override)
    return out


def _policy_layers(tenant_id: str, tool_type: str, tool_name: str, req_options: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return a dict of per-layer options plus merged, without side effects."""
    pol = _load_policies()
    out: Dict[str, Dict[str, Any]] = {
        "global": {},
        "tenant": {},
        "type": {},
        "name": {},
        "request": dict(req_options or {}),
        "merged": {},
    }
    # global
    out["global"] = dict(((pol.get("default") or {}).get("options") or {}))
    # tenant
    tnode = (pol.get("tenants") or {}).get(tenant_id or "", {})
    t_opts: Dict[str, Any] = {}
    if isinstance(tnode, dict):
        t_opts = dict(((tnode.get("default") or tnode).get("options") or {}))
    out["tenant"] = t_opts
    tools_node = (tnode.get("tools") if isinstance(tnode, dict) else None) or {}
    # type
    type_node = tools_node.get(tool_type, {}) if isinstance(tools_node, dict) else {}
    out["type"] = dict(((type_node.get("options") if isinstance(type_node, dict) else {}) or {}))
    # name
    names_node = (type_node.get("names") if isinstance(type_node, dict) else {}) or {}
    name_node = names_node.get(tool_name, {}) if isinstance(names_node, dict) else {}
    out["name"] = dict(((name_node.get("options") if isinstance(name_node, dict) else {}) or {}))

    # merged
    merged: Dict[str, Any] = {}
    merged = _merge_options(merged, out["global"])
    merged = _merge_options(merged, out["tenant"])
    merged = _merge_options(merged, out["type"])
    merged = _merge_options(merged, out["name"])
    merged = _merge_options(merged, out["request"])
    out["merged"] = merged
    return out


def _policy_merge_options(tenant_id: str, tool_type: str, tool_name: str, req_options: Dict[str, Any]) -> Dict[str, Any]:
    layers = _policy_layers(tenant_id, tool_type, tool_name, req_options)
    return layers["merged"]


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

class ToolPreviewResponse(BaseModel):
    tenant_id: str
    tool_type: str
    tool_name: str
    merged_options: Dict[str, Any]
    layers: Dict[str, Dict[str, Any]]



@router.post("/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(payload: ToolInvokeRequest) -> ToolInvokeResponse:
    # 生成 request_id（可替换为全局中间件注入的 trace_id/request_id）
    import uuid

    request_id = str(uuid.uuid4())
    # 把所有执行逻辑下沉到 core 执行器
    tenant = (payload.tenant_id or "_anon_")
    merged_options = _policy_merge_options(tenant, payload.tool_type, payload.tool_name, payload.options or {})
    result = await executor.execute(
        tenant_id=tenant,
        tool_type=payload.tool_type,
        tool_name=payload.tool_name,
        params=payload.params,
        options=merged_options,
    )
    return ToolInvokeResponse(
        request_id=request_id,
        tool_type=payload.tool_type,
        tool_name=payload.tool_name,
        result=result,
    )


@router.post("/preview", response_model=ToolPreviewResponse)
async def preview_tool_options(payload: ToolInvokeRequest) -> ToolPreviewResponse:
    tenant = (payload.tenant_id or "_anon_")
    layers = _policy_layers(tenant, payload.tool_type, payload.tool_name, payload.options or {})
    merged_options = layers.get("merged", {})
    return ToolPreviewResponse(
        tenant_id=tenant,
        tool_type=payload.tool_type,
        tool_name=payload.tool_name,
        merged_options=merged_options,
        layers=layers,
    )
