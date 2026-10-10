"""Shared preprocessing, durable review and atomic approval."""
import json
import re
import uuid
from datetime import datetime, timezone
import pandas as pd
from services import review_store as db, upload_service as upload, storage_service as storage

VERSION='dataset-v3'
SEVERITIES=('Fatal','Non-Fatal','Damage-to-Property')
class Conflict(ValueError): pass

def suggest_severity(description):
    from services.incoming_pipeline import severity
    label,uncertain=severity(description)
    return (None,'Outcome needs confirmation.') if uncertain else (label,'Suggested from the injury / damage description.')


def clean(raw, order, verified=False):
    from services import incoming_pipeline
    cleaned, report, engineering=incoming_pipeline.run(pd.DataFrame([raw]),order=order,verified_severity=verified)
    if cleaned.empty:raise ValueError('Enter at least the date and record details.')
    row=json.loads(cleaned.to_json(orient='records'))[0]
    issues=[i['message'] for i in report['issues'] if 'injury text is not automatically classified' not in i['message']]
    suggestion, _=incoming_pipeline.severity(raw.get('damage_injury'))
    suggestion=None if suggestion=='Unknown' else suggestion
    if row.get('review_notes'):issues.append(row['review_notes'])
    if row.get('validation_notes'):issues.append(row['validation_notes'])
    row.pop('_source_row',None)
    row.pop('record_revision',None)
    supplied=row.pop('record_id',None)
    if supplied:row['source_record_id']=supplied
    return row, issues, report['error_count']>0 or bool(row.get('validation_notes')), report['changes'], suggestion

def content_fingerprint(row):
    return storage.fingerprint({k:v for k,v in row.items() if k!='record_id'})

def event_key(row):
    date=upload.date_value(row.get('date'),'month_first')
    hour,minute=upload.time_value(row.get('time'),row.get('hour'),row.get('minute'))
    barangay=upload.normalize_category('barangay',row.get('barangay'))
    if pd.isna(date) or hour is None or barangay=='Unknown':return None
    return (date.strftime('%Y-%m-%d'),hour,minute,barangay)

class RecordIndex:
    """Index approved records once per request, rather than scan for each row."""
    def __init__(self, records):
        from collections import defaultdict
        self.records={r['record_id']:r for r in records}
        self.exact=defaultdict(set);self.source=defaultdict(set);self.event=defaultdict(set)
        for row in records:self.add(row)
    def add(self,row):
        rid=row['record_id'];self.records[rid]=row
        self.exact[content_fingerprint(row)].add(rid)
        if row.get('source_record_id'):self.source[str(row['source_record_id'])].add(rid)
        event=event_key(row)
        if event:self.event[event].add(rid)
    def __iter__(self):return iter(self.records.values())

def candidate_records(row, records, target=None):
    index=records if isinstance(records,RecordIndex) else RecordIndex(records)
    exact=index.exact.get(content_fingerprint(row),set())
    source=index.source.get(str(row.get('source_record_id')),set()) if row.get('source_record_id') else set()
    event=index.event.get(event_key(row),set())
    ids=(exact|source|event)-{target}
    return [dict(record=index.records[rid],reason='Matching source ID' if rid in source else 'Matching record values' if rid in exact else 'Same date, time and barangay') for rid in sorted(ids)]

def classify(draft, records):
    if draft['status']!='pending':return draft['status']
    if draft.get('decision')=='skip':return 'skip'
    if draft['blocked'] or draft['cleaned'].get('severity') not in SEVERITIES: return 'needs_review'
    target=draft.get('target_id')
    current=next((r for r in records if r['record_id']==target),None)
    if target and (not current or current['record_revision']!=draft.get('target_revision')):return 'conflict'
    matches=candidate_records(draft['cleaned'],records,target)
    if matches and draft.get('decision') not in ('separate','update'):return 'duplicate'
    return 'ready' if draft.get('reviewed') else 'needs_review'

def enrich(draft, records):
    d=dict(draft)
    d['state']=classify(d,records)
    d['duplicates']=candidate_records(d['cleaned'],records,d.get('target_id'))
    d['existing']=next((r for r in records if r['record_id']==d.get('target_id')),None)
    return d

def create_batch(frame, name, actor, order='month_first', mapping=None, drops=None, original=None, target=None, target_revision=None):
    if not 0<len(frame)<=100000:raise ValueError('Use between 1 and 100,000 rows.')
    mapped=upload.schema_service.apply(frame,mapping,drops)
    if 'date' not in mapped:raise ValueError('Match a column to Date of crash.')
    raw_rows=json.loads(mapped.to_json(orient='records',date_format='iso'))
    batch=uuid.uuid4().hex
    with db.transaction() as cursor:
        records=db.approved(cursor)
        current=next((r for r in records if r['record_id']==target),None)
        if target and not current:raise ValueError('Record not found.')
        if target_revision is not None and current['record_revision']!=target_revision:raise Conflict('The record changed. Reopen its details before editing.')
        import oracledb
        cursor.setinputsizes(file_data=oracledb.DB_TYPE_BLOB)
        cursor.execute('INSERT INTO MDRRMC_BATCHES (BATCH_ID,SOURCE_NAME,ORIGINAL_FILE,CREATED_BY) VALUES (:b,:n,:file_data,:a)',b=batch,n=name[:512],file_data=original,a=actor)
        for raw in raw_rows:
            # Preserve source values separately from every cleaned/editable version.
            row,issues,blocked,changes,suggestion=clean(raw,order)
            d=dict(id=uuid.uuid4().hex,batch_id=batch,status='pending',revision=1,original=raw,raw=raw,cleaned=row,issues=issues,blocked=blocked,changes=changes,suggestion=suggestion,date_order=order,reviewed=False,decision='update' if target else None,target_id=target,target_revision=current['record_revision'] if current else None,source_file=name,preprocessing_version=VERSION)
            db.save_draft(cursor,d,new=True)
        db.history(cursor,None,actor,'batch created',None,dict(batch_id=batch,rows=len(raw_rows),source=name))
    return batch

def list_batches():
    with storage.connect() as connection,connection.cursor() as cursor:
        cursor.execute("SELECT b.BATCH_ID,b.SOURCE_NAME,b.CREATED_AT,COUNT(d.DRAFT_ID),SUM(CASE WHEN d.STATUS='pending' THEN 1 ELSE 0 END) FROM MDRRMC_BATCHES b LEFT JOIN MDRRMC_DRAFTS d ON d.BATCH_ID=b.BATCH_ID GROUP BY b.BATCH_ID,b.SOURCE_NAME,b.CREATED_AT ORDER BY b.CREATED_AT DESC")
        return [dict(id=i,source=n,created_at=t.isoformat(),total=int(count),pending=int(p or 0)) for i,n,t,count,p in cursor]

def get_batch(batch, page=None, state='pending'):
    from collections import Counter
    with storage.connect() as connection,connection.cursor() as cursor:
        records=RecordIndex(db.approved(cursor))
        source=db.drafts(cursor,batch)
        if page is None:return [enrich(d,records) for d in source]
        classified=[(d,classify(d,records)) for d in source]
        counts=dict(Counter(s for _,s in classified))
        counts['pending']=sum(d['status']=='pending' for d in source)
        visible=[d for d,s in classified if state=='all' or state=='pending' and d['status']=='pending' or s==state]
        total=len(visible);page=max(1,min(page,max(1,(total+24)//25)))
        return dict(rows=[enrich(d,records) for d in visible[(page-1)*25:page*25]],page=page,total=total,page_size=25,counts=counts)

def update_draft(batch, ident, body, actor):
    with db.transaction() as cursor:
        draft=next((d for d in db.drafts(cursor,batch) if d['id']==ident),None)
        if not draft or draft['status']!='pending':raise Conflict('This row is no longer pending.')
        if body.get('revision')!=draft['revision']:raise Conflict('This row changed. Reload it before editing.')
        before=dict(draft)
        raw=body.get('raw',draft['raw'])
        if not isinstance(raw,dict) or any(isinstance(v,(dict,list)) for v in raw.values()):raise ValueError('Use plain field values.')
        draft['raw']=raw
        row,issues,blocked,changes,suggestion=clean(raw,draft['date_order'],verified=body.get('reviewed') is True)
        draft.update(cleaned=row,issues=issues,blocked=blocked,changes=changes,suggestion=suggestion,reviewed=body.get('reviewed') is True and raw.get('severity') in SEVERITIES)
        decision=body.get('decision') or None
        if decision not in (None,'skip','separate','update'):raise ValueError('Choose a valid duplicate decision.')
        records=db.approved(cursor)
        if decision=='update':
            target=body.get('target_id') or draft.get('target_id')
            other=next((r for r in records if r['record_id']==target),None)
            if not other:raise ValueError('Choose the existing record to update.')
            expected=body.get('target_revision',draft.get('target_revision'))
            if expected!=other['record_revision']:raise Conflict('The existing record changed. Reload the comparison.')
            draft.update(target_id=target,target_revision=expected)
        else:draft.update(target_id=None,target_revision=None)
        draft.update(decision=decision,revision=draft['revision']+1)
        db.save_draft(cursor,draft)
        db.history(cursor,draft.get('target_id'),actor,'draft reviewed',before,draft,batch_id=batch)
        return enrich(draft,RecordIndex(records))

def approve(batch, actor):
    from arm.pipeline import pipeline, ARMPipeline
    added=updated=skipped=0
    with pipeline._write_lock:
        with db.transaction() as cursor:
            records=db.approved(cursor)
            drafts=db.drafts(cursor,batch)
            index=RecordIndex(records)
            for d in drafts:
                if d['status']!='pending':continue
                state=classify(d,index)
                if state=='skip':
                    d['status']='skipped';skipped+=1
                elif state=='ready':
                    previous=next((r for r in records if r['record_id']==d.get('target_id')),None)
                    rid=previous['record_id'] if previous else uuid.uuid4().hex
                    row=dict(d['cleaned'],record_id=rid,record_revision=previous['record_revision']+1 if previous else 1,source_file=d['source_file'],imported_at=datetime.now(timezone.utc).isoformat(),preprocessing_version=VERSION,needs_manual_review=False,review_notes='')
                    if previous and previous.get('accident_id'):row['accident_id']=previous['accident_id']
                    db.save_record(cursor,row,previous)
                    db.history(cursor,rid,actor,'update approved' if previous else 'record approved',previous,row,batch_id=batch,draft_id=d['id'])
                    records=[r for r in records if r['record_id']!=rid]+[row]
                    index=RecordIndex(records) if previous else index
                    if not previous:index.add(row)
                    if previous:updated+=1
                    else:added+=1
                    d['status']='approved'
                else:continue
                d['revision']+=1
                db.save_draft(cursor,d)
            candidate=ARMPipeline();candidate.data=pd.DataFrame(records);candidate._coerce_types(candidate.data);candidate._staging=True
            candidate.run(force=True)
            cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
        # Publish only after the transaction, including mining, committed successfully.
        pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta=candidate.data,candidate.rules,candidate.itemsets,candidate.meta
    return dict(added=added,updated=updated,skipped=skipped,pending=sum(d['status']=='pending' for d in drafts),total=len(records))
