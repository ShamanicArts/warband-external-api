#!/usr/bin/env python3
"""
Warband Bridge v2 — full duplex.
Receives state from game, sends commands back.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import time

PORT = 8765
decision_queue = []

class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b''
        ts = time.strftime('%H:%M:%S')
        
        print(f"\n[{ts}] === STATE ===")
        if body:
            print(f"  {body.decode('utf-8', errors='replace')[:500]}")
        
        if decision_queue:
            decision = decision_queue.pop(0).encode()
            print(f"  → Decision: {decision}")
        else:
            decision = b"OK"
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(decision)))
        self.end_headers()
        self.wfile.write(decision)

    def log_message(self, format, *args):
        pass

def queue_decision(cmd):
    """Queue a command for the next state poll."""
    decision_queue.append(cmd)
    print(f"[queue] {cmd}")

def run():
    server = HTTPServer(('', PORT), BridgeHandler)
    print(f"[bridge] Listening on http://localhost:{PORT}")
    print(f"[bridge] Call queue_decision('CMD') from Python to send commands")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[bridge] Shutting down")

if __name__ == '__main__':
    run()
