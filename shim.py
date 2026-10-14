#!/usr/bin/env python3
"""detem-shim — proxy thang vao tokenize.vn, khong qua 9router.

Client (mozhenzhen...) -> shim nay -> https://tokenize.vn/v1
- Tu giu DETEM_API_KEY phia server (env DETEM_API_KEY), client khong can key that.
- Body thieu "stream" -> tu chen stream=false (detem tra rong neu thieu).
- Model "dt/deepseek-v4.1-flash" -> strip ve tran truoc khi forward.
- GET /v1/models -> chi hien 2 model detem ten tran.

Chi stdlib (http.server + http.client). Chay:
  DETEM_API_KEY=tk-... python3 shim.py [--host 0.0.0.0] [--port 20131] [--upstream https://tokenize.vn/v1]
"""
import argparse
import datetime
import gzip
import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

UPSTREAM = "https://tokenize.vn/v1"
DETEM_API_KEY = os.environ.get("DETEM_API_KEY", "")
# Model detem ho tro (ten tran nhu goi direct)
DT_MODELS = ("deepseek-v4.1-flash", "deepseek-v4-pro")
DT_PREFIX = "dt/"
FORWARD_TIMEOUT = 120
HOP_HEADERS = {"host", "connection", "keep-alive", "transfer-encoding",
               "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer",
               "authorization", "content-length"}


def upstream_conn(up):
    if up.scheme == "https":
        return http.client.HTTPSConnection(up.hostname, up.port or 443,
                                           timeout=FORWARD_TIMEOUT)
    return http.client.HTTPConnection(up.hostname, up.port or 80,
                                      timeout=FORWARD_TIMEOUT)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DetemShim/1.0"

    def log_message(self, *args):
        pass

    def log(self, path, model, patched):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        print(f"{ts} path={path} model={model} patched={str(patched).lower()}",
              flush=True)

    def _send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(200, {"ok": True})
            return
        if path == "/v1/models":
            self._models()
            return
        self._forward(None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        self._forward(raw)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_GET

    def _models(self):
        # Forward len tokenize, loc chi giu model detem ten tran.
        # Tokenize hong /models -> tra static.
        up = urlsplit(UPSTREAM)
        data = None
        try:
            conn = upstream_conn(up)
            conn.request("GET", "/v1/models",
                         headers={"Authorization": "Bearer " + DETEM_API_KEY})
            resp = conn.getresponse()
            if resp.status == 200:
                data = resp.read()
            conn.close()
        except Exception:
            data = None
        items = []
        if data:
            try:
                payload = json.loads(data.decode("utf-8"))
                for m in payload.get("data") or []:
                    mid = m.get("id", "")
                    if mid in DT_MODELS:
                        items.append({"id": mid, "object": "model",
                                      "created": m.get("created", 0),
                                      "owned_by": "detem"})
            except Exception:
                items = []
        if not items:
            items = [{"id": m, "object": "model", "created": 0,
                      "owned_by": "detem"} for m in DT_MODELS]
        self.log("/v1/models", "-", False)
        self._send_json(200, {"object": "list", "data": items})

    def _forward(self, raw):
        up = urlsplit(UPSTREAM)
        path_qs = self.path
        path = urlsplit(path_qs).path
        is_chat = path.endswith(("/chat/completions", "/responses"))
        model, stream, patched = "-", False, False

        body = None
        if is_chat and raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = None
            if isinstance(body, dict):
                model = body.get("model") or "-"
                # Strip prefix dt/ -> ten tran nhu goi direct.
                if isinstance(model, str) and model.startswith(DT_PREFIX):
                    body["model"] = model[len(DT_PREFIX):]
                    model = body["model"]
                    patched = True
                # Thieu stream -> chen false (detem tra rong neu thieu).
                if body.get("stream") is None:
                    body["stream"] = False
                    patched = True
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                stream = body.get("stream") is True
        self.log(path, model, patched)

        fwd_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_HEADERS}
        # Key that nam server, client khong can biet.
        fwd_headers["Authorization"] = "Bearer " + DETEM_API_KEY
        fwd_headers["Content-Type"] = "application/json"
        try:
            conn = upstream_conn(up)
            # Map path ve upstream: /v1/... giu nguyen (tokenize goc /v1).
            conn.request(self.command, path_qs, body=raw, headers=fwd_headers)
            resp = conn.getresponse()
            if stream and is_chat:
                self.send_response(resp.status, resp.reason)
                for k, v in resp.getheaders():
                    if k.lower() not in ("content-length", "transfer-encoding",
                                         "connection", "content-encoding"):
                        self.send_header(k, v)
                if not resp.getheader("Content-Type"):
                    self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    piece = resp.read(8192)
                    if not piece:
                        break
                    self.wfile.write(b"%X\r\n%s\r\n" % (len(piece), piece))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                data = resp.read()
                # Giai nen neu upstream tra gzip/deflate (client cu khong gui
                # Accept-Encoding nhu curl/postman mac dinh van nhan gzip).
                enc = (resp.getheader("Content-Encoding") or "").lower()
                if data and enc == "gzip":
                    try:
                        data = gzip.decompress(data)
                    except Exception:
                        pass
                elif data and enc == "deflate":
                    try:
                        import zlib
                        data = zlib.decompress(data)
                    except Exception:
                        pass
                self.send_response(resp.status, resp.reason)
                for k, v in resp.getheaders():
                    if k.lower() not in ("content-length", "transfer-encoding",
                                         "connection", "content-encoding"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                if data:
                    self.wfile.write(data)
            try:
                self.close_connection = True
            except Exception:
                pass
            conn.close()
        except Exception as e:
            try:
                self._send_json(502, {"error": {"message": f"upstream error: {e}",
                                                "type": "upstream_error"}})
            except Exception:
                pass


def main():
    global UPSTREAM, DETEM_API_KEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=20131)
    ap.add_argument("--upstream", default="https://tokenize.vn/v1")
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()
    UPSTREAM = args.upstream.rstrip("/")
    if args.api_key:
        DETEM_API_KEY = args.api_key
    if not DETEM_API_KEY:
        print("FATAL: thieu DETEM_API_KEY (env hoac --api-key)", flush=True)
        raise SystemExit(2)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"[detem-shim] listening {args.host}:{args.port} -> {UPSTREAM}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
