"""Browser verification server; all Oracle test writes are rolled back."""
import os,sys,threading,subprocess
from pathlib import Path
from contextlib import contextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from services import storage_service as storage, review_store as db
from app import app
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler
class QuietHandler(WSGIRequestHandler):
    def log_request(self,*args,**kwargs):pass
real=storage.connect()
class BorrowedConnection:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def cursor(self):return real.cursor()
storage.connect=lambda:BorrowedConnection()
@contextmanager
def transaction():
    with real.cursor() as cursor:
        cursor.execute('SAVEPOINT qa_operation')
        cursor.execute('SELECT REVISION FROM MDRRMC_STATE WHERE STATE_ID=1 FOR UPDATE WAIT 10');cursor.fetchone()
        try:yield cursor
        except Exception:
            cursor.execute('ROLLBACK TO qa_operation');raise
db.transaction=transaction
password='temporary-browser-check'
app.config['LOGIN_PASSWORD_HASH']=generate_password_hash(password)
server=make_server('127.0.0.1',5053,app,request_handler=QuietHandler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
env=os.environ.copy();env['TEST_LOGIN_PASSWORD']=password
env['PLAYWRIGHT_MODULE']=r'C:\Users\june\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright'
try:
    result=subprocess.run(['node',os.getenv('QA_BROWSER_SCRIPT','scripts/qa_dataset.cjs')],env=env,timeout=180)
    sys.exit(result.returncode)
finally:
    server.shutdown();thread.join(timeout=5);real.rollback();real.close()
    print('All browser-test Oracle changes rolled back.')
