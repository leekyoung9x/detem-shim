#!/usr/bin/env python3
"""detem-shim — forward sang 9router, tu chen "stream": false khi client khong gui.

Client (mozhenzhen...) -> 127.0.0.1:20131 (shim nay) -> 127.0.0.1:20127 (9router).
Provider detem (tokenize.vn) tra rong/cut neu body thieu stream -> shim chen
stream=false truoc khi forward. Client gui stream=true giu nguyen (SSE relay).

Chi stdlib (http.server + http.client). Chay:
  python3 /poki/tools/detem-shim/shim.py [--host 127.0.0.1] [--port 20131] [--upstream http://127.0.0.1:20127]
"""
import argparse
import datetime
import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

UPSTREAM = "http://127.0.0.1:20127"
FORWARD_TIMEOUT = 120
HOP_HEADERS = {"host", "connection", "keep-alive", "transfer-encoding",
               "upgrade", "proxy-authenticate", "proxy-authorization", "te", "trailer"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DetemShim/1.0"

    def log_message(self, *args):
        pass

    def log(self, path, model, patched):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        print(f"{ts} path={path} model={model} stream_patched={str(patched).lower()}",
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
        self._forward(None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        self._forward(raw)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_GET

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
                # Client khong gui stream (None) -> detem tra rong -> chen false.
                # stream=true giu nguyen de SSE relay.
                if body.get("stream") is None:
                    body["stream"] = False
                    patched = True
                    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                stream = body.get("stream") is True
        self.log(path, model, patched)

        fwd_headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_HEADERS}
        if is_chat:
            # Strip encoding/length cu (body co the doi sau patch), de phia
            # duoi tu thuong luong lai — tranh double-gzip/size lech.
            fwd_headers = {k: v for k, v in fwd_headers.items()
                           if k.lower() not in ("accept-encoding", "content-encoding",
                                                "content-length", "transfer-encoding")}
        try:
            conn = http.client.HTTPConnection(up.hostname, up.port or 80,
                                              timeout=FORWARD_TIMEOUT)
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
    global UPSTREAM
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=20131)
    ap.add_argument("--upstream", default="http://127.0.0.1:20127")
    args = ap.parse_args()
    UPSTREAM = args.upstream.rstrip("/")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"[detem-shim] listening {args.host}:{args.port} -> {UPSTREAM}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
