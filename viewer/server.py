#!/usr/bin/env python3
"""
Daily Brief Viewer — local server.
Scans a data/ subfolder (next to this script) for Daily Brief HTML files and serves them.
Report files live under data/ so generated content stays separate from app code —
this matters once the viewer is Drive-synced or deployed anywhere beyond a single
local folder. No API keys, no external services, no CORS issues.

Usage: double-click launch.bat (Windows) or run install-startup.bat once for auto-start.
Opens: http://localhost:8765
"""
import http.server, json, os, sys, webbrowser, threading, time, re
from urllib.parse import urlparse, unquote

PORT = 8765
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
BRIEF_RE = re.compile(r'^Daily Brief_\d{4}-\d{2}-\d{2}', re.IGNORECASE)


def list_briefs():
    files = []
    if not os.path.isdir(DATA_DIR):
        return files
    for name in os.listdir(DATA_DIR):
        if BRIEF_RE.match(name) and name.lower().endswith('.html'):
            path = os.path.join(DATA_DIR, name)
            files.append({
                'name': name,
                'label': make_label(name),
                'size': os.path.getsize(path),
                'mtime': os.path.getmtime(path),
            })
    files.sort(key=lambda f: f['name'], reverse=True)
    return files


def make_label(name):
    m = re.match(r'Daily Brief_(\d{4}-\d{2}-\d{2})(?:_(\d{2})-(\d{2}))?', name, re.IGNORECASE)
    if not m:
        return name
    date_part = m.group(1)
    hour, minute = m.group(2), m.group(3)
    if hour and minute:
        return date_part + ' ' + hour + ':' + minute
    return date_part


def write_pid():
    pid_path = os.path.join(SCRIPT_DIR, '.server.pid')
    try:
        with open(pid_path, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def cleanup_pid():
    pid_path = os.path.join(SCRIPT_DIR, '.server.pid')
    try:
        os.remove(pid_path)
    except Exception:
        pass


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        msg = fmt % args
        if 'favicon' in self.path:
            return
        print(' ', self.address_string(), msg)

    def set_headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

    def do_GET(self):
        raw_path = urlparse(self.path).path
        path = '/' + raw_path.strip('/')

        # Main viewer
        if path in ('/', '/index.html', '/daily-brief-viewer.html'):
            fpath = os.path.join(SCRIPT_DIR, 'daily-brief-viewer.html')
            try:
                body = open(fpath, 'rb').read()
                self.set_headers(200, 'text/html; charset=utf-8', len(body))
                self.wfile.write(body)
            except FileNotFoundError:
                body = b'<h1>Viewer file not found</h1>'
                self.set_headers(404, 'text/html', len(body))
                self.wfile.write(body)
            return

        # Brief list API
        if path == '/api/briefs':
            body = json.dumps(list_briefs()).encode()
            self.set_headers(200, 'application/json', len(body))
            self.wfile.write(body)
            return

        # Serve a specific brief
        if path.startswith('/brief/'):
            name = unquote(path[len('/brief/'):])
            if not BRIEF_RE.match(name) or os.sep in name or '/' in name or '..' in name:
                body = b'Bad request'
                self.set_headers(400, 'text/plain', len(body))
                self.wfile.write(body)
                return
            fpath = os.path.join(DATA_DIR, name)
            if not os.path.isfile(fpath):
                body = b'Not found'
                self.set_headers(404, 'text/plain', len(body))
                self.wfile.write(body)
                return
            body = open(fpath, 'rb').read()
            self.set_headers(200, 'text/html; charset=utf-8', len(body))
            self.wfile.write(body)
            return

        # Favicon stub
        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        body = b'Not found'
        self.set_headers(404, 'text/plain', len(body))
        self.wfile.write(body)


def open_browser():
    time.sleep(0.8)
    webbrowser.open('http://localhost:' + str(PORT))


if __name__ == '__main__':
    viewer = os.path.join(SCRIPT_DIR, 'daily-brief-viewer.html')
    if not os.path.exists(viewer):
        print('ERROR: daily-brief-viewer.html not found in', SCRIPT_DIR)
        sys.exit(1)

    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        print('Created data folder:', DATA_DIR)
        print('Point your Drive sync (or wherever the daily-brief skill uploads reports) at this folder.')

    briefs = list_briefs()
    print('Daily Brief Viewer')
    print('  App folder:', SCRIPT_DIR)
    print('  Data folder:', DATA_DIR)
    print('  Briefs found:', len(briefs))
    for b in briefs[:5]:
        print('   -', b['name'])
    if len(briefs) > 5:
        print(f'   ... and {len(briefs) - 5} more')
    print(f'\nServing at http://localhost:{PORT}')
    print('Press Ctrl+C to stop.\n')

    server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
    write_pid()

    if '--no-browser' not in sys.argv:
        threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        cleanup_pid()
