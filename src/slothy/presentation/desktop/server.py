"""仅回环地址的桌面预览传输；真实 Application API，无模拟响应。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps, loads
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlsplit


def create_server(bridge, *, frontend, port=8765, dev_origins=()):
    root = Path(frontend).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # 默认不记录请求参数、输入或输出。

        def _json(self, status, value):
            body = dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _trusted(self):
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            allowed_origins = {"http://" + host for host in allowed_hosts} | set(dev_origins)
            return self.headers.get("Host") in allowed_hosts and (
                not self.headers.get("Origin") or self.headers["Origin"] in allowed_origins)

        def do_POST(self):
            if not self._trusted() or self.headers.get("X-Slothy-Client") != "desktop-ui":
                return self._json(403, {"ok": False, "error": {"code": "forbidden", "message": "请求来源不可用。"}})
            if not self.path.startswith("/api/") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": "需要 JSON 请求。"}})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 524288:
                    raise ValueError("size")
                payload = loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                return self._json(400, {"ok": False, "error": {"code": "invalid_request", "message": "请求格式或长度无效。"}})
            return self._json(200, bridge.request(self.path.removeprefix("/api/"), payload))

        def do_GET(self):
            if not self._trusted():
                return self._json(403, {"ok": False})
            relative = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
            target = (root / relative).resolve()
            allowed = {".html", ".css", ".js", ".png", ".svg", ".jpg", ".webp", ".ico", ".woff", ".woff2"}
            if not target.is_relative_to(root) or not target.is_file() or target.suffix.lower() not in allowed:
                return self._json(404, {"ok": False, "error": {"code": "not_found", "message": "先运行 frontend 构建，或通过 Vite 开发服务访问。"}})
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", (guess_type(target.name)[0] or "application/octet-stream") + ("; charset=utf-8" if target.suffix in {".html", ".css", ".js"} else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
