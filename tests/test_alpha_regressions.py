"""Reproductions of the data-integrity failures found during the alpha audit."""
import io
import pandas as pd
import pytest
from services import incoming_pipeline as engine,dataset_service as dataset,upload_service as upload


def row(**changes):
    value=dict(date='2026-03-01',time='19:20',barangay='Ipil',damage_injury='abrasion',vehicle_involved='motorcycle')
    value.update(changes);return value


@pytest.mark.parametrize('description',['no fracture','without lacerations','suspected fatal injury, outcome not confirmed','possible fracture','unresponsive'])
def test_uncertain_outcomes_excluded(description):
    prepared=dataset.prepare(pd.DataFrame([row(damage_injury=description)]))
    assert prepared['items'][0]['cleaned']['needs_manual_review'] is True
    assert dataset.assess(prepared,[])['stats']['excluded']==1


def test_supplied_outcome_requires_explicit_confirmation_on_conflict():
    raw=pd.DataFrame([row(severity='Fatal')])
    conflict=dataset.prepare(raw)['items'][0]
    assert conflict['cleaned']['supplied_severity']=='Fatal'
    assert conflict['cleaned']['derived_severity']=='Non-Fatal'
    assert conflict['reason']
    confirmed=dataset.prepare(raw,verified_severity=True)['items'][0]
    assert confirmed['cleaned']['severity']=='Fatal' and not confirmed['reason']


def test_new_text_and_derived_month_survive():
    cleaned=dataset.prepare(pd.DataFrame([row(damage_type='Scratched bumper',package='First aid',month=3)]))['items'][0]['cleaned']
    assert cleaned['damage_type']=='Scratched Bumper' and cleaned['package']=='First Aid'
    assert cleaned['month']=='March'


def test_real_excel_date_only_has_no_time_and_explicit_midnight_survives():
    content=io.BytesIO()
    pd.DataFrame([row(date=pd.Timestamp('2026-03-01'),time=None)]).to_excel(content,index=False)
    cleaned=dataset.prepare(upload.parse_upload('date-only.xlsx',content.getvalue()))['items'][0]['cleaned']
    assert cleaned['time']=='' and cleaned['time_period']=='Unknown' and cleaned['hour'] is None
    midnight=dataset.prepare(pd.DataFrame([row(time='00:00')]))['items'][0]['cleaned']
    assert midnight['hour']==0 and midnight['time']=='00:00:00'


def test_ambiguous_file_requires_choice_then_day_first_is_correct():
    source=pd.DataFrame([row(date='03/04/2026'),row(date='25/04/2026')])
    prepared=dataset.prepare(source)
    assert prepared['stats']['engineering']['date_choice_required']
    assert prepared['items'][0]['reason'] and prepared['items'][0]['cleaned']['date']!='2026-03-04'
    with pytest.raises(ValueError,match='date format'):dataset.publish(prepared,'test.csv',None,'test','unused')
    selected=dataset.prepare(source,order='day_first')
    assert [e['cleaned']['date'] for e in selected['items']]==['2026-04-03','2026-04-25']
    assert not selected['stats']['engineering']['date_choice_required']


def test_stable_duplicate_identity_despite_different_batch_medians():
    a=row(incident_id='same',speed=None)
    first=dataset.prepare(pd.DataFrame([a,row(incident_id='other1',speed=20)]))
    second=dataset.prepare(pd.DataFrame([a,row(incident_id='other2',speed=80)]))
    saved=dict(first['items'][0]['cleaned'],record_id='existing')
    assert saved['speed']==20 and second['items'][0]['cleaned']['speed']==80
    assert saved['estimated_fields']=='speed'
    assert dataset.assess(second,[saved])['items'][0]['status']=='Duplicate'


def test_semantic_missingness_and_unknown_coordinates():
    prepared=dataset.prepare(pd.DataFrame([row(weather='N/A')]))
    assert prepared['stats']['missing_values']==1
    assert next(p for p in prepared['stats']['variables'] if p['name']=='weather')['missing']==1
    assert prepared['items'][0]['cleaned']['latitude'] is None


@pytest.mark.parametrize('value',[-5,'999999999999999999999999999',131])
def test_numeric_range_errors_preserve_original_and_exclude_only_bad_row(value):
    prepared=dataset.prepare(pd.DataFrame([row(age=value),row(age=25)]))
    plan=dataset.assess(prepared,[])
    assert plan['stats']['excluded']==1 and plan['stats']['ready']==1
    assert plan['items'][0]['original']['age']==value
    assert 'Age' in plan['items'][0]['reason']


def test_upload_overflow_is_a_controlled_preview_and_tabs_remain_independent(monkeypatch):
    from app import app
    from services import review_store
    from routes.api import _sources
    monkeypatch.setattr(review_store,'rows',lambda:[])
    _sources.clear();client=app.test_client()
    def inspect(name,record):
        r=client.post('/api/dataset/inspect',data={'file':(io.BytesIO(pd.DataFrame([record]).to_csv(index=False).encode()),name)})
        assert r.status_code==200
        return r.json['source_token']
    first=inspect('first.csv',row(age='999999999999999999999999999'))
    inspect('second.csv',row())
    response=client.post('/api/dataset/prepare',json={'source_token':first})
    assert response.status_code==200 and response.json['stats']['excluded']==1
    denied=app.test_client().post('/api/dataset/prepare',json={'source_token':first})
    assert denied.status_code==400
    _sources.clear()


def test_corrupt_excel_has_actionable_error():
    with pytest.raises(ValueError,match='save a new .xlsx or CSV copy'):
        upload.parse_upload('bad.xlsx',b'not an Excel file')


def test_review_and_upload_share_outcome_and_feature_rules():
    from services import review_service
    raw=row(damage_injury='suspected fatal injury',severity='Fatal',month=3,damage_type='Scratched bumper')
    reviewed,*_=review_service.clean(raw,'month_first')
    uploaded=dataset.prepare(pd.DataFrame([raw]))['items'][0]['cleaned']
    for key in ('severity','month','damage_type','derived_severity','supplied_severity'):
        assert reviewed[key]==uploaded[key]
