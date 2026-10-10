import pandas as pd
from services import dataset_service as service


def sample(**values):
    return dict(date='2026-09-01',time='8:30 PM',barangay='San Fabian',vehicle_involved='motorcycle',collision_type='SELF ACCIDENT',cause='LOSS ON COTROL',damage_injury='abrasion',**values)


def test_dataset_summary_cleaning_and_duplicates():
    a=sample(weather='Rainy')
    frame=pd.DataFrame([a,a,sample(weather='Sunny'),dict(a,date='invalid'),dict(a,damage_injury='unclear')])
    result=service.prepare(frame)
    plan=service.assess(result,[])
    assert plan['stats']['rows']==5 and plan['stats']['columns']==8
    assert plan['stats']['duplicate_rows']==1
    assert plan['stats']['ready']==2 and plan['stats']['duplicates_skipped']==1 and plan['stats']['excluded']==2
    cleaned=plan['items'][0]['cleaned']
    assert cleaned['severity']=='Non-Fatal' and cleaned['day']=='Tuesday' and cleaned['time']=='20:30:00'
    assert cleaned['weather']=='Rainy'


def test_exact_duplicates_against_existing_keep_different_people_and_extras():
    prepared=service.prepare(pd.DataFrame([sample(at_user='Driver'),sample(at_user='Passenger')]))
    existing=dict(prepared['items'][0]['cleaned'],record_id='abc',record_revision=1,source_file='old.csv',preprocessing_version='review-v1')
    existing['date']='9/1/2026';existing['time']='20:30'
    plan=service.assess(prepared,[existing])
    assert plan['stats']['ready']==1 and plan['stats']['duplicates_skipped']==1


def test_all_invalid_rows_excluded_after_issue_display_limit():
    frame=pd.DataFrame([dict(sample(),date='bad') for _ in range(250)])
    plan=service.assess(service.prepare(frame),[])
    assert plan['stats']['excluded']==250 and plan['stats']['ready']==0
    assert plan['items'][-1]['original']['date']=='bad'


def test_missing_counts_and_variable_information():
    frame=pd.DataFrame([sample(weather=''),sample(weather=None),sample(weather='Rainy')])
    result=service.prepare(frame)
    assert result['stats']['missing_values']==2 and result['stats']['rows_with_missing']==2
    profile=next(v for v in result['stats']['variables'] if v['name']=='weather')
    assert profile['missing']==2 and profile['unique']==1 and profile['imputed']==2


def test_conflicting_and_unknown_outcomes_excluded():
    result=service.assess(service.prepare(pd.DataFrame([sample(severity='Fatal'),dict(sample(),damage_injury='unresponsive')])),[])
    assert result['stats']['excluded']==2
    assert result['items'][0]['cleaned']['severity']=='Unknown'
    assert result['items'][0]['cleaned']['supplied_severity']=='Fatal'
    assert result['items'][0]['cleaned']['derived_severity']=='Non-Fatal'


def test_alternate_headings_and_day_first_dates():
    result=service.prepare(pd.DataFrame([{'Happened':'25/09/2026','Injury':'fracture','Case reference':'A1'}]),mapping={'Happened':'date'})
    assert result['stats']['date_order']=='auto'
    assert result['items'][0]['cleaned']['date']=='2026-09-25'
    assert result['items'][0]['cleaned']['case_reference']=='A1'


def test_reimport_exported_record_is_duplicate():
    existing=service.prepare(pd.DataFrame([sample()]))['items'][0]['cleaned']
    existing.update(record_id='known-id',record_revision=1,source_file='original.csv',imported_at='2026-10-01',preprocessing_version='dataset-v1')
    result=service.assess(service.prepare(pd.DataFrame([existing])),[existing])
    assert result['stats']['ready']==0 and result['stats']['duplicates_skipped']==1
