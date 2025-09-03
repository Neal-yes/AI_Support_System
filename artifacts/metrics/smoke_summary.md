## Smoke: /api/v1/ask

- Plain: rc=0 http=200
  - response_len=24
  - use_rag=false
- RAG: rc=22 http=500
  - sources_len=0 match=null
- result: FAIL (plain validation)
