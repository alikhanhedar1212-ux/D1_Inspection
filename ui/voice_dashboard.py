"""LAN-accessible dashboard for existing voice recognition events."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import deque
import json
import argparse
import time

UI_ROOT = Path(__file__).resolve().parent
ROOT = UI_ROOT.parent / 'voice_navigation'


def snapshot():
    events = []
    path = ROOT / 'ui_events.jsonl'
    if path.exists():
        # Bounded read even after long-running recognition sessions.
        with path.open('rb') as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - 256000))
            if size > 256000:
                stream.readline()
            lines = deque(stream, maxlen=250)
        for line in lines:
            try:
                events.append(json.loads(line))
            except (ValueError, UnicodeDecodeError):
                pass
    running = False
    try:
        pid = int((ROOT / 'listener.pid').read_text())
        proc = Path('/proc') / str(pid)
        running = str(ROOT / 'voice_navigation.py').encode() in (proc / 'cmdline').read_bytes()
        running = running and (proc / 'stat').read_text().split()[2] != 'Z'
    except (OSError, ValueError):
        pass
    try:
        session = json.loads((ROOT / 'ui_session.json').read_text())
    except (OSError, ValueError):
        session = None
    return {'events': events, 'session': session, 'running': running, 'server_time': time.time()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?', 1)[0]
        if route == '/':
            data = (UI_ROOT / 'dashboard.html').read_bytes()
            content_type = 'text/html; charset=utf-8'
        elif route == '/api/events':
            data = json.dumps(snapshot(), ensure_ascii=False).encode()
            content_type = 'application/json; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0', help='Listening address; defaults to all IPv4 interfaces')
    parser.add_argument('--port', type=int, default=8091)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Voice dashboard: http://{args.host}:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
