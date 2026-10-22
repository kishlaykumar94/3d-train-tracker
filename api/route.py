"""Vercel stub: the real-landscape route lookup (OpenStreetMap, minutes on first use, cached on disk) needs the local server."""
import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"state": "error", "msg": "Real-landscape mode needs the local server (python server.py): tracing the track in OpenStreetMap is too slow for a serverless host."}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
