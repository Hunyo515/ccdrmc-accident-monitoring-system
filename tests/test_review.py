import io
import pytest
import pandas as pd
from services import review_service as review
from services import document_reports


def row(**changes):
    result=dict(date='2026-10-01',time='20:30',barangay='San Fabian',vehicle_involved='Single Motor',collision_type='Self-accident',cause='Loss of Control',severity='Non-Fatal',damage_injury='abrasion')
    result.update(changes);return result

@pytest.mark.parametrize('description', ['no fatalities','no injuries','unresponsive','cardiac arrest','one casualty','unknown wording',''])
def test_uncertain_outcome_not_guessed(description):
    assert review.suggest_severity(description)[0] is None

@pytest.mark.parametrize('description,expected',[('declared deceased','Fatal'),('abrasion on arm','Non-Fatal'),('property damage only','Damage-to-Property')])
def test_explainable_suggestions(description,expected):
    suggestion,reason=review.suggest_severity(description)
    assert suggestion==expected and reason


def test_preprocessing_features_and_extra_columns():
    result,issues,blocked,changes,suggestion=review.clean(row(time='8:30 PM',weather='Rainy',severity=''), 'month_first')
    assert (result['day'],result['month'],result['time_period'])==('Thursday','October','8:01PM-12MN')
    assert result['weather']=='Rainy' and result['severity']=='Non-Fatal'
    assert not blocked and suggestion=='Non-Fatal'


def test_missing_severity_blocks_but_missing_coordinates_does_not():
    cleaned,*_=review.clean(row(severity='',damage_injury=''),'month_first')
    d=dict(status='pending',blocked=False,cleaned=cleaned,reviewed=True)
    assert review.classify(d,[])=='needs_review'
    cleaned['severity']='Non-Fatal'
    assert review.classify(d,[])=='ready'


def test_duplicate_comparison_retains_separate_people():
    record=dict(row(),record_id='existing',record_revision=1,at_user='Driver')
    incoming=row(at_user='Passenger')
    matches=review.candidate_records(incoming,[record])
    assert matches and matches[0]['reason']=='Same date, time and barangay'
    draft=dict(status='pending',cleaned=incoming,blocked=False,reviewed=True)
    assert review.classify(draft,[record])=='duplicate'
    draft['decision']='separate'
    assert review.classify(draft,[record])=='ready'


def test_stale_edit_never_replaces_new_revision():
    existing=dict(row(),record_id='existing',record_revision=2)
    draft=dict(status='pending',cleaned=row(),blocked=False,reviewed=True,decision='update',target_id='existing',target_revision=1)
    assert review.classify(draft,[existing])=='conflict'


def test_excel_no_formula_execution_and_real_filter_metadata():
    from openpyxl import load_workbook
    frame=pd.DataFrame([row(notes='=HYPERLINK("https://example.com")')])
    content=document_reports.export_records(frame,{'barangay':'San Fabian'})
    sheet=load_workbook(io.BytesIO(content)).active
    assert sheet['B3'].value=='barangay: San Fabian'
    assert sheet['B4'].value==1
    assert all(c.data_type!='f' for r in sheet for c in r)


def test_db_failure_returns_clear_error(monkeypatch):
    from app import app
    from services import storage_service as storage
    monkeypatch.setattr(storage,'backend',lambda:'oracle')
    def unavailable():raise ConnectionError('Test outage')
    monkeypatch.setattr(storage,'connect',unavailable)
    response=app.test_client().post('/api/review/manual',json={'record':row()})
    assert response.status_code==503 and 'Database unavailable' in response.json['error']


def test_report_filters_include_date_and_severity():
    from services.report_service import filtered_data
    frame=pd.DataFrame([dict(row(),year=2026),dict(row(date='2025-01-01',severity='Fatal'),year=2025)])
    result=filtered_data(frame,{'date_from':'2026-01-01','date_to':'2026-12-31','severity':'Non-Fatal'})
    assert len(result)==1 and result.iloc[0]['date']=='2026-10-01'


def test_excel_native_dates_survive_review_serialization():
    from datetime import datetime
    import json
    raw=json.loads(pd.DataFrame([row(date=datetime(2026,10,1),time=datetime(2026,10,1,20,30))]).to_json(orient='records',date_format='iso'))[0]
    cleaned,_,blocked,_,_=review.clean(raw,'month_first')
    assert not blocked and cleaned['date']=='2026-10-01' and cleaned['time']=='20:30:00'


def test_mixed_historical_and_new_dates_are_both_filtered():
    from services.report_service import filtered_data
    frame=pd.DataFrame([dict(row(date='10/01/2026'),year=2026),dict(row(date='2026-10-01'),year=2026)])
    assert len(filtered_data(frame,{'date_from':'2026-10-01','date_to':'2026-10-01'}))==2


def test_invalid_report_range_is_rejected():
    from app import app
    assert app.test_client().get('/api/export/data.xlsx?date_from=2026-12-31&date_to=2026-01-01').status_code==400


def test_pdf_empty_selection_is_valid():
    import pymupdf
    frame=pd.DataFrame(columns=['severity'])
    content=document_reports.analysis_pdf(frame,{'search':'no matching rows'},'test-revision')
    pdf=pymupdf.open(stream=content,filetype='pdf')
    assert len(pdf)==1 and 'No approved records match' in pdf[0].get_text()


def test_duplicate_events_match_historical_date_and_time_formats():
    existing=dict(row(date='10/01/2026',time='8:30 PM'),record_id='existing',record_revision=1,at_user='Driver')
    incoming=row(date='2026-10-01',time='20:30:00',at_user='Passenger')
    assert review.candidate_records(incoming,[existing])[0]['reason']=='Same date, time and barangay'


def test_agency_friendly_headings_are_recognised():
    from services import schema_service
    frame=pd.DataFrame([{'Date of crash':'2026-10-01','Time of crash':'8:30 PM','Injury / damage description':'abrasion','Road user':'Driver'}])
    mapped=schema_service.apply(frame)
    assert {'date','time','damage_injury','at_user'} <= set(mapped.columns)
    cleaned,_,blocked,_,suggestion=review.clean(mapped.iloc[0].to_dict(),'month_first')
    assert not blocked and suggestion=='Non-Fatal' and cleaned['day']=='Thursday'
