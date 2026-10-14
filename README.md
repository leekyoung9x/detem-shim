# detem-shim — Forward sang 9router, tự chèn `"stream": false`

Provider detem (tokenize.vn) qua 9router trả rỗng/cụt nếu body thiếu `stream`.
Shim này đứng giữa: client không cần gửi `stream`, shim tự chèn `stream: false`
trước khi forward. Client gửi `stream: true` được giữ nguyên (SSE relay).

Chỉ dùng Python stdlib, không dependency.

## Chạy

```bash
python3 shim.py [--host 127.0.0.1] [--port 20131] [--upstream http://127.0.0.1:20127]
```

## API (OpenAI-compatible, base `http://HOST:20131`)

- `GET /health` → `{"ok": true}`
- `GET /v1/models` → danh sách model của 9router (gồm `dt/deepseek-v4-pro`, `dt/deepseek-v4.1-flash`), cần header `Authorization: Bearer <key-9router>`
- `POST /v1/chat/completions` → forward sang 9router, tự chèn `stream:false` nếu thiếu

Ví dụ (không cần `stream`):

```bash
curl http://127.0.0.1:20131/v1/chat/completions \
  -H "Authorization: Bearer <key>" -H 'Content-Type: application/json' \
  -d '{"model":"dt/deepseek-v4.1-flash","max_tokens":64,
       "messages":[{"role":"user","content":"hi"}]}'
```

## Log

Mỗi request chat 1 dòng: timestamp, path, model, `stream_patched=true/false`
(cho biết có phải chèn `stream` không). Không log Authorization, không log prompt.
