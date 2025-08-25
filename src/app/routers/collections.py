from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, Set
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from pydantic import BaseModel

from src.app.clients import qdrant as qcli
from src.app.clients import ollama
from fastapi.responses import StreamingResponse, Response, FileResponse
import json
import urllib.parse
import time
import asyncio
import uuid
import os
import tempfile
import json as _json
import gzip
import logging

from src.app.core.metrics import (
    IMPORT_SECONDS,
    IMPORT_ROWS_TOTAL,
    IMPORT_BATCHES_TOTAL,
    IMPORT_SKIPPED_TOTAL,
    EXPORT_SECONDS,
    EXPORT_ROWS_TOTAL,
    EXPORT_STATUS_TOTAL,
    DOWNLOAD_SECONDS,
    DOWNLOAD_BYTES_TOTAL,
    DOWNLOAD_ROWS_TOTAL,
    EXPORT_RUNNING,
    DOWNLOAD_RUNNING,
)

router = APIRouter(prefix="/collections", tags=["collections"]) 


class EnsureRequest(BaseModel):
    name: str
    vector_size: int
    distance: Optional[str] = None  # "COSINE" | "EUCLID" | "DOT"


class DeletePointsByIdsRequest(BaseModel):
    collection: str
    ids: List[Union[str, int]]


class DeletePointsByFilterRequest(BaseModel):
    collection: str
    filters: Dict[str, Any]


class UpsertTextsRequest(BaseModel):
    collection: str
    texts: List[str]
    metadatas: Optional[List[Dict[str, Any]]] = None  # 与 texts 对齐，可为空
    ids: Optional[List[Union[str, int]]] = None            # 可选自定义 ID
    model: Optional[str] = None                      # 覆盖 embeddings 模型


class ExportRequest(BaseModel):
    collection: str
    filters: Optional[Dict[str, Any]] = None
    with_vectors: bool = True
    with_payload: bool = True


class ImportRequest(BaseModel):
    collection: str
    jsonl: str  # 原始 JSONL 文本，每行一个对象：{"id":..., "vector": [...], "payload": {...}}
    continue_on_error: bool = False  # 出现错误时是否跳过继续导入
    max_error_examples: int = 5      # 返回的错误示例条数上限
    batch_size: int = 1000           # 批处理大小
    on_conflict: str = "upsert"      # upsert|skip


# 并发限制（可通过环境变量覆盖）
_EXPORT_MAX_CONCURRENCY = int(os.getenv("EXPORT_MAX_CONCURRENCY", "2"))
_DOWNLOAD_MAX_CONCURRENCY = int(os.getenv("DOWNLOAD_MAX_CONCURRENCY", "4"))

# 进程级信号量
_export_semaphore = asyncio.Semaphore(_EXPORT_MAX_CONCURRENCY)
_download_semaphore = asyncio.Semaphore(_DOWNLOAD_MAX_CONCURRENCY)


def _extract_vector_size(info: Dict[str, Any]) -> int:
    """Best-effort 从 Qdrant collection info 中提取向量维度 size。

    兼容多种结构：
    - info["config"]["params"]["vectors"]["size"]
    - info["params"]["vectors"]["size"]
    - info["params"]["size"]
    - info["vectors"]["size"]
    未找到则返回 0。
    """
    try:
        return int(info.get("config", {}).get("params", {}).get("vectors", {}).get("size") or 0)
    except Exception:
        pass
    try:
        return int(info.get("params", {}).get("vectors", {}).get("size") or 0)
    except Exception:
        pass
    try:
        return int(info.get("params", {}).get("size") or 0)
    except Exception:
        pass
    try:
        return int(info.get("vectors", {}).get("size") or 0)
    except Exception:
        pass
    return 0


@router.get("")
async def list_collections() -> Dict[str, Any]:
    return {"collections": qcli.list_collections()}


@router.get("/{name}")
async def collection_info(name: str) -> Dict[str, Any]:
    if not qcli.collection_exists(name):
        raise HTTPException(status_code=404, detail="collection not found")
    return {"name": name, "info": qcli.get_collection_info(name)}


@router.post("/ensure")
async def ensure_collection(req: EnsureRequest) -> Dict[str, Any]:
    from qdrant_client.http import models as qmodels

    dist = (req.distance or "COSINE").upper()
    try:
        distance = getattr(qmodels.Distance, dist)
    except AttributeError:
        raise HTTPException(status_code=400, detail=f"invalid distance: {req.distance}")
    qcli.ensure_collection(req.name, vector_size=req.vector_size, distance=distance)
    return {"name": req.name, "distance": distance.value, "vector_size": req.vector_size}


@router.delete("/{name}")
async def delete_collection(name: str) -> Dict[str, Any]:
    if not qcli.collection_exists(name):
        # idempotent delete
        return {"name": name, "deleted": False, "reason": "not found"}
    qcli.delete_collection(name)
    return {"name": name, "deleted": True}


@router.post("/{name}/clear")
async def clear_collection(name: str) -> Dict[str, Any]:
    if not qcli.collection_exists(name):
        raise HTTPException(status_code=404, detail="collection not found")
    qcli.clear_collection(name)
    return {"name": name, "cleared": True}


@router.post("/points/delete_by_ids")
async def delete_points_by_ids(req: DeletePointsByIdsRequest) -> Dict[str, Any]:
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids is required")
    deleted = qcli.delete_points_by_ids(req.collection, req.ids)
    return {"collection": req.collection, "deleted_ids": req.ids, "deleted_count": deleted}


@router.post("/points/delete_by_filter")
async def delete_points_by_filter(req: DeletePointsByFilterRequest) -> Dict[str, Any]:
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    if not req.filters:
        raise HTTPException(status_code=400, detail="filters is required")
    deleted = qcli.delete_points_by_filter(req.collection, req.filters)
    return {"collection": req.collection, "filters": req.filters, "deleted": True, "deleted_count": deleted}


@router.post("/points/upsert_texts")
async def upsert_texts(req: UpsertTextsRequest) -> Dict[str, Any]:
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is required")

    # 生成文本向量
    vecs = await ollama.embeddings(req.texts, model=req.model)
    if not vecs or len(vecs) != len(req.texts):
        raise HTTPException(status_code=500, detail="failed to embed texts")

    # 构造 payload（确保 text 字段存在）
    payloads: List[Dict[str, Any]] = []
    metas = req.metadatas or []
    for i, t in enumerate(req.texts):
        base: Dict[str, Any] = {"text": t}
        if i < len(metas) and isinstance(metas[i], dict):
            base.update(metas[i])
        payloads.append(base)

    # 写入 Qdrant
    qcli.upsert_vectors(req.collection, vectors=vecs, payloads=payloads, ids=req.ids)

    return {
        "collection": req.collection,
        "upserted": len(vecs),
        "ids": req.ids or [],
    }


@router.post("/export")
async def export_collection(req: ExportRequest):
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    # 直接使用 Qdrant scroll，规避潜在兼容性问题
    from qdrant_client.http import models as qmodels
    from src.app.clients.qdrant import get_client, _build_filter  # type: ignore

    client = get_client()
    flt = _build_filter(req.filters) if req.filters else None
    next_page: Optional[qmodels.ScrollOffset] = None
    lines: List[str] = []
    while True:
        points, next_page = client.scroll(
            collection_name=req.collection,
            limit=1000,
            with_vectors=req.with_vectors,
            with_payload=req.with_payload,
            offset=next_page,
            scroll_filter=flt,
        )
        if not points:
            break
        for p in points:
            vid = getattr(p, "id", None)
            vec = getattr(p, "vector", None)
            pl = getattr(p, "payload", None)
            # 若为多向量命名配置，vector 可能为 dict；当仅有一个向量时，取其中一个值
            if isinstance(vec, dict) and len(vec) == 1:
                try:
                    vec = list(vec.values())[0]
                except Exception:
                    pass
            # 构造行
            lines.append(json.dumps({"id": vid, "vector": vec if req.with_vectors else None, "payload": pl if req.with_payload else None}, ensure_ascii=False))
        if next_page is None:
            break
    body = "\n".join(lines) + ("\n" if lines else "")
    return Response(content=body, media_type="application/x-ndjson")


# -----------------------------
# 后台导出任务管理（内存版）
# -----------------------------
EXPORT_JOBS: Dict[str, Dict[str, Any]] = {}
_CLEANER_STARTED: bool = False
EXPORT_TTL_SECONDS: int = 3600  # 1h 保留

# Redis（可选）持久化
_redis = None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis  # type: ignore
        from src.app.config import settings
        _redis = aioredis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
    except Exception:
        _redis = None
    return _redis


async def _job_key(task_id: str) -> str:
    return f"export:job:{task_id}"


async def _job_load(task_id: str) -> Optional[Dict[str, Any]]:
    r = await _get_redis()
    if r is not None:
        try:
            data = await r.get(await _job_key(task_id))
            if data:
                return _json.loads(data)
        except Exception:
            pass
    return EXPORT_JOBS.get(task_id)


async def _job_save(task_id: str, job: Dict[str, Any], expire: Optional[int] = None) -> None:
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(await _job_key(task_id), _json.dumps(job, ensure_ascii=False), ex=expire)
        except Exception:
            pass
    EXPORT_JOBS[task_id] = job


async def _job_delete(task_id: str) -> None:
    r = await _get_redis()
    if r is not None:
        try:
            await r.delete(await _job_key(task_id))
        except Exception:
            pass
    EXPORT_JOBS.pop(task_id, None)


async def _run_export_task(task_id: str) -> None:
    job = await _job_load(task_id)
    if not job:
        return
    job["status"] = "running"
    job["started_at"] = time.time()
    params = job.get("params")
    if isinstance(params, dict):
        req = ExportStartRequest(**params)
    else:
        # 兼容旧内存对象
        req = params  # type: ignore
    await _job_save(task_id, job)
    # 并发控制：获取导出信号量
    await _export_semaphore.acquire()
    tenant = (job.get("tenant") or "_anon_")
    EXPORT_RUNNING.labels(collection=req.collection, tenant=tenant).inc()
    try:
        from qdrant_client.http import models as qmodels
        from src.app.clients.qdrant import get_client, _build_filter  # type: ignore

        client = get_client()
        flt = _build_filter(req.filters) if req.filters else None
        next_page: Optional[qmodels.ScrollOffset] = None
        total = 0

        # 创建临时文件（支持 gzip 后缀）
        suffix = ".jsonl.gz" if getattr(req, "with_gzip", False) else ".jsonl"
        fd, path = tempfile.mkstemp(prefix=f"export_{req.collection}_", suffix=suffix)
        os.close(fd)
        job["file_path"] = path

        # 依据 gzip 选择写入方式（文本模式）
        writer_ctx = gzip.open(path, "wt", encoding="utf-8") if getattr(req, "with_gzip", False) else open(path, "w", encoding="utf-8")
        with writer_ctx as f:
            while True:
                points, next_page = client.scroll(
                    collection_name=req.collection,
                    limit=1000,
                    with_vectors=req.with_vectors,
                    with_payload=req.with_payload,
                    offset=next_page,
                    scroll_filter=flt,
                )
                if not points:
                    break
                for p in points:
                    # 每条写入前从持久化存储读取最新任务状态，确保取消及时生效（兼容 Redis 持久化场景）
                    latest = await _job_load(task_id)
                    if latest and latest.get("cancelled"):
                        raise RuntimeError("cancelled")
                    vid = getattr(p, "id", None)
                    vec = getattr(p, "vector", None)
                    pl = getattr(p, "payload", None)
                    if isinstance(vec, dict) and len(vec) == 1:
                        try:
                            vec = list(vec.values())[0]
                        except Exception:
                            pass
                    line = json.dumps({
                        "id": vid,
                        "vector": vec if req.with_vectors else None,
                        "payload": pl if req.with_payload else None,
                    }, ensure_ascii=False)
                    f.write(line + "\n")
                    total += 1
                    job["written"] = total
                    await _job_save(task_id, job)
                    EXPORT_ROWS_TOTAL.labels(collection=req.collection, tenant=tenant).inc()
                    # 节流（可选）
                    if getattr(req, "delay_ms_per_point", 0) > 0:
                        await asyncio.sleep(max(req.delay_ms_per_point, 0) / 1000.0)
                    # 再次检查取消（避免在写入或睡眠期间发起的取消被错过）
                    latest = await _job_load(task_id)
                    if latest and latest.get("cancelled"):
                        raise RuntimeError("cancelled")
                if next_page is None:
                    break
        # 写入全部完成后，最终检查是否已被取消，若是则按取消收尾
        latest = await _job_load(task_id)
        if latest and latest.get("cancelled"):
            raise RuntimeError("cancelled")
        job["status"] = "succeeded"
        job["finished_at"] = time.time()
        job["total"] = total
        EXPORT_STATUS_TOTAL.labels(collection=req.collection, status="succeeded", tenant=tenant).inc()
        EXPORT_SECONDS.labels(collection=req.collection, tenant=tenant).observe(max(job["finished_at"] - job["started_at"], 0.0))
        await _job_save(task_id, job, expire=EXPORT_TTL_SECONDS)
        asyncio.create_task(_schedule_file_cleanup(task_id))
        logging.info("export_finish", extra={
            "event": "export_finish",
            "status": "succeeded",
            "task_id": task_id,
            "collection": req.collection,
            "written": total,
            "duration_ms": int((job["finished_at"] - job["started_at"]) * 1000),
            "file_path": job.get("file_path"),
            "trace_id": job.get("trace_id"),
        })
    except Exception as e:
        # 若被取消，标记为 cancelled
        if str(e) == "cancelled":
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
            job["error"] = None
            EXPORT_STATUS_TOTAL.labels(collection=req.collection, status="cancelled", tenant=tenant).inc()
            EXPORT_SECONDS.labels(collection=req.collection, tenant=tenant).observe(max(job["finished_at"] - job.get("started_at", job.get("created_at", time.time())), 0.0))
            await _job_save(task_id, job, expire=EXPORT_TTL_SECONDS)
            asyncio.create_task(_schedule_file_cleanup(task_id))
            logging.info("export_finish", extra={
                "event": "export_finish",
                "status": "cancelled",
                "task_id": task_id,
                "collection": req.collection,
                "written": job.get("written", 0),
                "duration_ms": int((job["finished_at"] - job.get("started_at", job.get("created_at", job["finished_at"])) ) * 1000),
                "trace_id": job.get("trace_id"),
            })
            return
        job["status"] = "failed"
        job["finished_at"] = time.time()
        job["error"] = str(e)
        EXPORT_STATUS_TOTAL.labels(collection=req.collection, status="failed", tenant=tenant).inc()
        EXPORT_SECONDS.labels(collection=req.collection, tenant=tenant).observe(max(job["finished_at"] - job.get("started_at", job.get("created_at", time.time())), 0.0))
        await _job_save(task_id, job, expire=EXPORT_TTL_SECONDS)
        asyncio.create_task(_schedule_file_cleanup(task_id))
        logging.error("export_finish", extra={
            "event": "export_finish",
            "status": "failed",
            "task_id": task_id,
            "collection": req.collection,
            "written": job.get("written", 0),
            "duration_ms": int((job["finished_at"] - job.get("started_at", job.get("created_at", job["finished_at"])) ) * 1000),
            "error": job.get("error"),
            "trace_id": job.get("trace_id"),
        })
    finally:
        # 释放导出并发槽位
        try:
            EXPORT_RUNNING.labels(collection=req.collection, tenant=tenant).dec()
        except Exception:
            pass
        try:
            _export_semaphore.release()
        except Exception:
            pass


async def _cleanup_export_jobs_loop():
    while True:
        try:
            now = time.time()
            to_delete: List[str] = []
            for tid, jb in list(EXPORT_JOBS.items()):
                st = jb.get("status")
                fin = jb.get("finished_at")
                if st in {"succeeded", "failed", "cancelled"} and fin and now - fin > EXPORT_TTL_SECONDS:
                    # 删除临时文件
                    fp = jb.get("file_path")
                    if fp and os.path.exists(fp):
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
                    to_delete.append(tid)
            for tid in to_delete:
                EXPORT_JOBS.pop(tid, None)
        except Exception:
            pass
        await asyncio.sleep(60)


class ExportStartRequest(ExportRequest):
    # 节流参数：每条写出后延迟毫秒数，便于在小数据上验证取消与长时任务
    delay_ms_per_point: int = 0
    # 结果是否 gzip 压缩（生成 .jsonl.gz 文件）
    with_gzip: bool = False


@router.post("/export/start")
async def export_start(req: ExportStartRequest, request: Request) -> Dict[str, Any]:
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    task_id = uuid.uuid4().hex
    tenant = getattr(getattr(request, "state", None), "tenant", None) or "_anon_"
    job = {
        "status": "pending",
        "created_at": time.time(),
        "params": req.dict(),
        "written": 0,
        "total": None,
        "file_path": None,
        "error": None,
        "cancelled": False,
        # 将请求 request_id 作为 trace_id 写入任务，便于重启后仍可关联
        "trace_id": getattr(getattr(request, "state", None), "request_id", None),
        # 记录租户，用于指标打点
        "tenant": tenant,
    }
    await _job_save(task_id, job)
    # 启动后台任务
    asyncio.create_task(_run_export_task(task_id))
    # 启动清理守护任务（仅一次）
    global _CLEANER_STARTED
    if not _CLEANER_STARTED:
        asyncio.create_task(_cleanup_export_jobs_loop())
        _CLEANER_STARTED = True
    logging.info("export_start", extra={
        "event": "export_start",
        "task_id": task_id,
        "collection": req.collection,
        "with_vectors": req.with_vectors,
        "with_payload": req.with_payload,
        "with_gzip": req.with_gzip,
        "delay_ms_per_point": req.delay_ms_per_point,
        "trace_id": job.get("trace_id"),
        "tenant": tenant,
    })
    return {"task_id": task_id, "status": "pending"}


@router.get("/export/status")
async def export_status(task_id: str) -> Dict[str, Any]:
    job = await _job_load(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="task not found")
    # 避免暴露文件路径
    resp = {k: v for k, v in job.items() if k != "file_path" and k != "params"}
    resp["task_id"] = task_id
    params_obj = job.get("params")
    if params_obj is None:
        resp["params"] = None
    else:
        # 兼容 Redis/内存中为 dict 的情况，以及历史对象为 Pydantic 模型的情况
        model_dump = getattr(params_obj, "model_dump", None)
        if callable(model_dump):
            resp["params"] = model_dump()
        else:
            resp["params"] = params_obj
    return resp


@router.get("/export/download_by_task")
async def export_download_by_task(task_id: str):
    job = await _job_load(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="task not found")
    if job.get("status") != "succeeded":
        raise HTTPException(status_code=400, detail="task not finished")
    path = job.get("file_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    params_obj = job.get("params")
    # 兼容 dict / pydantic
    if hasattr(params_obj, "model_dump"):
        params = params_obj.model_dump()
    else:
        params = params_obj or {}
    is_gzip = bool(params.get("with_gzip"))
    ext = ".jsonl.gz" if is_gzip else ".jsonl"
    media = "application/gzip" if is_gzip else "application/x-ndjson"
    filename = f"{params.get('collection', 'export')}_export_{task_id}{ext}"
    return FileResponse(path, media_type=media, filename=filename)


@router.delete("/export/task")
async def export_cancel(task_id: str) -> Dict[str, Any]:
    job = await _job_load(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="task not found")
    if job.get("status") in {"succeeded", "failed", "cancelled"}:
        return {"task_id": task_id, "status": job.get("status"), "message": "task already finished"}
    job["cancelled"] = True
    await _job_save(task_id, job)
    logging.info("export_cancel", extra={
        "event": "export_cancel",
        "task_id": task_id,
        "collection": job.get("params", {}).get("collection") if isinstance(job.get("params"), dict) else getattr(job.get("params"), "collection", None),
    })
    return {"task_id": task_id, "status": "cancelling"}


async def _schedule_file_cleanup(task_id: str) -> None:
    try:
        await asyncio.sleep(EXPORT_TTL_SECONDS)
        job = await _job_load(task_id)
        if not job:
            return
        fp = job.get("file_path")
        if fp and os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception:
                pass
        await _job_delete(task_id)
    except Exception:
        pass


@router.post("/import")
async def import_collection(req: ImportRequest) -> Dict[str, Any]:
    if not qcli.collection_exists(req.collection):
        raise HTTPException(status_code=404, detail="collection not found")
    # 校验向量维度
    info = qcli.get_collection_info(req.collection)
    expected_dim = _extract_vector_size(info)
    lines = [ln for ln in req.jsonl.splitlines() if ln.strip()]
    ids: List[Any] = []
    vectors: List[Any] = []
    payloads: List[Any] = []
    errors: List[Dict[str, Any]] = []
    skipped_conflicts = 0
    t0 = time.monotonic()
    for idx, ln in enumerate(lines, start=1):
        try:
            obj = json.loads(ln)
            vid = obj.get("id")
            vec = obj.get("vector")
            if not isinstance(vec, list):
                raise ValueError("vector must be a list of floats")
            if expected_dim and len(vec) != expected_dim:
                raise ValueError(f"vector dimension mismatch, expected {expected_dim}, got {len(vec)}")
            ids.append(vid)
            vectors.append(vec)
            payloads.append(obj.get("payload"))
        except Exception as e:
            if not req.continue_on_error:
                raise HTTPException(status_code=400, detail=f"invalid jsonl line at {idx}: {e}")
            if len(errors) < max(0, int(req.max_error_examples)):
                errors.append({"line_no": idx, "error": str(e), "line": ln[:500]})
            IMPORT_SKIPPED_TOTAL.labels(collection=req.collection, reason="error").inc()
            continue
    imported = 0
    batches = 0
    if vectors:
        # 批处理写入
        from src.app.clients.qdrant import get_client as _get_client
        client = _get_client()
        bs = max(1, int(req.batch_size or 1000))
        on_conflict = (req.on_conflict or "upsert").lower()
        for i in range(0, len(vectors), bs):
            sub_vecs = vectors[i:i+bs]
            sub_ids = ids[i:i+bs]
            sub_pls = payloads[i:i+bs]
            # 冲突跳过：仅对明确提供 id 的点进行检查
            if on_conflict == "skip":
                check_ids = [pid for pid in sub_ids if pid is not None]
                existing_ids: Set[Any] = set()
                if check_ids:
                    try:
                        existing = client.retrieve(collection_name=req.collection, ids=check_ids, with_vectors=False, with_payload=False)
                        existing_ids = {getattr(p, 'id', None) for p in existing}
                    except Exception:
                        existing_ids = set()
                # 过滤掉已存在的 id
                keep_vecs: List[Any] = []
                keep_ids: List[Any] = []
                keep_pls: List[Any] = []
                for v, pid, pl in zip(sub_vecs, sub_ids, sub_pls):
                    if pid is not None and pid in existing_ids:
                        skipped_conflicts += 1
                        IMPORT_SKIPPED_TOTAL.labels(collection=req.collection, reason="conflict").inc()
                        continue
                    keep_vecs.append(v)
                    keep_ids.append(pid)
                    keep_pls.append(pl)
                sub_vecs, sub_ids, sub_pls = keep_vecs, keep_ids, keep_pls
            if not sub_vecs:
                continue
            qcli.upsert_vectors(req.collection, vectors=sub_vecs, payloads=sub_pls, ids=sub_ids)
            batches += 1
            imported += len(sub_vecs)
            IMPORT_BATCHES_TOTAL.labels(collection=req.collection).inc()
            IMPORT_ROWS_TOTAL.labels(collection=req.collection).inc(len(sub_vecs))
    IMPORT_SECONDS.labels(collection=req.collection).observe(max(time.monotonic() - t0, 0.0))
    return {
        "collection": req.collection,
        "imported": imported,
        "total_lines": len(lines),
        "skipped": (len(lines) - len(vectors)) + skipped_conflicts,
        "conflicts_skipped": skipped_conflicts,
        "batches": batches,
        "errors": errors,
    }


@router.post("/import_file")
async def import_collection_file(
    collection: str = Form(...),
    file: UploadFile = File(...),
    continue_on_error: bool = Form(False),
    max_error_examples: int = Form(5),
    batch_size: int = Form(1000),
    on_conflict: str = Form("upsert"),
) -> Dict[str, Any]:
    """通过文件上传导入 NDJSON；自动识别 gzip。表单字段与 JSON 版保持一致。"""
    if not qcli.collection_exists(collection):
        raise HTTPException(status_code=404, detail="collection not found")
    # 读取文件并解压
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    # detect gzip by magic header 1F 8B
    if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
        import gzip, io
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gf:
                raw = gf.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"failed to gunzip: {e}")
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to decode file: {e}")

    info = qcli.get_collection_info(collection)
    expected_dim = _extract_vector_size(info)
    lines = [ln for ln in text.splitlines() if ln.strip()]

    ids: list = []
    vectors: list = []
    payloads: list = []
    errors: list[Dict[str, Any]] = []
    skipped_conflicts = 0
    t0 = time.monotonic()

    for idx, ln in enumerate(lines, start=1):
        try:
            obj = json.loads(ln)
            vid = obj.get("id")
            vec = obj.get("vector")
            if not isinstance(vec, list):
                raise ValueError("vector must be a list of floats")
            if expected_dim and len(vec) != expected_dim:
                raise ValueError(f"vector dimension mismatch, expected {expected_dim}, got {len(vec)}")
            ids.append(vid)
            vectors.append(vec)
            payloads.append(obj.get("payload"))
        except Exception as e:
            if not continue_on_error:
                raise HTTPException(status_code=400, detail=f"invalid jsonl line at {idx}: {e}")
            if len(errors) < max(0, int(max_error_examples)):
                errors.append({"line_no": idx, "error": str(e), "line": ln[:500]})
            IMPORT_SKIPPED_TOTAL.labels(collection=collection, reason="error").inc()
            continue

    imported = 0
    batches = 0
    if vectors:
        from src.app.clients.qdrant import get_client as _get_client
        client = _get_client()
        bs = max(1, int(batch_size or 1000))
        on_conf = (on_conflict or "upsert").lower()
        for i in range(0, len(vectors), bs):
            sub_vecs = vectors[i:i+bs]
            sub_ids = ids[i:i+bs]
            sub_pls = payloads[i:i+bs]
            if on_conf == "skip":
                check_ids = [pid for pid in sub_ids if pid is not None]
                existing_ids: set = set()
                if check_ids:
                    try:
                        existing = client.retrieve(collection_name=collection, ids=check_ids, with_vectors=False, with_payload=False)
                        existing_ids = {getattr(p, 'id', None) for p in existing}
                    except Exception:
                        existing_ids = set()
                keep_vecs: list = []
                keep_ids: list = []
                keep_pls: list = []
                for v, pid, pl in zip(sub_vecs, sub_ids, sub_pls):
                    if pid is not None and pid in existing_ids:
                        skipped_conflicts += 1
                        IMPORT_SKIPPED_TOTAL.labels(collection=collection, reason="conflict").inc()
                        continue
                    keep_vecs.append(v)
                    keep_ids.append(pid)
                    keep_pls.append(pl)
                sub_vecs, sub_ids, sub_pls = keep_vecs, keep_ids, keep_pls
            if not sub_vecs:
                continue
            qcli.upsert_vectors(collection, vectors=sub_vecs, payloads=sub_pls, ids=sub_ids)
            batches += 1
            imported += len(sub_vecs)
            IMPORT_BATCHES_TOTAL.labels(collection=collection).inc()
            IMPORT_ROWS_TOTAL.labels(collection=collection).inc(len(sub_vecs))
    IMPORT_SECONDS.labels(collection=collection).observe(max(time.monotonic() - t0, 0.0))

    return {
        "collection": collection,
        "imported": imported,
        "total_lines": len(lines),
        "skipped": (len(lines) - len(vectors)) + skipped_conflicts,
        "conflicts_skipped": skipped_conflicts,
        "batches": batches,
        "errors": errors,
    }


@router.get("/export/download")
async def export_download(
    collection: str,
    request: Request,
    with_vectors: bool = True,
    with_payload: bool = True,
    filters: Optional[str] = None,  # JSON 字符串，例如 {"tag":"faq"}
    gzip: bool = False,
    delay_ms_per_point: int = 0,
):
    """浏览器友好的下载接口，流式输出 JSONL，并设置下载文件名。

    查询参数：
    - collection: 集合名
    - with_vectors/with_payload: 是否包含向量/负载
    - filters: JSON 字符串，作为 payload 过滤条件
    """
    if not qcli.collection_exists(collection):
        raise HTTPException(status_code=404, detail="collection not found")

    try:
        parsed_filters: Optional[Dict[str, Any]] = json.loads(filters) if filters else None
    except Exception:
        raise HTTPException(status_code=400, detail="filters must be a valid JSON string")

    from qdrant_client.http import models as qmodels
    from src.app.clients.qdrant import get_client, _build_filter  # type: ignore

    client = get_client()
    flt = _build_filter(parsed_filters) if parsed_filters else None

    # 并发限制：下载并发。如果已满，直接 429
    if _download_semaphore.locked():
        raise HTTPException(status_code=429, detail="too many concurrent downloads")
    await _download_semaphore.acquire()
    tenant = getattr(getattr(request, "state", None), "tenant", None) or "_anon_"
    DOWNLOAD_RUNNING.labels(collection=collection, gzip=str(bool(gzip)).lower(), tenant=tenant).inc()

    logging.info("download_start", extra={
        "event": "download_start",
        "collection": collection,
        "gzip": bool(gzip),
        "with_vectors": with_vectors,
        "with_payload": with_payload,
        "delay_ms_per_point": delay_ms_per_point,
    })

    def line_iter():
        next_page: Optional[qmodels.ScrollOffset] = None
        while True:
            points, next_page = client.scroll(
                collection_name=collection,
                limit=1000,
                with_vectors=with_vectors,
                with_payload=with_payload,
                offset=next_page,
                scroll_filter=flt,
            )
            if not points:
                break
            for p in points:
                vid = getattr(p, "id", None)
                vec = getattr(p, "vector", None)
                pl = getattr(p, "payload", None)
                if isinstance(vec, dict) and len(vec) == 1:
                    try:
                        vec = list(vec.values())[0]
                    except Exception:
                        pass
                obj = {"id": vid}
                if with_vectors:
                    obj["vector"] = vec
                if with_payload:
                    obj["payload"] = pl
                yield json.dumps(obj, ensure_ascii=False) + "\n"
                # 节流（可选）
                if delay_ms_per_point and delay_ms_per_point > 0:
                    time.sleep(delay_ms_per_point / 1000.0)
            if next_page is None:
                break

    filename = urllib.parse.quote(f"{collection}.jsonl" + (".gz" if gzip else ""))
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}

    # 指标计数器
    t0 = time.monotonic()
    rows = 0
    bytes_out = 0

    def _finalize():
        duration = max(time.monotonic() - t0, 0.0)
        DOWNLOAD_SECONDS.labels(collection=collection, gzip=str(bool(gzip)).lower(), tenant=tenant).observe(duration)
        DOWNLOAD_BYTES_TOTAL.labels(collection=collection, gzip=str(bool(gzip)).lower(), tenant=tenant).inc(bytes_out)
        DOWNLOAD_ROWS_TOTAL.labels(collection=collection, tenant=tenant).inc(rows)
        logging.info(
            "download_finish",
            extra={
                "event": "download_finish",
                "collection": collection,
                "gzip": bool(gzip),
                "rows": rows,
                "bytes": bytes_out,
                "duration_ms": int(duration * 1000),
            },
        )
        # 并发指标与信号量释放
        try:
            DOWNLOAD_RUNNING.labels(collection=collection, gzip=str(bool(gzip)).lower(), tenant=tenant).dec()
        except Exception:
            pass
        try:
            _download_semaphore.release()
        except Exception:
            pass

    if not gzip:
        def stream_iter():
            nonlocal rows, bytes_out
            try:
                for chunk in line_iter():
                    data = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                    rows += 1
                    bytes_out += len(data)
                    yield data
            finally:
                _finalize()
        return StreamingResponse(stream_iter(), media_type="application/x-ndjson", headers=headers)

    # 按块 gzip 压缩流（使用 zlib 生成 gzip 格式：wbits=31）
    import zlib as _zlib
    def gzip_iter():
        compressor = _zlib.compressobj(level=6, wbits=31)
        nonlocal rows, bytes_out
        try:
            for chunk in line_iter():
                rows += 1
                data = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                out = compressor.compress(data)
                if out:
                    bytes_out += len(out)
                    yield out
            tail = compressor.flush()
            if tail:
                bytes_out += len(tail)
                yield tail
        finally:
            _finalize()

    headers["Content-Encoding"] = "gzip"
    return StreamingResponse(gzip_iter(), media_type="application/x-ndjson", headers=headers)
