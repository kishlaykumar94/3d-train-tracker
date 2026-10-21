"""Local server for the 3D train tracker.   Run:  python server.py   then open http://localhost:8765/"""
import json, os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import ntes

HERE = os.path.dirname(os.path.abspath(__file__))


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/status":
            b = json.dumps(ntes.api_status(parse_qs(u.query))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        super().do_GET()

    def end_headers(self):  # never cache, so edits show on a normal refresh
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Open http://localhost:8765/")
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
