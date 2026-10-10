"""Session-owned dataset previews and one-click imports."""
import csv
import io
import secrets
import time
import uuid
from flask import Blueprint, jsonify, request, session, current_app, Response
from services import dataset_service as dataset, review_store as db, upload_service as upload

dataset_bp=Blueprint('dataset',__name__)

@dataset_bp.errorhandler(ValueError)
def invalid(error):return jsonify(error=str(error)),400

def source_for(body):
    from routes.api import _sources, _pending_lock
    token=body.get('source_token')
    if not isinstance(token,str):raise ValueError('Choose a file first.')
    with _pending_lock:source=_sources.get(token)
    if not source or source['owner']!=session.get('upload_owner') or source['expires']<time.time():raise ValueError('This preview expired. Choose your file again.')
    return source

def prepared_for(body):
    source=source_for(body);prepared=source.get('dataset')
    if not prepared or body.get('preview_token')!=prepared['token']:raise ValueError('The preview changed. Prepare the file again before adding it.')
    return source,prepared

@dataset_bp.post('/api/dataset/prepare')
def prepare():
    from routes.api import _pending_lock
    body=request.get_json(silent=True) or {};source=source_for(body)
    with _pending_lock:
        if source.get('importing'):raise ValueError('This dataset is being added. Please wait.')
        source.pop('dataset',None)
    frame=source['frame']
    if body.get('sheet_name') and source['raw'] is not None:frame=upload.parse_upload(source['filename'],source['raw'],body['sheet_name'])
    try:
        prepared=dataset.prepare(frame,body.get('mapping'),body.get('drop_columns'),body.get('date_order','auto'))
        prepared['plan']=dataset.assess(prepared,db.rows())
    except ValueError as error:
        prepared=dataset.preview_only(frame,str(error))
    prepared['token']=secrets.token_urlsafe(32);prepared['batch_id']=uuid.uuid4().hex
    with _pending_lock:source['dataset']=prepared
    return jsonify(preview_token=prepared['token'],stats=prepared['plan']['stats'],preparation_error=prepared.get('preparation_error'),fields=upload.schema_service.FIELDS)

@dataset_bp.post('/api/dataset/rows')
def rows():
    body=request.get_json(silent=True) or {};source,prepared=prepared_for(body)
    size=int(body.get('page_size',10));page=max(1,int(body.get('page',1)))
    if size not in (10,25,50,100):raise ValueError('Choose 10, 25, 50 or 100 entries.')
    if body.get('view')=='original':
        records=prepared['raw'];columns=prepared['raw_columns']
    else:
        records=[dict(e['cleaned'],_result=e['status'],_reason=e['reason']) for e in prepared['plan']['items']]
        columns=list(dict.fromkeys(['_result']+[k for r in records for k in r if k not in ('_result','_reason')]+['_reason']))
    query=str(body.get('search','')).strip().casefold()
    if query:records=[r for r in records if any(query in str(v if v is not None else '').casefold() for v in r.values())]
    total=len(records);page=min(page,max(1,(total+size-1)//size))
    return jsonify(rows=records[(page-1)*size:page*size],columns=columns,page=page,page_size=size,total=total)

@dataset_bp.post('/api/dataset/excluded')
def excluded():
    body=request.get_json(silent=True) or {};source,prepared=prepared_for(body)
    entries=[e for e in prepared['plan']['items'] if e['status']!='Ready']
    return excluded_response(entries)


def excluded_response(entries):
    columns=list(dict.fromkeys(['File row','Reason','Needs manual review']+[k for e in entries for k in e['original']]))
    output=io.StringIO();writer=csv.DictWriter(output,fieldnames=columns);writer.writeheader()
    def safe(v):
        text='' if v is None else str(v)
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    for e in entries:writer.writerow({k:safe(v) for k,v in dict(e['original'],**{'File row':e['row'],'Reason':e['reason'],'Needs manual review':e['cleaned'].get('needs_manual_review',True)}).items()})
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="excluded-records.csv"'})

@dataset_bp.post('/api/dataset/import')
def import_dataset():
    from routes.api import _pending_lock
    body=request.get_json(silent=True) or {};source,prepared=prepared_for(body)
    with _pending_lock:
        if prepared.get('result'):return jsonify(prepared['result'])
        if source.get('importing'):return jsonify(error='This dataset is already being added. Please wait.'),409
        source['importing']=True
    try:
        result=dataset.publish(prepared,source['filename'],source['raw'],current_app.config['LOGIN_USERNAME'],prepared['batch_id'])
        prepared['plan']=dict(items=result.pop('items'),stats=result['stats']);prepared['result']=result
        return jsonify(result)
    except ValueError:raise
    except Exception:
        current_app.logger.exception('Dataset import failed; transaction rolled back')
        return jsonify(error='The dataset could not be added. No partial import was saved. Please try again.'),503
    finally:
        with _pending_lock:source['importing']=False

@dataset_bp.post('/api/dataset/manual')
def manual():
    import pandas as pd
    body=request.get_json(silent=True) or {};record=body.get('record')
    if not isinstance(record,dict) or any(isinstance(v,(dict,list)) for v in record.values()):raise ValueError('Enter the accident details.')
    prepared=dataset.prepare(pd.DataFrame([record]),verified_severity=body.get('outcome_verified') is True)
    if prepared['items'][0]['reason']:raise ValueError(prepared['items'][0]['reason'])
    result=dataset.publish(prepared,'Manual entry',None,current_app.config['LOGIN_USERNAME'],uuid.uuid4().hex)
    result.pop('items');return jsonify(result)

@dataset_bp.post('/api/dataset/inspect')
def inspect():
    from routes.api import _sources, _pending_lock
    file=request.files.get('file')
    if not file or not file.filename:raise ValueError('Choose a CSV, TSV or XLSX file.')
    raw=file.read();frame=upload.parse_upload(file.filename,raw)
    session.setdefault('upload_owner',secrets.token_urlsafe(24))
    token=secrets.token_urlsafe(32)
    with _pending_lock:
        for key in list(_sources):
            if _sources[key]['expires']<time.time() and not _sources[key].get('importing'):_sources.pop(key)
        if len(_sources)>=8:raise ValueError('Uploads are busy. Please try again shortly.')
        _sources[token]=dict(owner=session['upload_owner'],expires=time.time()+1800,frame=frame,filename=file.filename,raw=raw)
    return jsonify(source_token=token,fields=upload.schema_service.FIELDS,sheet_names=frame.attrs.get('sheet_names',[]),selected_sheet=frame.attrs.get('selected_sheet'))


@dataset_bp.get('/api/dataset/history')
def history():
    from services import import_history
    return jsonify(import_history.list_imports(int(request.args.get('page',1))))


@dataset_bp.get('/api/dataset/history/<batch>/excluded')
def history_excluded(batch):
    from services import import_history
    return excluded_response(import_history.excluded_rows(batch))


@dataset_bp.get('/api/dataset/history/<batch>/original')
def history_original(batch):
    from services import import_history,storage_service
    from flask import send_file
    from pathlib import PureWindowsPath
    with storage_service.connect() as connection,connection.cursor() as cursor:
        _,name,raw=import_history.receipt(cursor,batch)
    if raw is None:raise ValueError('This record was entered manually; there is no source file.')
    return send_file(io.BytesIO(raw),as_attachment=True,download_name=PureWindowsPath(name).name)


@dataset_bp.post('/api/dataset/history/<batch>/undo')
def undo_import(batch):
    from services import import_history
    if (request.get_json(silent=True) or {}).get('confirm') is not True:raise ValueError('Confirm which import to undo.')
    return jsonify(import_history.reverse(batch,current_app.config['LOGIN_USERNAME']))


@dataset_bp.post('/api/dataset/records/<ident>')
def update_record(ident):
    body=request.get_json(silent=True) or {};record=body.get('record')
    if not isinstance(record,dict) or any(isinstance(v,(dict,list)) for v in record.values()):raise ValueError('Enter the accident details.')
    return jsonify(dataset.update_record(ident,record,body.get('revision'),current_app.config['LOGIN_USERNAME'],body.get('outcome_verified') is True))
