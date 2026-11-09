"""Deterministic worker subprocess used by cancellation integration tests."""
import json
from pathlib import Path
import subprocess
import sys
import time

request = json.loads(sys.stdin.readline())
mode = request['operation']
if mode == 'crash':
    raise SystemExit(7)
if mode == 'complete':
    print(json.dumps(['done', request['folder']]), flush=True)
else:
    Path(request['folder'], 'keep.part').write_bytes(b'partial download')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    print(json.dumps(['processing', {'child_pid': child.pid}]), flush=True)
    if mode == 'orphan-crash':
        raise SystemExit(7)
    while True:
        time.sleep(.05)
