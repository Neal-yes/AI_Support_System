from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge

# Shared Prometheus metrics (register once per process)
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path", "status"),
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "path", "status"),
)

# --- APP Specific Metrics ---

# Embedding 时间
EMBED_SECONDS = Histogram(
    "embed_duration_seconds",
    "Time spent generating embeddings",
    labelnames=("model",),
)

# RAG 检索（向量检索）时间
RAG_RETRIEVAL_SECONDS = Histogram(
    "rag_retrieval_duration_seconds",
    "Time spent retrieving top-k documents from vector DB",
    labelnames=("collection",),
)

# 生成（LLM 推理）时间
LLM_GENERATE_SECONDS = Histogram(
    "llm_generate_duration_seconds",
    "Time spent generating LLM responses",
    labelnames=("model", "stream"),
)

# RAG 命中计数（是否检索到至少一条）
RAG_MATCHES_TOTAL = Counter(
    "rag_matches_total",
    "Number of RAG requests with/without matches",
    labelnames=("collection", "has_match"),
)

# Import（批量导入）耗时
IMPORT_SECONDS = Histogram(
    "import_duration_seconds",
    "Time spent importing vectors",
    labelnames=("collection",),
)

# Import 条数
IMPORT_ROWS_TOTAL = Counter(
    "import_rows_total",
    "Number of rows imported (accepted)",
    labelnames=("collection",),
)

# Import 批次数
IMPORT_BATCHES_TOTAL = Counter(
    "import_batches_total",
    "Number of import batches executed",
    labelnames=("collection",),
)

# Import 跳过计数（冲突/错误）
IMPORT_SKIPPED_TOTAL = Counter(
    "import_skipped_total",
    "Number of rows skipped during import",
    labelnames=("collection", "reason"),  # reason: conflict|error
)

# Export（后台导出）耗时
EXPORT_SECONDS = Histogram(
    "export_duration_seconds",
    "Time spent exporting points to NDJSON",
    labelnames=("collection", "tenant"),
)

# Export 条数
EXPORT_ROWS_TOTAL = Counter(
    "export_rows_total",
    "Number of rows exported",
    labelnames=("collection", "tenant"),
)

# Export 状态计数
EXPORT_STATUS_TOTAL = Counter(
    "export_status_total",
    "Number of export tasks by final status",
    labelnames=("collection", "status", "tenant"),  # status: succeeded|failed|cancelled
)

# Download（直接下载）耗时
DOWNLOAD_SECONDS = Histogram(
    "download_duration_seconds",
    "Time spent streaming download of JSONL or GZIP",
    labelnames=("collection", "gzip", "tenant"),
)

# Download 输出字节（按响应体字节计数，gzip=true 为压缩后字节）
DOWNLOAD_BYTES_TOTAL = Counter(
    "download_bytes_total",
    "Total bytes streamed in download responses",
    labelnames=("collection", "gzip", "tenant"),
)

# Download 输出行数（导出点的数量）
DOWNLOAD_ROWS_TOTAL = Counter(
    "download_rows_total",
    "Total rows streamed in download responses",
    labelnames=("collection", "tenant"),
)

# --- Concurrency Gauges ---
# 正在运行的后台导出任务数量
EXPORT_RUNNING = Gauge(
    "export_running",
    "Number of export tasks currently running",
    labelnames=("collection", "tenant"),
)

# 正在进行的直接下载请求数量
DOWNLOAD_RUNNING = Gauge(
    "download_running",
    "Number of concurrent download requests in progress",
    labelnames=("collection", "gzip", "tenant"),
)
