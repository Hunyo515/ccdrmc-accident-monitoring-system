"""Explicit setup: python scripts/oracle_setup.py [--seed]."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent/'.env')
import pandas as pd
from services import storage_service as store

p=argparse.ArgumentParser(); p.add_argument('--seed',action='store_true'); args=p.parse_args()
with store.connect() as conn,conn.cursor() as cur:
    import oracledb
    try:
        cur.execute(f'''CREATE TABLE {store.table()} (
          RECORD_HASH VARCHAR2(64) PRIMARY KEY,
          RECORD_JSON CLOB CHECK (RECORD_JSON IS JSON),
          CREATED_AT TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL)''')
        print('Crash-record table created.')
    except oracledb.DatabaseError as e:
        if e.args[0].code!=955: raise
        print('Table already exists; keeping existing records.')
    if args.seed:
        import json
        cur.execute(f'SELECT RECORD_HASH FROM {store.table()}')
        seen={r[0] for r in cur}
        records=json.loads(pd.read_csv(store.CSV_PATH).to_json(orient='records'))
        new=[]
        for r in records:
            h=store.fingerprint(r)
            if h not in seen: new.append(dict(h=h,p=json.dumps(r))); seen.add(h)
        cur.setinputsizes(h=64,p=oracledb.DB_TYPE_CLOB)
        cur.executemany(f'INSERT INTO {store.table()} (RECORD_HASH,RECORD_JSON) VALUES (:h,:p)',new)
        conn.commit(); print(f'{len(new)} records seeded; existing records kept.')
