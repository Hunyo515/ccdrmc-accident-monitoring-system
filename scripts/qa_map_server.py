"""Run map browser QA against CSV only; never connect to production Oracle."""
import os
os.environ['DATA_BACKEND'] = 'csv'
import sys
import threading
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server
app.config['LOGIN_PASSWORD_HASH'] = generate_password_hash('map-browser-check')
server = make_server('127.0.0.1', 5055, app)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    sys.exit(subprocess.run(['node', 'scripts/qa_map.cjs'], timeout=150).returncode)
finally:
    server.shutdown()
    thread.join(timeout=5)
