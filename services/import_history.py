"""Recoverable import receipts and guarded reversal using existing Oracle audit tables."""
import io
import pandas as pd
from services import review_store as db, storage_service as storage


def list_imports(page=1):
    page=max(1,page)
    with storage.connect() as connection,connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM MDRRMC_HISTORY WHERE ACTION='dataset imported'")
        total=int(cursor.fetchone()[0])
        cursor.execute("""SELECT h.PAYLOAD,h.CREATED_AT,h.ACTOR,b.SOURCE_NAME
            FROM MDRRMC_HISTORY h JOIN MDRRMC_BATCHES b ON b.BATCH_ID=JSON_VALUE(h.PAYLOAD,'$.batch_id')
            WHERE h.ACTION='dataset imported' ORDER BY h.CREATED_AT DESC,h.EVENT_ID DESC
            OFFSET :offset ROWS FETCH NEXT 20 ROWS ONLY""",offset=(page-1)*20)
        entries=[]
        for payload,created,actor,name in cursor:
            event=db.decode(payload);stats=event['after']['summary']
            entries.append(dict(id=event['batch_id'],name=name,created_at=created.isoformat(),actor=actor,
                                added=stats.get('ready',0),excluded=stats.get('excluded',0),duplicates=stats.get('duplicates_skipped',0)))
        cursor.execute("SELECT PAYLOAD FROM MDRRMC_HISTORY WHERE ACTION='dataset reversed'")
        reversed_ids={db.decode(p)['batch_id'] for p, in cursor}
        for entry in entries:entry['reversed']=entry['id'] in reversed_ids
        return dict(imports=entries,page=page,total=total,page_size=20)


def receipt(cursor,batch):
    cursor.execute("SELECT PAYLOAD FROM MDRRMC_HISTORY WHERE ACTION='dataset imported' AND JSON_VALUE(PAYLOAD,'$.batch_id')=:b",b=batch)
    found=cursor.fetchone()
    if not found:raise ValueError('This import could not be found.')
    event=db.decode(found[0])
    cursor.execute('SELECT SOURCE_NAME,ORIGINAL_FILE FROM MDRRMC_BATCHES WHERE BATCH_ID=:b',b=batch)
    name,blob=cursor.fetchone()
    return event,name,blob.read() if hasattr(blob,'read') else blob


def excluded_rows(batch):
    from services import upload_service
    with storage.connect() as connection,connection.cursor() as cursor:
        event,name,raw=receipt(cursor,batch)
    entries=event['after'].get('excluded',[])
    if any('original' not in e for e in entries) and raw:
        frame=upload_service.parse_upload(name,raw)
        originals={int(i)+1:row for i,row in zip(frame.index,frame.to_dict('records'))}
        entries=[dict(e,original=e.get('original',originals.get(e['row'],{}))) for e in entries]
    return [dict(row=e['row'],reason=e['reason'],original=e.get('original',{}),cleaned={'needs_manual_review':e.get('needs_manual_review',True)}) for e in entries]


def reverse(batch,actor):
    from arm.pipeline import pipeline,ARMPipeline
    with pipeline._write_lock:
        with db.transaction() as cursor:
            receipt(cursor,batch)
            cursor.execute("SELECT COUNT(*) FROM MDRRMC_HISTORY WHERE ACTION='dataset reversed' AND JSON_VALUE(PAYLOAD,'$.batch_id')=:b",b=batch)
            if cursor.fetchone()[0]:raise ValueError('This import has already been undone.')
            cursor.execute("SELECT RECORD_ID,PAYLOAD FROM MDRRMC_HISTORY WHERE ACTION='dataset import' AND JSON_VALUE(PAYLOAD,'$.batch_id')=:b",b=batch)
            originals={rid:db.decode(payload)['after'] for rid,payload in cursor}
            current=db.approved(cursor);by_id={r['record_id']:r for r in current}
            if not originals:raise ValueError('There are no imported records to undo.')
            if any(by_id.get(rid)!=original for rid,original in originals.items()):
                raise ValueError('Some records have changed since this import. Undo is blocked to protect those changes.')
            if any(d.get('target_id') in originals for d in db.drafts(cursor)):
                raise ValueError('A record from this import has a pending edit. Finish that edit before undoing.')
            remaining=[r for r in current if r['record_id'] not in originals]
            if not remaining:raise ValueError('Undo would leave no records for analysis. Contact the administrator.')
            for rid,original in originals.items():
                cursor.execute('DELETE FROM MDRRMC_RECORDS WHERE RECORD_ID=:i',i=rid)
                db.history(cursor,rid,actor,'import record reversed',original,None,batch_id=batch)
            candidate=ARMPipeline();candidate.data=pd.DataFrame(remaining);candidate._coerce_types(candidate.data);candidate._staging=True;candidate.run(force=True)
            db.history(cursor,None,actor,'dataset reversed',None,dict(removed=len(originals)),batch_id=batch)
            cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
        pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta=candidate.data,candidate.rules,candidate.itemsets,candidate.meta
    return dict(removed=len(originals),total=len(remaining))
