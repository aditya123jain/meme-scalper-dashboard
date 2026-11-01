#!/usr/bin/env python3
"""Read-only receiver for the paper meme-scalper dashboard. Stdlib only.
Keeps the latest snapshot (pushed by the trading box) in memory.
  GET  /d/<VIEW_TOKEN>/          -> dashboard page
  GET  /d/<VIEW_TOKEN>/api/data  -> latest snapshot JSON
  POST /ingest  (header X-Write-Secret: <WRITE_SECRET>) -> store snapshot
Everything else -> 404. No controls, no wallets, no keys."""
import os, json, time, hmac, gzip, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
VIEW_TOKEN = os.environ["VIEW_TOKEN"].encode()
WRITE_SECRET = os.environ["WRITE_SECRET"].encode()
PORT = int(os.environ.get("PORT", "10000"))
MAX_BODY = 3_000_000
snap = {"body": None, "t": 0.0}
lock = threading.Lock()

def page():
    with open(os.path.join(HERE, "index.html"), "rb") as f: return f.read()

class H(BaseHTTPRequestHandler):
    server_version = "dash"; sys_version = ""
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        if self.close_connection: self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Robots-Tag", "noindex, nofollow"); self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)
    def _get(self):
        parts = self.path.split("?", 1)[0].split("/")
        if len(parts) >= 3 and parts[1] == "d" and hmac.compare_digest(parts[2].encode(), VIEW_TOKEN):
            rest = "/".join(parts[3:])
            if rest in ("", "index.html"): return self._send(200, page(), "text/html; charset=utf-8")
            if rest == "api/data":
                with lock: body, t = snap["body"], snap["t"]
                if body is None: return self._send(200, json.dumps({"error": "waiting for first data push from the scalper box"}).encode(), "application/json")
                d = json.loads(body); d["push_age_s"] = time.time() - t
                return self._send(200, json.dumps(d).encode(), "application/json")
        return self._send(404, b"Not Found")
    do_GET = do_HEAD = _get
    def do_POST(self):
        # always consume the body (keep-alive safety) or close the connection if it is too big
        try: n = int(self.headers.get("Content-Length", "0"))
        except ValueError: n = -1
        raw = b""
        if 0 < n <= MAX_BODY: raw = self.rfile.read(n)
        else: self.close_connection = True
        if self.path.split("?", 1)[0] != "/ingest": return self._send(404, b"Not Found")
        if not hmac.compare_digest((self.headers.get("X-Write-Secret") or "").encode(), WRITE_SECRET):
            return self._send(401, b"unauthorized")
        try:
            if n <= 0 or n > MAX_BODY: return self._send(413, b"bad size")
            if self.headers.get("Content-Encoding") == "gzip": raw = gzip.decompress(raw)
            d = json.loads(raw)
            if not isinstance(d, dict): raise ValueError
        except Exception:
            return self._send(400, b"bad body")
        with lock: snap["body"], snap["t"] = raw, time.time()
        return self._send(200, b"ok")

if __name__ == "__main__":
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
