"""Exercise the packaged executable from outside its install directory."""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import urllib.request

root = Path(__file__).resolve().parents[1]
exe = root / 'dist' / 'editPDFbyAI' / ('editPDFbyAI.exe' if os.name == 'nt' else 'editPDFbyAI')
with tempfile.TemporaryDirectory() as folder:
    proc = subprocess.Popen([str(exe), '--no-open'], cwd=folder, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    lines = queue.Queue()
    def read():
        for line in proc.stdout:
            if line.startswith(b'http://127.0.0.1:'):
                lines.put(line.decode().strip())
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    try:
        url = lines.get(timeout=60)
        assert url, 'Packaged server exited before startup'
        base, token = url.split('/#')
        def request(path, body=None):
            req = urllib.request.Request(base + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'X-PDFedit-Token': token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        assert b'editPDFbyAI' in request('/')
        assert request('/app.js')
        request('/api/demo', {})
        assert request('/api/export').startswith(b'%PDF-')
        assert request('/api/page?page=1').startswith(b'\x89PNG')
        print('Packaged startup, assets, demo, render and PDF export passed.')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
