import io
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app
from arm import pipeline as arm
from services import upload_service as upload, storage_service as storage, rules_service, overview_service, prescription_service
from services.contextual_prescriptions import feature_steps, PERIODS


def raw(**changes):
    row={'Date':'10/01/2026','Time':'8:30 PM','Vehicle':'motorcycle','Collision':'SELF ACCIDENT','Probable Cause':'LOSS ON COTROL','Brgy':'SAN FABIAN','Severity':'Non-Fatal','latitude':'16.7','longitude':'121.7'}
    row.update(changes);return pd.DataFrame([row])


def test_agency_cleaning_and_derived_values():
    df,r=upload.preprocess(raw())
    row=df.iloc[0]
    assert (row.date,row.day,row.month,row.hour,row.time_period)==('2026-10-01','Thursday','October',20,'8:01PM-12MN')
    assert (row.vehicle_involved,row.collision_type,row.cause,row.barangay)==('Single Motor','Self-accident','Loss of Control','San Fabian')
    assert r['error_count']==0


@pytest.mark.parametrize('h,m,expected',[(0,0,'8:01PM-12MN'),(0,1,'12:01AM-4AM'),(4,0,'12:01AM-4AM'),(4,1,'4:01AM-8AM'),(12,0,'8:01AM-12NN'),(12,1,'12:01PM-4PM'),(20,0,'4:01PM-8PM'),(20,1,'8:01PM-12MN')])
def test_notebook_time_boundaries(h,m,expected): assert upload.period_for(h,m)==expected


def test_dates_are_explicit_and_invalid_time_blocked():
    assert upload.date_value('03/04/2025','month_first').month==3
    assert upload.date_value('03/04/2025','day_first').month==4
    df,r=upload.preprocess(raw(Time='25:00'))
    assert r['error_count']>0
    assert pd.isna(upload.date_value('2/30/2025','month_first'))


def test_missing_injury_outcome_never_imputed_from_text():
    df,r=upload.preprocess(raw(Severity='',damage_injury='no fatal injuries; abrasion'))
    assert df.iloc[0].severity=='Unknown'
    assert r['review_count']==1


def test_duplicates_and_other_casualties():
    first=raw();second=raw(at_user='Passenger')
    df,r=upload.preprocess(pd.concat([first,first,second],ignore_index=True))
    assert len(df)==2 and r['duplicates_removed']==1


def test_all_seven_features_have_three_domain_steps():
    values={'vehicle_involved':'Single Motor vs Tricycle','collision_type':'Head-on Hit','cause':'Loss of Control','barangay':'San Fabian','day':'Friday','time_period':'8:01PM-12MN','severity':'Fatal'}
    for f,v in values.items():
        steps=feature_steps(f,v); assert len(steps)==3 and all(steps)
    acts=prescription_service.get().match_rule({'items':list(values.items())})
    plans=[a for a in acts if a.get('contextual')]
    assert {a['agency'] for a in plans}=={'enforcement','engineering','education'}
    assert all(len(a['matched_on'])==7 for a in plans)
    assert all('Pending' in a['validation_status'] for a in plans)
    assert 'helmet' in next(a['action'] for a in plans if a['agency']=='education')
    assert '12 midnight' in next(a['action'] for a in plans if a['agency']=='enforcement')


def rule(ant,con,conf=.7,lift=1.4):
    return dict(antecedents=[v for f,v in ant],consequents=[v for f,v in con],antecedent_items=ant,consequent_items=con,items=ant+con,antecedent_label=str(ant),consequent_label=str(con),confidence=conf,lift=lift,support=.1)


def test_redundancy_keeps_best_direction_and_useful_extensions():
    a=[('cause','Loss of Control')];b=[('vehicle_involved','Single Motor')];c=[('day','Friday')]
    forward=rule(a,b);reverse=rule(b,a,.8);redundant=rule(a+c,b,.6,1.3);useful=rule(a+[('day','Sunday')],b,.9,1.7)
    kept,total=rules_service.filter_rules([forward,reverse,redundant,useful],limit=50)
    assert reverse in kept and forward not in kept
    # Because the representative direction changed, the direction-specific pruning must also inspect originals.
    assert useful in kept and redundant not in kept


def test_dashboard_aggregates_and_colors():
    data=arm.pipeline.data
    out=overview_service.build_overview(data,{})
    assert out['kpis']['time_period']['count']==data.time_period.value_counts().max()
    assert out['hourly_distribution'][18]['label']=='6 PM'
    counts=[r['count'] for r in out['day_distribution']];assert counts==sorted(counts,reverse=True)
    assert sum(r['count'] for r in out['month_distribution'])==len(data)
    assert sum(r['count'] for r in out['yearly_trend'])==len(data)
    one=overview_service.build_barangay_breakdown(data,{})
    assert all(one['colors'][b]==out['barangay_colors'][b] for b in one['barangays'])
    b=one['barangays'][0]
    assert overview_service.build_barangay_breakdown(data,{'barangay':b})['barangays']==[b]


def test_severity_counts_do_not_call_unknown_nonfatal():
    df,_=upload.preprocess(pd.concat([raw(Severity=''),raw(Severity='property damage')],ignore_index=True))
    row=overview_service.build_overview(df,{})['top_causes'][0]
    assert row['non_fatal']==0 and row['unknown']==1 and row['property_damage']==1


@pytest.fixture
def isolated_data(tmp_path,monkeypatch):
    path=tmp_path/'crashes.csv';path.write_bytes(storage.CSV_PATH.read_bytes())
    monkeypatch.setattr(storage,'CSV_PATH',path);monkeypatch.setattr(arm,'DATA_PATH',path)
    monkeypatch.setattr(arm,'CACHE_DIR',tmp_path)
    state=(arm.pipeline.data,arm.pipeline.rules,arm.pipeline.itemsets,arm.pipeline.meta)
    yield path
    arm.pipeline.data,arm.pipeline.rules,arm.pipeline.itemsets,arm.pipeline.meta=state


def test_preview_verify_commit_and_replay(isolated_data):
    app.config['TESTING']=True
    with app.test_client() as c:
        before=isolated_data.read_bytes()
        data=c.post('/api/upload',data={'file':(io.BytesIO(raw(Severity='').to_csv(index=False).encode()),'raw.csv')}).get_json()
        assert isolated_data.read_bytes()==before and data['preview'][0]['hour']==20
        token=data['preview_token']
        assert c.post('/api/upload/confirm',json={'preview_token':token}).status_code==400
        with app.test_client() as other:
            assert other.post('/api/upload/confirm',json={'preview_token':token,'reviewed':True}).status_code==409
        saved=c.post('/api/upload/confirm',json={'preview_token':token,'reviewed':True})
        assert saved.status_code==200 and saved.get_json()['rows_added']==1
        assert c.post('/api/upload/confirm',json={'preview_token':token,'reviewed':True}).status_code==409
        again=c.post('/api/upload',data={'file':(io.BytesIO(raw(Severity='').to_csv(index=False).encode()),'raw.csv')}).get_json()
        saved=c.post('/api/upload/confirm',json={'preview_token':again['preview_token'],'reviewed':True}).get_json()
        assert saved['rows_added']==0 and saved['duplicates_skipped']==1


def test_persistence_failure_keeps_dashboard(isolated_data,monkeypatch):
    before=arm.pipeline.data.copy();disk=isolated_data.read_bytes()
    def fail(*args):raise RuntimeError('Simulated storage failure')
    monkeypatch.setattr(storage,'save_append',fail)
    cleaned,_=upload.preprocess(raw())
    with pytest.raises(RuntimeError):arm.pipeline.append_and_remine(cleaned)
    pd.testing.assert_frame_equal(before,arm.pipeline.data)
    assert isolated_data.read_bytes()==disk


def test_threshold_defaults_and_parameters():
    with app.test_client() as c:
        data=c.get('/api/rules').get_json()
        assert len(data['rules'])==10
        assert all(r['support']>=.05 and r['confidence']>=.6 and r['lift']>=1.2 for r in data['rules'])
        assert len(c.get('/api/rules?limit=3').get_json()['rules'])==3
        assert c.get('/api/rules?min_support=nan').status_code==400
        assert c.get('/api/rules?min_lift=inf').status_code==400


def test_oracle_connector_uses_server_environment(monkeypatch):
    import oracledb
    connect=MagicMock();monkeypatch.setattr(oracledb,'connect',connect)
    monkeypatch.setenv('ORACLE_PASSWORD','test-only');storage.connect()
    assert connect.call_args.kwargs['host']=='localhost'
    assert connect.call_args.kwargs['service_name']=='XEPDB1'
    assert connect.call_args.kwargs['password']=='test-only'
    with pytest.raises(ValueError):storage.identifier('CRASH; DROP TABLE X')


def test_normalization_is_idempotent_for_canonical_categories():
    for field,key in [('cause','CANONICAL_CAUSES'),('collision_type','CANONICAL_COLLISIONS'),('vehicle_involved','CANONICAL_VEHICLES')]:
        for value in upload.MAPS[key]:
            normalized=upload.normalize_category(field,value)
            assert upload.normalize_category(field,normalized)==normalized
    frame,report=upload.preprocess(raw())
    assert report['review_count']==0
    assert frame.iloc[0].cause=='Loss of Control'


def test_oracle_append_uses_binds_clob_and_commit(monkeypatch):
    conn=MagicMock();conn.__enter__.return_value=conn
    cursor=MagicMock();cursor.__enter__.return_value=cursor;conn.cursor.return_value=cursor
    monkeypatch.setenv('DATA_BACKEND','oracle');monkeypatch.setattr(storage,'connect',lambda:conn)
    frame,_=upload.preprocess(raw())
    storage.save_append(frame,frame)
    sql,rows=cursor.executemany.call_args.args
    assert ':record_hash' in sql and ':record_json' in sql
    assert 'Loss of Control' not in sql
    assert json.loads(rows[0]['record_json'])['cause']=='Loss of Control'
    conn.commit.assert_called_once()


def test_oracle_read_clob_records(monkeypatch):
    monkeypatch.setenv("ORACLE_TABLE","CCDRMC_CRASH_RECORDS")
    conn=MagicMock();conn.__enter__.return_value=conn
    cursor=MagicMock();cursor.__enter__.return_value=cursor;conn.cursor.return_value=cursor
    payload=MagicMock();payload.read.return_value='{"date":"2026-10-01","cause":"Loss of Control"}'
    cursor.__iter__.return_value=iter([(payload,)])
    monkeypatch.setenv('DATA_BACKEND','oracle');monkeypatch.setattr(storage,'connect',lambda:conn)
    assert storage.load().iloc[0].cause=='Loss of Control'


def test_column_mapping_xlsx_and_record_identity():
    frame=raw().rename(columns={'Date':'WHEN IT HAPPENED'})
    buffer=io.BytesIO();frame.to_excel(buffer,index=False)
    parsed=upload.parse_upload('agency.xlsx',buffer.getvalue())
    cleaned,report=upload.preprocess(parsed,mapping={'WHEN IT HAPPENED':'date'})
    assert report['error_count']==0 and cleaned.iloc[0].date=='2026-10-01'
    row=cleaned.iloc[0].to_dict();row['record_id']='ONE'
    second={**row,'record_id':'TWO'}
    assert storage.fingerprint(row)!=storage.fingerprint(second)


def test_exactly_one_prescription_per_domain_for_every_displayed_pattern():
    with app.test_client() as client:
        rules=client.get('/api/rules?limit=5000').get_json()['rules']
        assert rules
        for rule in rules:
            actions=rule['actions']
            assert len(actions)==3
            assert {a['agency'] for a in actions}=={'enforcement','engineering','education'}
            assert all(a['steps']==[a['action']] for a in actions)
            assert all(a['validation_status']=='Pending expert validation' for a in actions)
            assert all('source_catalog_ids' in a for a in actions)


def inspect(client,frame,name='agency.csv'):
    return client.post('/api/upload/inspect',data={'file':(io.BytesIO(frame.to_csv(index=False).encode()),name)}).get_json()


def test_reordered_agency_headings_and_extra_choices():
    frame=raw().rename(columns={'Vehicle':'Other vehicle involved (NMV\nor MV)','Probable Cause':'Accident\nCausation','Brgy':'Exact Location\n(Number, Street, LGU)'})
    frame['Officer remarks']='Keep this note';frame['Unused']='remove me';frame['review_notes']='original agency note'
    frame=frame[list(reversed(frame.columns))]
    with app.test_client() as c:
        d=inspect(c,frame)
        assert d['can_import'] and d['preview'][0]['cause']=='Loss of Control'
        assert d['preview'][0]['extra_review_notes']=='original agency note'
        mapping={x['source']:x['suggestion'] for x in d['source_columns']}
        result=c.post('/api/upload/prepare',json={'source_token':d['source_token'],'mapping':mapping,'drop_columns':['Unused']}).get_json()
        assert result['preview'][0]['officer_remarks']=='Keep this note'
        assert 'unused' not in result['columns']
        assert result['preview'][0]['extra_review_notes']=='original agency note'


def test_missing_meaning_can_be_mapped_without_reupload():
    frame=pd.DataFrame({'WHEN':['2026-09-30'],'Notes':['Unspecified crash']})
    with app.test_client() as c:
        d=inspect(c,frame)
        assert not d['can_import'] and 'Date of crash' in d['preparation_error']
        with app.test_client() as other:
            assert other.post('/api/upload/prepare',json={'source_token':d['source_token']}).status_code==409
        result=c.post('/api/upload/prepare',json={'source_token':d['source_token'],'mapping':{'WHEN':'date','Notes':'__keep__'}}).get_json()
        assert result['can_import']
        assert result['preview'][0]['cause']=='Unknown' and result['report']['review_count']==1


def test_duplicate_meanings_require_explicit_resolution():
    with app.test_client() as c:
        d=inspect(c,raw(crash_date='2026-09-30'))
        assert not d['can_import']
        fixed=c.post('/api/upload/prepare',json={'source_token':d['source_token'],'mapping':{'crash_date':'__keep__'}}).get_json()
        assert fixed['can_import'] and fixed['preview'][0]['crash_date']=='2026-09-30'


@pytest.mark.parametrize('filename,delimiter',[('agency.csv',';'),('agency.tsv','\t'),('agency.csv','|')])
def test_tabular_delimiters(filename,delimiter):
    parsed=upload.parse_upload(filename,raw().to_csv(index=False,sep=delimiter).encode())
    cleaned,report=upload.preprocess(parsed)
    assert report['error_count']==0 and cleaned.iloc[0].hour==20


def test_excel_sheet_selection_and_title_rows():
    buffer=io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        pd.DataFrame({'Instructions':['Use the Records worksheet']}).to_excel(writer,sheet_name='Read me',index=False)
        raw().to_excel(writer,sheet_name='Records',startrow=2,index=False)
    with app.test_client() as c:
        d=c.post('/api/upload/inspect',data={'file':(io.BytesIO(buffer.getvalue()),'agency.xlsx')}).get_json()
        assert not d['can_import'] and len(d['sheet_names'])==2
        d=c.post('/api/upload/prepare',json={'source_token':d['source_token'],'sheet_name':'Records'}).get_json()
        assert d['can_import'] and d['selected_sheet']=='Records' and d['preview'][0]['hour']==20


def read_csv_response(response):
    import csv
    assert response.status_code==200
    assert response.headers['Content-Type'].startswith('text/csv')
    return list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))


def test_verified_import_updates_data_analysis_mining_and_reports(isolated_data):
    with app.test_client() as c:
        count=c.get('/api/overview').get_json()['kpis']['total_accidents']
        revision=c.get('/api/meta').get_json()['dataset_revision']
        d=inspect(c,raw(record_id='REPORT-INTEGRATION',Notes='=1+1'))
        saved=c.post('/api/upload/confirm',json={'preview_token':d['preview_token'],'reviewed':True}).get_json()
        assert saved['rows_added']==1 and saved['meta']['n_transactions']==count+1
        assert saved['meta']['dataset_revision']!=revision
        assert c.get('/api/overview').get_json()['kpis']['total_accidents']==count+1
        result=c.get('/api/data?search=REPORT-INTEGRATION').get_json()
        assert result['total']==1 and result['rows'][0]['notes']=='=1+1'
        assert result['rows'][0]['source_file']=='agency.csv'
        export=read_csv_response(c.get('/api/export/data.csv?search=REPORT-INTEGRATION'))
        assert len(export)==1 and export[0]['notes']=="'=1+1"
        patterns=read_csv_response(c.get('/api/export/patterns.csv'))
        public=c.get('/api/rules?limit=5000').get_json()
        assert len(patterns)==public['total']
        assert all(p['enforcement'] and p['engineering'] and p['public_information_education'] for p in patterns)
        assert all(p['dataset_revision']==saved['meta']['dataset_revision'] for p in patterns)
        report=read_csv_response(c.get('/api/export/analysis.csv'))
        assert next(r for r in report if r['metric']=='Total crash records')['value']==str(count+1)
        assert {'By year','By month','By weekday','Top 5 barangays by month','Top 5 barangays by weekday','Patterns','Map'} <= {r['section'] for r in report}
        assert sum(int(r['value']) for r in report if r['section']=='By month' and r['metric']=='Total records')==count+1


def test_filtered_report_and_empty_data_export():
    with app.test_client() as c:
        query='?barangay=San%20Fabian&year_from=2022&year_to=2022'
        overview=c.get('/api/overview'+query).get_json()
        report=read_csv_response(c.get('/api/export/analysis.csv'+query))
        total=next(r for r in report if r['metric']=='Total crash records')
        assert int(total['value'])==overview['kpis']['total_accidents']
        assert all(r['scope'].startswith('Full dataset') for r in report if r['section']=='Patterns')
        assert not read_csv_response(c.get('/api/export/data.csv?search=NOT-A-REAL-RECORD'))
        assert c.get('/api/data?page=invalid').status_code==400
        assert c.get('/api/export/patterns.csv?min_lift=nan').status_code==400
