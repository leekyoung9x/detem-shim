# detem-shim — Proxy thẳng vào tokenize.vn (không qua 9router)

Client → shim này → `https://tokenize.vn/v1`. Key detem giữ phía server
(env `DETEM_API_KEY`), client gọi không cần key.

Tự xử 2 việc:
- Body thiếu `"stream"` → tự chèn `stream: false` (detem trả rỗng nếu thiếu).
- Model `"dt/deepseek-v4.1-flash"` → strip về tên trần trước khi forward.

Chỉ dùng Python stdlib, không dependency.

## Chạy

```bash
DETEM_API_KEY=tk-... python3 shim.py [--host 0.0.0.0] [--port 20131] [--upstream https://tokenize.vn/v1]
```

Thiếu key là exit 2 ngay lúc khởi động.

## API (base `http://HOST:20131`, không cần Authorization)

- `GET /health` → `{"ok": true}`
- `GET /v1/models` → chỉ 2 model detem tên trần:
  `deepseek-v4-pro`, `deepseek-v4.1-flash`
- `POST /v1/chat/completions` → forward thẳng tokenize.vn:

```bash
curl http://127.0.0.1:20131/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-v4.1-flash","max_tokens":64,
       "messages":[{"role":"user","content":"hi"}]}'
```

`stream: true` được giữ nguyên (SSE relay).

## Log

Mỗi request 1 dòng: timestamp, path, model, `patched=true/false`
(có chèn `stream`/strip prefix không). Không log key, không log prompt.
