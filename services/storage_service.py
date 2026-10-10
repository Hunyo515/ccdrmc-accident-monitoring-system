"""CSV or Oracle storage. Credentials never leave the server.
Oracle table creation is an explicit administrator command, not a page load.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
CSV_PATH=BASE/'data/Echague-Road-Accident-Cleaned.csv'
IDENTITY_FIELDS=['incident_id','accident_id','date','time','hour','minute','at_user','vehicle_involved','collision_type','cause','damage_injury','latitude','longitude','barangay','municipality','province','severity']


def backend(): return os.getenv('DATA_BACKEND','oracle').lower()


def identifier(value):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_$#]*(?:\.[A-Za-z][A-Za-z0-9_$#]*)?',value):
        raise ValueError('Oracle table must be a plain table name or SCHEMA.TABLE.')
    return value


def connect():
    import oracledb
    password=os.getenv('ORACLE_PASSWORD','')
    if not password: raise ValueError('Set ORACLE_PASSWORD in the server environment or local .env file.')
    return oracledb.connect(user=os.getenv('ORACLE_USER','rescue'),password=password,
        host=os.getenv('ORACLE_HOST','localhost'),port=int(os.getenv('ORACLE_PORT','1521')),
        service_name=os.getenv('ORACLE_SERVICE','XEPDB1'),tcp_connect_timeout=10)


def table(): return identifier(os.getenv('ORACLE_TABLE','MDRRMC_RECORDS'))


def fingerprint(row):
    from services.upload_service import date_value, normalize_category, text
    if text(row.get('record_id')):
        return hashlib.sha256(('record_id:'+text(row.get('record_id'))).encode()).hexdigest()
    values={k:text(row.get(k)) for k in IDENTITY_FIELDS}
    dt=date_value(values['date'],'month_first')
    if not pd.isna(dt): values['date']=dt.strftime('%Y-%m-%d')
    for k in ('vehicle_involved','cause','collision_type','barangay'):
        values[k]=normalize_category(k,values[k])
    for k in ('hour','minute','latitude','longitude'):
        try: values[k]=str(float(values[k]))
        except ValueError: pass
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def unique_new(existing,incoming):
    seen={fingerprint(r) for r in existing.to_dict('records')}
    indices=[]
    for idx,row in incoming.iterrows():
        key=fingerprint(row)
        if key not in seen: indices.append(idx); seen.add(key)
    return incoming.loc[indices].copy()


def load():
    if backend()=='csv': return pd.read_csv(CSV_PATH)
    if backend()!='oracle': raise ValueError('DATA_BACKEND must be csv or oracle.')
    if table() == 'MDRRMC_RECORDS':
        from services import review_store
        return pd.DataFrame(review_store.rows())
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(f'SELECT RECORD_JSON FROM {table()} ORDER BY CREATED_AT, RECORD_HASH')
        rows=[]
        for (payload,) in cursor:
            rows.append(json.loads(payload.read() if hasattr(payload,'read') else payload))
    if not rows: raise ValueError('Oracle has no records. Run python scripts/oracle_setup.py --seed before enabling DATA_BACKEND=oracle.')
    return pd.DataFrame(rows)


def save_append(new,combined):
    if backend()=='csv':
        temp=CSV_PATH.with_suffix('.tmp')
        combined.to_csv(temp,index=False)
        os.replace(temp,CSV_PATH)
        return
    with connect() as conn,conn.cursor() as cursor:
        import oracledb
        cursor.setinputsizes(record_hash=64,record_json=oracledb.DB_TYPE_CLOB)
        records=json.loads(new.to_json(orient='records',date_format='iso'))
        cursor.executemany(f'INSERT INTO {table()} (RECORD_HASH, RECORD_JSON) VALUES (:record_hash, :record_json)',
            [dict(record_hash=fingerprint(r),record_json=json.dumps(r)) for r in records])
        conn.commit()


def agency_records():
    source=os.getenv('ORACLE_SOURCE_TABLE','')
    if not source: raise ValueError('Set ORACLE_SOURCE_TABLE to the agency table or view to import.')
    source=identifier(source)
    with connect() as conn,conn.cursor() as cursor:
        cursor.execute(f'SELECT * FROM {source} WHERE ROWNUM <= 100001')
        columns=[d[0] for d in cursor.description]
        rows=cursor.fetchall()
    if len(rows)>100000: raise ValueError('The agency source has over 100,000 rows. Use a filtered Oracle view for each import batch.')
    return pd.DataFrame(rows,columns=columns)
