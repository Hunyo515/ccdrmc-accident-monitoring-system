"""Dataset-level preparation and atomic publication; no per-row approval queue."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
import pandas as pd
from services import upload_service as upload, review_service as review, review_store as db

META={'record_id','record_revision','needs_manual_review','review_notes','source_file','imported_at','preprocessing_version','_source_row','year','month','day','hour','minute','accident_id','latitude_imputed','longitude_imputed','exported_accident_id'}
META.update({'source_fingerprint','estimated_fields','validation_notes','derived_severity','supplied_severity'})

def fingerprint(row):
    # Include additional information and casualty identifiers, not just incident details.
    values={}
    for k,v in row.items():
        if k in str(row.get('estimated_fields','')).split(', '):continue
        if k in ('latitude','longitude') and str(row.get(k+'_imputed','')).lower() in ('true','1'):continue
        if k=='source_accident_id' and re.fullmatch(r'ACC-\d+',str(v)):continue
        if k in META or k in {'extra_'+name for name in META} or (k=='time_period' and upload.text(row.get('time'))):continue
        text=upload.text(v).strip()
        if text.casefold() in ('','unknown','n/a','na','none','nan','null','not specified','-'):continue
        if k=='date':
            date=upload.date_value(text,'month_first')
            if not pd.isna(date):text=date.strftime('%Y-%m-%d')
        elif k in ('barangay','vehicle_involved','collision_type','cause'):text=upload.normalize_category(k,text)
        elif k=='time':
            h,m=upload.time_value(text,None,None)
            if h is not None:text=f'{h:02}:{m:02}:00'
        elif k in ('latitude','longitude'):
            try:text=str(float(text))
            except ValueError:pass
        values[k]=text
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

def prepare(frame, mapping=None, drops=None, order='auto', verified_severity=False):
    from services import incoming_pipeline
    if not 0<len(frame)<=100000:raise ValueError('Use a file containing 1 to 100,000 rows.')
    cleaned,report,engineering=incoming_pipeline.run(frame,mapping,drops,order,verified_severity)
    invalid_rows=set(report['invalid_rows'])
    originals=json.loads(frame.to_json(orient='records',date_format='iso'))
    original_by_row={(int(index)+1 if frame.attrs.get('source_row_numbers') else position):originals[position-2] for position,index in enumerate(frame.index,start=2)}
    result=[];suggested=0
    for row in json.loads(cleaned.to_json(orient='records')):
        source_row=row.pop('_source_row')
        suggested+=int(row.get('severity') in review.SEVERITIES)
        problem=[]
        if source_row in invalid_rows:
            problem.append('Invalid date or time')
        if row.get('needs_manual_review') or row.get('severity') not in review.SEVERITIES:problem.append(row.get('review_notes') or 'Severity cannot be determined from the supplied information')
        if row.get('validation_notes'):problem.append(row['validation_notes'])
        supplied=row.pop('record_id',None)
        row.pop('record_revision',None)
        if supplied:row['source_record_id']=supplied
        result.append(dict(row=source_row,original=original_by_row.get(source_row,{}),cleaned=row,reason='; '.join(problem)))
    missing=frame.map(incoming_pipeline.missing)
    stats=dict(rows=len(frame),columns=len(frame.columns),missing_values=int(missing.sum().sum()),rows_with_missing=int(missing.any(axis=1).sum()),duplicate_rows=int(frame.fillna('').astype(str).duplicated().sum()),severity_derived=suggested,date_order=order)
    stats['variables']=engineering['variables']
    stats['engineering']=engineering
    stats['manual_review']=sum(bool(e['cleaned'].get('needs_manual_review')) for e in result)
    return dict(items=result,stats=stats,raw=json.loads(frame.to_json(orient='records',date_format='iso')),raw_columns=list(frame.columns))

def assess(prepared, existing, skip_duplicates=True):
    seen={fingerprint(row) for row in existing};by_id={r.get('record_id'):r for r in existing};items=[];ready=duplicate=invalid=0
    sources={r.get('source_fingerprint') for r in existing if r.get('source_fingerprint')}
    for entry in prepared['items']:
        e=dict(entry);key=fingerprint(e['cleaned'])
        original=by_id.get(e['cleaned'].get('source_record_id'))
        exported_duplicate=original is not None and fingerprint({k:v for k,v in e['cleaned'].items() if k not in ('source_record_id','estimated_fields')})==fingerprint({k:v for k,v in original.items() if k not in ('source_record_id','estimated_fields')})
        if e['reason']:e['status']='Excluded';invalid+=1
        elif (key in seen or e['cleaned'].get('source_fingerprint') in sources or exported_duplicate) and skip_duplicates:e.update(status='Duplicate',reason='Exact duplicate after cleaning');duplicate+=1
        else:
            e['status']='Ready';ready+=1;seen.add(key)
            if e['cleaned'].get('source_fingerprint'):sources.add(e['cleaned']['source_fingerprint'])
        items.append(e)
    return dict(items=items,stats=dict(prepared['stats'],ready=ready,duplicates_skipped=duplicate,excluded=invalid))

def publish(prepared, name, original, actor, batch_id, skip_duplicates=True):
    from arm.pipeline import pipeline, ARMPipeline
    if prepared['stats'].get('engineering',{}).get('date_choice_required'):raise ValueError('Choose the date format for this file before adding records.')
    with pipeline._write_lock:
        with db.transaction() as cursor:
            existing=db.approved(cursor)
            plan=assess(prepared,existing,skip_duplicates)
            good=[e for e in plan['items'] if e['status']=='Ready']
            if not good:raise ValueError('There are no new valid records to add. Download the excluded rows for details.')
            import oracledb
            cursor.setinputsizes(file_data=oracledb.DB_TYPE_BLOB)
            cursor.execute('INSERT INTO MDRRMC_BATCHES (BATCH_ID,SOURCE_NAME,ORIGINAL_FILE,CREATED_BY) VALUES (:b,:n,:file_data,:a)',b=batch_id,n=name[:512],file_data=original,a=actor)
            now=datetime.now(timezone.utc).isoformat()
            cursor.execute('SELECT REVISION FROM MDRRMC_STATE WHERE STATE_ID=2')
            counter=cursor.fetchone()
            prior=max([int(m[1]) for r in existing if (m:=re.fullmatch(r'ACC-(\d+)',str(r.get('accident_id',''))))]+[int(counter[0]) if counter else 0])
            if counter is None:cursor.execute('INSERT INTO MDRRMC_STATE (STATE_ID,REVISION) VALUES (2,:v)',v=prior)
            added=[]
            for position,entry in enumerate(good,start=1):
                from services.incoming_pipeline import VERSION
                row=dict(entry['cleaned'],accident_id=f'ACC-{prior+position:06d}',record_id=uuid.uuid4().hex,record_revision=1,source_file=name,imported_at=now,preprocessing_version=VERSION)
                db.save_record(cursor,row)
                db.history(cursor,row['record_id'],actor,'dataset import',None,row,batch_id=batch_id,source_row=entry['row'])
                added.append(row)
            cursor.execute('UPDATE MDRRMC_STATE SET REVISION=:v WHERE STATE_ID=2',v=prior+len(added))
            db.history(cursor,None,actor,'dataset imported',None,dict(summary=plan['stats'],excluded=[dict(row=e['row'],reason=e['reason'],original=e['original'],needs_manual_review=e['cleaned'].get('needs_manual_review',False)) for e in plan['items'] if e['status']!='Ready']),batch_id=batch_id)
            candidate=ARMPipeline();candidate.data=pd.DataFrame(existing+added);candidate._coerce_types(candidate.data);candidate._staging=True;candidate.run(force=True)
            cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
        pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta=candidate.data,candidate.rules,candidate.itemsets,candidate.meta
    return dict(added=len(added),total=len(existing)+len(added),stats=plan['stats'],items=plan['items'])


def preview_only(frame, reason):
    """Keep a searchable original preview when automatic preparation is blocked."""
    raw=json.loads(frame.to_json(orient='records',date_format='iso'))
    from services.incoming_pipeline import missing as is_missing
    missing=frame.map(is_missing)
    stats=dict(rows=len(frame),columns=len(frame.columns),missing_values=int(missing.sum().sum()),rows_with_missing=int(missing.any(axis=1).sum()),duplicate_rows=int(frame.fillna('').astype(str).duplicated().sum()),severity_derived=0,date_order='auto',ready=0,duplicates_skipped=0,excluded=len(frame),variables=[dict(name=str(c),missing=int(missing[c].sum()),unique=int(frame.loc[~missing[c],c].astype(str).nunique())) for c in frame.columns])
    items=[dict(row=int(index)+1 if frame.attrs.get('source_row_numbers') else position,original=raw[position-2],cleaned=raw[position-2],status='Excluded',reason=reason) for position,index in enumerate(frame.index,start=2)]
    return dict(raw=raw,raw_columns=list(frame.columns),items=items,stats=stats,plan=dict(items=items,stats=stats),preparation_error=reason)


def update_record(ident,values,revision,actor,verified=False):
    """Validate and save an explicit edit with optimistic locking and the upload pipeline."""
    from arm.pipeline import pipeline,ARMPipeline
    from services.incoming_pipeline import VERSION,DERIVED
    with pipeline._write_lock:
        with db.transaction() as cursor:
            existing=db.approved(cursor);previous=next((r for r in existing if r['record_id']==ident),None)
            if not previous:raise ValueError('Record not found.')
            if previous['record_revision']!=revision:raise review.Conflict('This record changed. Reopen it before saving.')
            editable={k:v for k,v in previous.items() if k not in META|DERIVED and not k.endswith('_imputed')}
            editable.update({k:v for k,v in values.items() if k not in META|DERIVED and not k.endswith('_imputed')})
            estimated=set(str(previous.get('estimated_fields','')).split(', '))
            estimated.update(k for k in ('latitude','longitude') if previous.get(k+'_imputed') is True)
            for key in estimated:
                if key and str(editable.get(key,''))==str(previous.get(key,'')):editable[key]=None
            prepared=prepare(pd.DataFrame([editable]),verified_severity=verified)
            entry=prepared['items'][0]
            if entry['reason']:raise ValueError(entry['reason'])
            others=[r for r in existing if r['record_id']!=ident]
            if assess(prepared,others)['stats']['duplicates_skipped']:raise ValueError('These values exactly match another record. No change was saved.')
            record=dict(entry['cleaned'],record_id=ident,record_revision=revision+1,source_file=previous.get('source_file'),imported_at=previous.get('imported_at'),preprocessing_version=VERSION)
            if previous.get('accident_id'):record['accident_id']=previous['accident_id']
            db.save_record(cursor,record,previous)
            db.history(cursor,ident,actor,'record edited',previous,record)
            candidate=ARMPipeline();candidate.data=pd.DataFrame(others+[record]);candidate._coerce_types(candidate.data);candidate._staging=True;candidate.run(force=True)
            cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
        pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta=candidate.data,candidate.rules,candidate.itemsets,candidate.meta
    return dict(record=record,total=len(existing))
