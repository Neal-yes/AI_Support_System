## Smoke: /api/v1/ask

- Plain: rc=0 http=200
  - response_len=28
  - use_rag=false
- RAG: rc=0 http=200
  - request_collection=metrics_demo_1d response_collection=metrics_demo_1d
  - sources_len=5 match=true
- result: PASS
