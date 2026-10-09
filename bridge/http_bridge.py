#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import time

PORT = 8765

class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b''
        print(f"\n[bridge] {time.strftime('%H:%M:%S')} - {self.path}")
        if body:
            print(f"[bridge] Body: {body.decode('utf-8', errors='replace')[:500]}")
        
        response = b"decision:continue"
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)
        print(f"[bridge] Sent: {response}")

    def log_message(self, format, *args):
        pass

def run():
    server = HTTPServer(('', PORT), BridgeHandler)
    print(f"[bridge] Listening on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[bridge] Shutting down")

if __name__ == '__main__':
    run()
