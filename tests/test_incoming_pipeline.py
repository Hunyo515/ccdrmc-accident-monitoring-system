import pandas as pd
from services import incoming_pipeline as engine, dataset_service as dataset


def base(**kw):
    row=dict(date='2026-03-01',time='7:20 PM',location='P1 IPIL, ECHAGUE, ISABELA',damage_injury='abrasion')
    row.update(kw);return row


def test_mixed_dates_excel_serial_and_six_periods():
    serial=(pd.Timestamp('2026-03-02 19:20')-pd.Timestamp('1899-12-30')).total_seconds()/86400
    f=pd.DataFrame([base(date=serial,time=None),base(date='25/03/2026',time=0),base(date='March 3, 2026',time='4:00 AM')])
    clean,_,audit=engine.run(f)
    assert clean.date.tolist()==['2026-03-02','2026-03-25','2026-03-03']
    assert clean.hour.tolist()==[19,0,4] and clean.minute.tolist()==[20,0,0]
    assert str(clean.hour.dtype)=='Int64' and str(clean.latitude.dtype)=='float64'
    assert clean.time_period.tolist()==['4:01PM-8PM','8:01PM-12MN','12:01AM-4AM']
    assert audit['excel_dates_converted']==1
    assert [engine.legacy.period_for(h,1) for h in (0,4,8,12,16,20)]==list(engine.legacy.PERIODS)


def test_fuzzy_geography_and_numeric_imputation():
    f=pd.DataFrame([base(location='P1 SAN FABAIN, ECHAGUE, ISABELA',speed='20'),base(speed='40'),base(speed='bad')])
    clean,_,audit=engine.run(f)
    assert clean.iloc[0].barangay=='San Fabian' and clean.iloc[0].municipality=='Echague' and clean.iloc[0].province=='Isabela'
    assert clean.speed.tolist()==[20,40,30] and str(clean.speed.dtype)=='Int64'
    assert any(a['field']=='barangay' and a['score']>=85 for a in audit['normalizations'])
    assert clean.latitude_imputed.all()


def test_sparse_columns_preserved_and_not_model_fields():
    f=pd.DataFrame([base(new_weather='Rainy' if i==0 else None) for i in range(10)])
    clean,_,audit=engine.run(f)
    profile=next(p for p in audit['variables'] if p['name']=='new_weather')
    assert profile['use']=='Storage/Auditing Only' and profile['missing_percent']==90
    assert 'new_weather' not in engine.MODEL_FIELDS and len(clean)==10
    assert clean.new_weather.iloc[1]=='Unknown'


def test_new_categorical_cardinality_and_typo_merge():
    f=pd.DataFrame([base(weather=v) for v in ['Rainy','Rainy','Rainyy']])
    clean,_,audit=engine.run(f)
    assert clean.weather.tolist()==['Rainy']*3
    p=next(p for p in audit['variables'] if p['name']=='weather')
    assert p['unique']==2 and p['unique_after']==1


def test_severity_rules_flag_ambiguous_and_negations():
    examples={'declared deceased':'Fatal','non-fatal injury':'Non-Fatal','no injuries, property damage only':'Damage-to-Property','unresponsive':'Unknown','no fatalities':'Unknown','abrasion':'Non-Fatal'}
    for description,expected in examples.items():
        label,flag=engine.severity(description)
        assert label==expected and flag==(expected=='Unknown')
    prepared=dataset.prepare(pd.DataFrame([base(damage_injury='unresponsive')]))
    assert prepared['items'][0]['cleaned']['needs_manual_review'] is True
    assert dataset.assess(prepared,[])['stats']['excluded']==1


def test_date_field_named_time_is_not_mapped_to_injury():
    clean,_,_=engine.run(pd.DataFrame([{'Date':'03/01/2026','Time':'7:20 PM','Place of Incident':'P1 IPIL, ECHAGUE, ISABELA','Damage/Injury':'abrasion'}]))
    assert clean.iloc[0].hour==19 and clean.iloc[0].damage_injury=='abrasion'


def test_sparse_presence_flag_preserves_reported_missingness():
    clean,_,audit=engine.run(pd.DataFrame([base(alcohol_detected='yes' if i==0 else None) for i in range(10)]))
    assert clean.alcohol_detected_information_present.tolist()==[True]+[False]*9
    assert next(p for p in audit['variables'] if p['name']=='alcohol_detected')['use']=='Storage/Auditing Only'


def test_imputed_coordinates_do_not_become_map_points():
    from services.map_service import get_map_points
    clean,_,_=engine.run(pd.DataFrame([base(),base(latitude=16.7,longitude=121.68)]))
    assert len(get_map_points(clean))==1
