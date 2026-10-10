from flask import Blueprint, jsonify, request, session, current_app
import json
import math
import secrets
import time
import threading
from services import storage_service, schema_service

from arm.pipeline import pipeline
from services import (
    overview_service, rules_service, map_service, upload_service, prescription_service,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(ValueError)
def invalid_request(error):
    return jsonify(error=str(error)),400

CONDITION_FIELDS = ["vehicle_involved", "collision_type", "cause", "barangay", "time_period", "day"]
OVERVIEW_FILTER_FIELDS = ["barangay", "collision_type", "cause"]


def _overview_filters_from_args(args) -> dict:
    filters = {k: args.get(k) or None for k in OVERVIEW_FILTER_FIELDS}
    year_from = args.get("year_from", "")
    year_to = args.get("year_to", "")
    filters["year_from"] = int(year_from) if year_from.isdigit() else None
    filters["year_to"] = int(year_to) if year_to.isdigit() else None
    for key in ('date_from','date_to','severity'):
        if args.get(key): filters[key]=args[key]
    return filters


@api_bp.get("/meta")
def meta():
    return jsonify(pipeline.meta)


@api_bp.get("/overview")
def overview():
    filters = _overview_filters_from_args(request.args)
    return jsonify(overview_service.build_overview(pipeline.data, filters))


@api_bp.get("/overview/years")
def overview_years():
    return jsonify(overview_service.available_years(pipeline.data))


@api_bp.get("/overview/monthly-comparison")
def overview_monthly_comparison():
    filters = _overview_filters_from_args(request.args)
    return jsonify(overview_service.build_monthly_comparison(pipeline.data, filters))


@api_bp.get("/overview/barangay-breakdown")
def overview_barangay_breakdown():
    filters = _overview_filters_from_args(request.args)
    return jsonify(overview_service.build_barangay_breakdown(pipeline.data, filters))


@api_bp.get("/filters")
def filters():
    df = pipeline.data
    options = {field: sorted(df[field].dropna().unique().tolist()) for field in CONDITION_FIELDS}
    return jsonify(options)


def _public_rule(rule: dict, hits: list[dict]) -> dict:
    """A rule as the browser sees it: no internal item list, plus its actions."""
    out = {k: v for k, v in rule.items() if k not in ("items", "antecedent_items", "consequent_items")}
    out["actions"] = hits
    return out


@api_bp.get("/rules")
def rules():
    try:
        min_support = float(request.args.get("min_support", 0.05))
        min_confidence = float(request.args.get("min_confidence", 0.60))
        min_lift = float(request.args.get("min_lift", 1.2))
        limit = max(1, min(int(request.args.get("limit", 10)), 5000))
        if not (0.05 <= min_support <= 1 and 0 <= min_confidence <= 1 and math.isfinite(min_lift) and min_lift >= 0):
            raise ValueError()
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "numeric query params must be numbers"}), 400

    search = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "lift")
    order = request.args.get("order", "desc")
    only_with_actions = request.args.get("only_with_actions", "0") in ("1", "true", "yes")
    cat = prescription_service.get()

    if only_with_actions:
        # Filter first, then page, so page counts reflect what is actually listed.
        everything, _ = rules_service.filter_rules(
            pipeline.rules, min_support, min_confidence, min_lift, search, sort_by, order,
            limit=len(pipeline.rules), offset=0,
        )
        with_hits = [(r, cat.match_rule(r)) for r in everything]
        with_hits = [(r, h) for r, h in with_hits if h]
        total = len(with_hits)
        page = with_hits[offset:offset + limit]
    else:
        rows, total = rules_service.filter_rules(
            pipeline.rules, min_support, min_confidence, min_lift, search, sort_by, order, limit, offset,
        )
        page = [(r, cat.match_rule(r)) for r in rows]

    return jsonify({
        "rules": [_public_rule(r, h) for r, h in page],
        "total": total, "limit": limit, "offset": offset,
    })


def _apply_thresholds():
    min_support = float(request.args.get("min_support", 0.05))
    min_confidence = float(request.args.get("min_confidence", 0.60))
    min_lift = float(request.args.get("min_lift", 1.2))
    if not (0.05 <= min_support <= 1 and 0 <= min_confidence <= 1 and math.isfinite(min_lift) and min_lift >= 0):
        raise ValueError("Invalid thresholds")
    search = request.args.get("search", "")
    filtered, _ = rules_service.filter_rules(
        pipeline.rules, min_support, min_confidence, min_lift, search,
        sort_by="lift", order="desc", limit=len(pipeline.rules), offset=0,
    )
    return filtered


@api_bp.get("/rules/network")
def rules_network():
    try:
        top_n = max(1,min(int(request.args.get("top_n", 20)), 60))
        return jsonify(rules_service.network_data(_apply_thresholds(), top_n))
    except ValueError: return jsonify(error="Use valid numeric filter values."),400


@api_bp.get("/rules/heatmap")
def rules_heatmap():
    try: return jsonify(rules_service.heatmap_data(_apply_thresholds()))
    except ValueError: return jsonify(error="Use valid numeric filter values."),400


@api_bp.get("/rules/actions")
def rules_actions():
    """Recommended actions for every pattern that passes the current thresholds."""
    try:
        filtered = _apply_thresholds()
    except ValueError:
        return jsonify({"error": "numeric query params must be numbers"}), 400
    return jsonify(prescription_service.summarize(prescription_service.get(), filtered))


@api_bp.get("/prescriptions")
def prescriptions_catalog():
    cat = prescription_service.get()
    return jsonify({
        "source": cat.source,
        "total": len(cat.entries),
        "active": len(cat.active),
        "agencies": prescription_service.AGENCIES,
        "prescriptions": cat.public_catalog(),
    })


@api_bp.get("/map")
def map_points():
    year = request.args.get("year", "")
    barangay = request.args.get("barangay", "")
    severity = request.args.get("severity", "")
    points = map_service.get_map_points(pipeline.data, year, barangay, severity)
    return jsonify(points)


@api_bp.get('/map/summary')
def map_summary():
    return jsonify(map_service.map_summary(pipeline.data, **{
        key: request.args.get(key, '') for key in ('year', 'barangay', 'severity')
    }))


@api_bp.post("/admin/refresh")
def admin_refresh():
    meta_info = pipeline.run(force=True)
    return jsonify({"status": "ok", "meta": meta_info})


# Preview tokens are short-lived, tied to this browser session and consumed once.
_pending = {}
_pending_lock = threading.Lock()


def _preview(frame, body):
    mapping = body.get("mapping") or {}
    if isinstance(mapping, str):
        try: mapping = json.loads(mapping)
        except ValueError: raise ValueError('Column mapping must be a JSON object such as {"Crash Date": "date"}.')
    if not isinstance(mapping, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mapping.items()):
        raise ValueError('Column mapping must map original column names to field names.')
    drop_columns=body.get('drop_columns') or []
    if isinstance(drop_columns,str):
        try:drop_columns=json.loads(drop_columns)
        except ValueError:raise ValueError('Choose valid columns to remove.')
    date_order=body.get('date_order','month_first')
    if date_order=='auto':
        import re
        mapped=schema_service.apply(frame,mapping,drop_columns)
        dates=mapped['date'].dropna().astype(str).head(1000) if 'date' in mapped else []
        parts=[re.match(r'^(\d{1,2})[/.-](\d{1,2})[/.-]\d{4}$',v.strip()) for v in dates]
        date_order='day_first' if any(m and int(m[1])>12 for m in parts) else 'month_first'
    cleaned, report = upload_service.preprocess(frame, date_order, mapping, drop_columns, deduplicate=storage_service.backend()!='oracle')
    payload = upload_service.preview_payload(cleaned, report)
    payload['can_import'] = not report['error_count'] and not cleaned.empty
    if payload['can_import']:
        session.setdefault('upload_owner', secrets.token_urlsafe(24))
        token = secrets.token_urlsafe(32)
        with _pending_lock:
            for k in list(_pending):
                if _pending[k]['expires'] < time.time(): del _pending[k]
            # One pending preview per browser; limits retained upload memory.
            for k in list(_pending):
                if _pending[k]['owner'] == session['upload_owner']: del _pending[k]
            if len(_pending) >= 20: raise ValueError('The upload queue is busy. Please try again shortly.')
            _pending[token] = dict(owner=session['upload_owner'], expires=time.time()+1800, df=cleaned, report=report, source_file=body.get('source_file','Upload'))
        payload['preview_token'] = token
    return jsonify(payload)


@api_bp.post('/upload')
@api_bp.post('/upload/preview')
def upload():
    file=request.files.get('file')
    if not file or not file.filename: return jsonify(error='Choose a CSV or XLSX file.'),400
    try:
        return _preview(upload_service.parse_upload(file.filename,file.read()),request.form)
    except ValueError as e: return jsonify(error=str(e)),400
    except Exception:
        current_app.logger.exception('Upload preview failed')
        return jsonify(error='Could not read the file. Check that it is a valid CSV or XLSX.'),400


@api_bp.post('/upload/confirm')
def confirm_upload():
    if storage_service.backend() == 'oracle':
        return jsonify(error='Save this upload to the review queue and approve ready records there.'),409
    body=request.get_json(silent=True) or {}
    token=body.get('preview_token','')
    if not isinstance(token,str): return jsonify(error='Invalid preview token.'),400
    with _pending_lock:
        item=_pending.get(token)
        if not item or item['owner']!=session.get('upload_owner') or item['expires']<time.time():
            return jsonify(error='This preview expired or was already added. Preview the file again.'),409
        if item['report']['review_count'] and body.get('reviewed') is not True:
            return jsonify(error='Please verify the flagged values before adding these records.'),400
        del _pending[token]
    try:
        aligned=upload_service.prepare_for_append(item['df'],list(pipeline.data.columns))
        from datetime import datetime, timezone
        aligned['source_file']=item.get('source_file','Upload')
        aligned['imported_at']=datetime.now(timezone.utc).isoformat()
        meta_info=pipeline.append_and_remine(aligned)
    except Exception:
        current_app.logger.exception('Import failed before snapshot publication')
        with _pending_lock: _pending[token]=item
        return jsonify(error='Records could not be saved. The dashboard was not changed. Check database access and try again.'),503
    return jsonify(status='ok', rows_added=meta_info['rows_added'],
        duplicates_skipped=len(aligned)-meta_info['rows_added'], total_rows=meta_info['n_transactions'],meta=meta_info)


_sources = {}


def _inspect_source(frame, filename, raw=None):
    session.setdefault('upload_owner',secrets.token_urlsafe(24))
    source_token=secrets.token_urlsafe(32)
    with _pending_lock:
        for key in list(_sources):
            if _sources[key]['expires']<time.time() or _sources[key]['owner']==session['upload_owner']:
                del _sources[key]
        if len(_sources)>=8:raise ValueError('The upload queue is busy. Please try again shortly.')
        _sources[source_token]=dict(owner=session['upload_owner'],expires=time.time()+1800,frame=frame,filename=filename,raw=raw)
    info=dict(source_token=source_token,source_columns=schema_service.describe(frame),fields=schema_service.FIELDS,
        sheet_names=frame.attrs.get('sheet_names',[]),selected_sheet=frame.attrs.get('selected_sheet'),source_rows=len(frame))
    try:info.update(_preview(frame,{'date_order':'auto','source_file':filename}).get_json())
    except ValueError as e:info.update(can_import=False,preparation_error=str(e))
    return jsonify(info)


@api_bp.post('/upload/inspect')
def inspect_upload():
    file=request.files.get('file')
    if not file or not file.filename:return jsonify(error='Choose a data file.'),400
    try:
        raw=file.read();frame=upload_service.parse_upload(file.filename,raw)
        return _inspect_source(frame,file.filename,raw)
    except ValueError as e:return jsonify(error=str(e)),400
    except Exception:
        current_app.logger.exception('File inspection failed')
        return jsonify(error='Could not read this file. Use a CSV, TSV or XLSX table.'),400


@api_bp.post('/upload/prepare')
def prepare_upload():
    body=request.get_json(silent=True) or {};token=body.get('source_token','')
    if not isinstance(token,str):return jsonify(error='Invalid upload reference.'),400
    with _pending_lock:source=_sources.get(token)
    if not source or source['owner']!=session.get('upload_owner') or source['expires']<time.time():
        return jsonify(error='The upload expired. Please choose the file again.'),409
    try:
        frame=source['frame']
        if body.get('sheet_name') and source['raw'] is not None and body['sheet_name']!=frame.attrs.get('selected_sheet'):
            frame=upload_service.parse_upload(source['filename'],source['raw'],body['sheet_name'])
            # New worksheet has its own headings: inspect it again instead of reusing old matches.
            return _inspect_source(frame,source['filename'],source['raw'])
        body['source_file']=source['filename']
        return _preview(frame,body)
    except ValueError as e:return jsonify(error=str(e)),400


@api_bp.get('/data')
def data_records():
    from services import report_service
    try:
        page=max(1,int(request.args.get('page',1)));size=max(1,min(100,int(request.args.get('page_size',25))))
    except ValueError:return jsonify(error='Use a valid page number.'),400
    df,_,meta=pipeline.snapshot()
    filtered=report_service.filtered_data(df,_overview_filters_from_args(request.args),request.args.get('search','').strip())
    total=len(filtered);page=min(page,max(1,(total+size-1)//size))
    priority=['date','time','barangay','vehicle_involved','collision_type','cause','severity','time_period']
    columns=[c for c in priority if c in df]+[c for c in df if c not in priority]
    view=filtered.iloc[(page-1)*size:page*size].reindex(columns=columns)
    return jsonify(columns=columns,rows=report_service.records(view),total=total,dataset_total=len(df),
        page=page,page_size=size,meta=meta)


def _csv_download(content,filename):
    from flask import Response
    response=Response(content,content_type='text/csv; charset=utf-8')
    response.headers['Content-Disposition']=f'attachment; filename="{filename}"'
    response.headers['Cache-Control']='no-store'
    return response


@api_bp.get('/export/data.csv')
def export_data():
    from services import report_service
    df,_,_=pipeline.snapshot()
    frame=report_service.filtered_data(df,_overview_filters_from_args(request.args),request.args.get('search','').strip())
    return _csv_download(report_service.csv_bytes(report_service.records(frame),list(frame.columns)),'ccdrmc-records.csv')


@api_bp.get('/export/analysis.csv')
def export_analysis():
    from services import report_service
    df,rules,meta=pipeline.snapshot()
    return _csv_download(report_service.analysis_report(df,rules,meta,_overview_filters_from_args(request.args)),'ccdrmc-dashboard-analysis.csv')


@api_bp.get('/export/patterns.csv')
def export_patterns():
    from services import report_service
    try:
        support=float(request.args.get('min_support',.05));confidence=float(request.args.get('min_confidence',.60));lift=float(request.args.get('min_lift',1.2))
        if not (.05<=support<=1 and 0<=confidence<=1 and math.isfinite(lift) and lift>=0):raise ValueError()
    except ValueError:return jsonify(error='Use valid pattern thresholds.'),400
    _,rules,meta=pipeline.snapshot()
    thresholds=dict(min_support=support,min_confidence=confidence,min_lift=lift,search=request.args.get('search',''),sort_by=request.args.get('sort_by','lift'))
    rows=report_service.pattern_rows(rules,thresholds)
    for row in rows:row.update(dataset_revision=meta.get('dataset_revision',''),min_support=support,min_confidence=confidence,min_lift=lift)
    return _csv_download(report_service.csv_bytes(rows,report_service.PATTERN_COLUMNS+['dataset_revision','min_support','min_confidence','min_lift']),'ccdrmc-patterns.csv')
