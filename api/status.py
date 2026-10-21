"""Vercel serverless function: /api/status?a=<train>&b=<train>[&as=<dd-Mon-yyyy>&bs=<dd-Mon-yyyy>]"""
import json, os, sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ntes

ntes.BACKGROUND = False      # a serverless instance can't keep a refresh thread alive after responding


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(ntes.api_status(parse_qs(urlparse(self.path).query))).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        # let Vercel's CDN reuse an answer for 30 s so repeat polls don't all hit NTES
        self.send_header("Cache-Control", "public, s-maxage=30, stale-while-revalidate=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
