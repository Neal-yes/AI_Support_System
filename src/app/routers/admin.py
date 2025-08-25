from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ---------- Pydantic Models ----------
class EvalItem(BaseModel):
    # 可按需扩展字段：query/expected_answer/rubric/check_type/labels/context等
    query: str
    expected_answer: Optional[str] = None
    check_type: Optional[str] = None
    labels: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None


class EvalCreate(BaseModel):
    name: str = Field(..., description="评测集名称")
    description: Optional[str] = None


class EvalUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Eval(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items_count: int = 0


class EvalImportPayload(BaseModel):
    items: List[EvalItem]


class EvalRunCreate(BaseModel):
    config_version: Optional[str] = None


class EvalRun(BaseModel):
    id: str
    eval_id: str
    created_at: datetime
    status: str = Field("completed", description="queued|running|completed|failed")
    # 最小占位指标，后续接入真实评测后替换
    metrics: Dict[str, Any] = Field(default_factory=dict)


# ---------- In-memory Stores + JSON 持久化 ----------
DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "admin_evals.json"

EVALS: Dict[str, Eval] = {}
EVAL_ITEMS: Dict[str, List[EvalItem]] = {}
EVAL_RUNS: Dict[str, EvalRun] = {}


def _serialize_dt(dt: datetime) -> str:
    return dt.isoformat()


def _deserialize_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _save_store() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "evals": {k: v.model_dump() | {"created_at": _serialize_dt(v.created_at), "updated_at": _serialize_dt(v.updated_at)} for k, v in EVALS.items()},
            "eval_items": {k: [i.model_dump() for i in lst] for k, lst in EVAL_ITEMS.items()},
            "eval_runs": {k: r.model_dump() | {"created_at": _serialize_dt(r.created_at)} for k, r in EVAL_RUNS.items()},
        }
        DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        # 持久化失败不阻断主流程（可在日志中记录，后续接入统一日志）
        pass


def _load_store() -> None:
    if not DATA_FILE.exists():
        return
    try:
        data = json.loads(DATA_FILE.read_text())
        EVALS.clear()
        EVAL_ITEMS.clear()
        EVAL_RUNS.clear()
        for k, v in (data.get("evals") or {}).items():
            EVALS[k] = Eval(
                id=v["id"],
                name=v["name"],
                description=v.get("description"),
                created_at=_deserialize_dt(v["created_at"]),
                updated_at=_deserialize_dt(v["updated_at"]),
                items_count=int(v.get("items_count", 0)),
            )
        for k, items in (data.get("eval_items") or {}).items():
            EVAL_ITEMS[k] = [EvalItem(**it) for it in items]
        for k, v in (data.get("eval_runs") or {}).items():
            EVAL_RUNS[k] = EvalRun(
                id=v["id"],
                eval_id=v["eval_id"],
                created_at=_deserialize_dt(v["created_at"]),
                status=v.get("status", "completed"),
                metrics=v.get("metrics", {}),
            )
    except Exception:
        # 读取失败时忽略（可在日志中记录）
        EVALS.clear(); EVAL_ITEMS.clear(); EVAL_RUNS.clear()


# 模块加载时尝试恢复
_load_store()


# ---------- Eval CRUD ----------
@router.get("/evals", response_model=List[Eval])
async def list_evals() -> List[Eval]:
    return list(EVALS.values())


@router.post("/evals", response_model=Eval)
async def create_eval(payload: EvalCreate) -> Eval:
    now = datetime.utcnow()
    eid = str(uuid.uuid4())
    rec = Eval(
        id=eid,
        name=payload.name,
        description=payload.description,
        created_at=now,
        updated_at=now,
        items_count=0,
    )
    EVALS[eid] = rec
    EVAL_ITEMS[eid] = []
    _save_store()
    return rec


@router.get("/evals/{eval_id}", response_model=Eval)
async def get_eval(eval_id: str) -> Eval:
    rec = EVALS.get(eval_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Eval not found")
    return rec


@router.put("/evals/{eval_id}", response_model=Eval)
async def update_eval(eval_id: str, payload: EvalUpdate) -> Eval:
    rec = EVALS.get(eval_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Eval not found")
    update_data = rec.model_dump()
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.description is not None:
        update_data["description"] = payload.description
    update_data["updated_at"] = datetime.utcnow()
    updated = Eval(**update_data)
    EVALS[eval_id] = updated
    _save_store()
    return updated


@router.delete("/evals/{eval_id}")
async def delete_eval(eval_id: str) -> Dict[str, str]:
    if eval_id not in EVALS:
        raise HTTPException(status_code=404, detail="Eval not found")
    EVALS.pop(eval_id, None)
    EVAL_ITEMS.pop(eval_id, None)
    # 同时清理关联的 runs
    to_delete = [rid for rid, r in EVAL_RUNS.items() if r.eval_id == eval_id]
    for rid in to_delete:
        EVAL_RUNS.pop(rid, None)
    _save_store()
    return {"status": "ok"}


# ---------- Eval Import ----------
@router.post("/evals/{eval_id}/import", response_model=Eval)
async def import_eval_items(eval_id: str, payload: EvalImportPayload) -> Eval:
    rec = EVALS.get(eval_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Eval not found")
    EVAL_ITEMS.setdefault(eval_id, [])
    EVAL_ITEMS[eval_id].extend(payload.items)
    rec.items_count = len(EVAL_ITEMS[eval_id])
    rec.updated_at = datetime.utcnow()
    EVALS[eval_id] = rec
    _save_store()
    return rec


# ---------- Eval Runs ----------
@router.post("/evals/{eval_id}/runs", response_model=EvalRun)
async def create_eval_run(eval_id: str, payload: EvalRunCreate) -> EvalRun:
    if eval_id not in EVALS:
        raise HTTPException(status_code=404, detail="Eval not found")
    run_id = str(uuid.uuid4())
    now = datetime.utcnow()
    items = EVAL_ITEMS.get(eval_id, [])
    # 占位：立即完成并给出基础统计。后续接入真实执行与评分。
    metrics = {
        "config_version": payload.config_version or "dev",
        "total_items": len(items),
        "passed": len(items),  # 占位为全通过
        "failed": 0,
        "accuracy": 1.0 if items else None,
    }
    run = EvalRun(id=run_id, eval_id=eval_id, created_at=now, status="completed", metrics=metrics)
    EVAL_RUNS[run_id] = run
    _save_store()
    return run


@router.get("/eval-runs", response_model=List[EvalRun])
async def list_eval_runs() -> List[EvalRun]:
    # 按创建时间倒序
    return sorted(EVAL_RUNS.values(), key=lambda r: r.created_at, reverse=True)


@router.get("/eval-runs/{run_id}", response_model=EvalRun)
async def get_eval_run(run_id: str) -> EvalRun:
    run = EVAL_RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return run
