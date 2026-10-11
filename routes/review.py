"""Authenticated Oracle workflow endpoints."""
from flask import Blueprint, request, jsonify, current_app, render_template, redirect, url_for
import pandas as pd
from services import review_service as review, review_store as db, storage_service as store, upload_service as upload

review_bp=Blueprint('review',__name__)

def actor():return current_app.config['LOGIN_USERNAME']

@review_bp.errorhandler(review.Conflict)
def conflict(error):return jsonify(error=str(error)),409

@review_bp.errorhandler(ValueError)
def invalid(error):return jsonify(error=str(error)),400

@review_bp.get('/review/<batch>')
def page(batch):
    from routes.views import _ctx
    return render_template('review.html',batch_id=batch,**_ctx('data'))

@review_bp.get('/api/review/batches')
def batches():return jsonify(batches=review.list_batches())

@review_bp.get('/api/review/<batch>')
def batch_rows(batch):
    result=review.get_batch(batch,page=int(request.args.get('page',1)),state=request.args.get('state','pending'))
    return jsonify(**result,fields=upload.schema_service.FIELDS)

@review_bp.post('/api/review/<batch>/<ident>')
def edit_draft(batch,ident):
    return jsonify(review.update_draft(batch,ident,request.get_json(silent=True) or {},actor()))

@review_bp.post('/api/review/<batch>/approve')
def approve(batch):
    if (request.get_json(silent=True) or {}).get('approved') is not True:raise ValueError('Confirm approval first.')
    try:return jsonify(review.approve(batch,actor()))
    except (ValueError, review.Conflict):raise
    except Exception:
        current_app.logger.exception('Approval failed; transaction rolled back')
        return jsonify(error='Approval could not finish. Refresh the review queue and try again; pending records have not been published.'),503

@review_bp.post('/api/review/stage-upload')
def stage_upload():
    from routes.api import _sources, _pending_lock
    from flask import session
    import time
    body=request.get_json(silent=True) or {}
    with _pending_lock:
        source=_sources.get(body.get('source_token',''))
    if not source or source['owner']!=session.get('upload_owner') or source['expires']<time.time():raise review.Conflict('Choose the file again; this preview expired.')
    order=body.get('date_order','month_first')
    if order=='auto':raise ValueError('Choose month/day/year or day/month/year before saving for review.')
    frame=source['frame']
    if body.get('sheet_name') and source['raw'] is not None:
        frame=upload.parse_upload(source['filename'],source['raw'],body['sheet_name'])
    batch=review.create_batch(frame,source['filename'],actor(),order,body.get('mapping'),body.get('drop_columns'),source['raw'])
    with _pending_lock:_sources.pop(body['source_token'],None)
    return jsonify(batch_id=batch,url=url_for('review.page',batch=batch))

@review_bp.post('/api/review/manual')
def manual():
    body=request.get_json(silent=True) or {}
    raw=body.get('record')
    if not isinstance(raw,dict):raise ValueError('Enter a record.')
    batch=review.create_batch(pd.DataFrame([raw]),'Manual entry',actor())
    return jsonify(batch_id=batch,url=url_for('review.page',batch=batch))

@review_bp.get('/api/records/<ident>')
def record(ident):
    with store.connect() as conn,conn.cursor() as cursor:
        row=next((r for r in db.approved(cursor) if r['record_id']==ident),None)
        if not row:return jsonify(error='Record not found.'),404
        cursor.execute('SELECT ACTOR,ACTION,PAYLOAD,CREATED_AT FROM MDRRMC_HISTORY WHERE RECORD_ID=:i ORDER BY CREATED_AT DESC',i=ident)
        events=[dict(actor=a,action=b,detail=db.decode(p),created_at=t.isoformat()) for a,b,p,t in cursor]
    return jsonify(record=row,history=events)

@review_bp.post('/api/records/<ident>/edit')
def propose_edit(ident):
    rows=store.load().to_dict('records')
    row=next((r for r in rows if r['record_id']==ident),None)
    if not row:return jsonify(error='Record not found.'),404
    # Store JSON-safe values and keep external IDs separate from internal IDs.
    from services.report_service import records
    row=records(pd.DataFrame([row]))[0]
    revision=row['record_revision']
    for key in ('record_id','record_revision','needs_manual_review','review_notes','preprocessing_version','imported_at','source_file'):row.pop(key,None)
    batch=review.create_batch(pd.DataFrame([row]),'Edit approved record',actor(),target=ident,target_revision=revision)
    return jsonify(batch_id=batch,url=url_for('review.page',batch=batch))


def report_selection():
    from arm.pipeline import pipeline
    from routes.api import _overview_filters_from_args
    from services import report_service
    frame,_,meta=pipeline.snapshot()
    filters=_overview_filters_from_args(request.args)
    search=request.args.get('search','').strip()
    if filters.get('date_from') and filters.get('date_to') and filters['date_from']>filters['date_to']:
        raise ValueError('The start date must not follow the end date.')
    return report_service.filtered_data(frame,filters,search),dict(filters,search=search),meta

@review_bp.get('/api/export/data.xlsx')
def excel_report():
    from flask import Response
    from services.document_reports import export_records
    frame,filters,_=report_selection()
    return Response(export_records(frame,filters),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="mdrrmc-records.xlsx"'})

@review_bp.get('/api/export/analysis.pdf')
def pdf_report():
    from flask import Response
    from services.document_reports import analysis_pdf
    frame,filters,meta=report_selection()
    return Response(analysis_pdf(frame,filters,meta.get('dataset_revision','')),mimetype='application/pdf',headers={'Content-Disposition':'attachment; filename="road-accident-analysis-report.pdf"'})
