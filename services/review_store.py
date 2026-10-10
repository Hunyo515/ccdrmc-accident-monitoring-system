"""Oracle persistence for reviewed records; no local fallback."""
import json
import uuid
from contextlib import contextmanager
from services import storage_service

TABLES = {
'MDRRMC_RECORDS': '''RECORD_ID VARCHAR2(64) PRIMARY KEY, REVISION NUMBER NOT NULL, PAYLOAD CLOB NOT NULL CHECK (PAYLOAD IS JSON), CREATED_AT TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL''',
'MDRRMC_BATCHES': '''BATCH_ID VARCHAR2(64) PRIMARY KEY, SOURCE_NAME VARCHAR2(512), ORIGINAL_FILE BLOB, CREATED_BY VARCHAR2(128), CREATED_AT TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL''',
'MDRRMC_DRAFTS': '''DRAFT_ID VARCHAR2(64) PRIMARY KEY, BATCH_ID VARCHAR2(64) NOT NULL REFERENCES MDRRMC_BATCHES(BATCH_ID), STATUS VARCHAR2(20) NOT NULL, REVISION NUMBER NOT NULL, PAYLOAD CLOB NOT NULL CHECK (PAYLOAD IS JSON), CREATED_AT TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL''',
'MDRRMC_HISTORY': '''EVENT_ID VARCHAR2(64) PRIMARY KEY, RECORD_ID VARCHAR2(64), ACTOR VARCHAR2(128), ACTION VARCHAR2(40), PAYLOAD CLOB NOT NULL CHECK (PAYLOAD IS JSON), CREATED_AT TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL''',
'MDRRMC_STATE': '''STATE_ID NUMBER PRIMARY KEY, REVISION NUMBER NOT NULL'''
}

def decode(value):
    if isinstance(value, (dict,list)): return value
    return json.loads(value.read() if hasattr(value, 'read') else value)

def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)

@contextmanager
def transaction():
    with storage_service.connect() as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT REVISION FROM MDRRMC_STATE WHERE STATE_ID=1 FOR UPDATE WAIT 10')
                cursor.fetchone()
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise

def setup():
    with storage_service.connect() as connection, connection.cursor() as cursor:
        for name, columns in TABLES.items():
            cursor.execute('SELECT COUNT(*) FROM USER_TABLES WHERE TABLE_NAME=:name', name=name)
            if cursor.fetchone()[0]:
                continue
            cursor.execute(f'CREATE TABLE {name} ({columns})')
        cursor.execute('MERGE INTO MDRRMC_STATE s USING (SELECT 1 id FROM dual) x ON (s.STATE_ID=x.id) WHEN NOT MATCHED THEN INSERT (STATE_ID,REVISION) VALUES (1,0)')
        connection.commit()

def approved(cursor):
    cursor.execute('SELECT RECORD_ID, REVISION, PAYLOAD FROM MDRRMC_RECORDS ORDER BY CREATED_AT, RECORD_ID')
    return [dict(decode(p), record_id=i, record_revision=int(v)) for i,v,p in cursor]

def rows():
    with storage_service.connect() as connection, connection.cursor() as cursor:
        return approved(cursor)

def drafts(cursor, batch=None):
    sql='SELECT DRAFT_ID,BATCH_ID,STATUS,REVISION,PAYLOAD FROM MDRRMC_DRAFTS'
    if batch:
        cursor.execute(sql+' WHERE BATCH_ID=:b ORDER BY CREATED_AT,DRAFT_ID', b=batch)
    else:
        cursor.execute(sql+" WHERE STATUS='pending' ORDER BY CREATED_AT,DRAFT_ID")
    return [dict(decode(p), id=i, batch_id=b, status=s, revision=int(v)) for i,b,s,v,p in cursor]

def save_draft(cursor, draft, new=False):
    import oracledb
    cursor.setinputsizes(payload=oracledb.DB_TYPE_CLOB)
    payload=dump({k:v for k,v in draft.items() if k not in ('id','batch_id','status','revision')})
    params=dict(i=draft['id'], b=draft['batch_id'], s=draft['status'], v=draft['revision'], payload=payload)
    if new:
        cursor.execute('INSERT INTO MDRRMC_DRAFTS (DRAFT_ID,BATCH_ID,STATUS,REVISION,PAYLOAD) VALUES (:i,:b,:s,:v,:payload)',params)
    else:
        params.pop('b')
        cursor.execute('UPDATE MDRRMC_DRAFTS SET STATUS=:s,REVISION=:v,PAYLOAD=:payload WHERE DRAFT_ID=:i',params)

def history(cursor, record_id, actor, action, before, after, **extra):
    import oracledb
    cursor.setinputsizes(payload=oracledb.DB_TYPE_CLOB)
    cursor.execute('INSERT INTO MDRRMC_HISTORY (EVENT_ID,RECORD_ID,ACTOR,ACTION,PAYLOAD) VALUES (:i,:r,:a,:action,:payload)',
                   i=uuid.uuid4().hex,r=record_id,a=actor,action=action,payload=dump(dict(before=before,after=after,**extra)))

def save_record(cursor, record, previous=None):
    import oracledb
    cursor.setinputsizes(payload=oracledb.DB_TYPE_CLOB)
    values=dict(i=record['record_id'],v=record['record_revision'],payload=dump(record))
    if previous:
        cursor.execute('UPDATE MDRRMC_RECORDS SET REVISION=:v,PAYLOAD=:payload WHERE RECORD_ID=:i',values)
    else:
        cursor.execute('INSERT INTO MDRRMC_RECORDS (RECORD_ID,REVISION,PAYLOAD) VALUES (:i,:v,:payload)',values)
