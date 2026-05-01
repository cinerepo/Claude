#!/usr/bin/env python3
"""
server.py — Cinesys IPAM web server (stdlib only, no Flask required)
Usage: python3 server.py [--port 8765]
"""

import json, pathlib, argparse
from http.server import SimpleHTTPRequestHandler, HTTPServer

BASE = pathlib.Path(__file__).parent
DATA_FILE = BASE / "ipam_data.json"
PORT = 8765

class IPAMHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/api/data":
            self._serve_json()
        else:
            # Serve static files from BASE dir (index.html, etc.)
            super().do_GET()

    def _serve_json(self):
        if not DATA_FILE.exists():
            body = b'{"error":"ipam_data.json not found. Run: python3 ingest.py <discovery_json>"}'
            code = 404
        else:
            body = DATA_FILE.read_bytes()
            code = 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Only log non-asset requests
        if not any(self.path.endswith(x) for x in [".ico", ".png", ".css", ".js"]):
            super().log_message(fmt, *args)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    import os
    os.chdir(BASE)
    httpd = HTTPServer(("", args.port), IPAMHandler)
    print(f"Cinesys IPAM server → http://localhost:{args.port}")
    print(f"  Data file : {DATA_FILE}")
    print(f"  Ingest    : python3 ingest.py <discovery_json>")
    print("  Ctrl+C to stop\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
