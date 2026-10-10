"""Read-only alpha probes. Writes evidence files, never production records."""
import os,sys,json,time,io
from pathlib import Path
os.environ['DATA_BACKEND']='csv'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from services import dataset_service as ds, incoming_pipeline as eng, upload_service as upload
OUT=Path(__file__).resolve().parents[1]/'tmp/alpha';OUT.mkdir(parents=True,exist_ok=True)
results=[]
def record(**kwargs):
    r=dict(date='2026-03-01',time='19:20',barangay='Ipil',vehicle_involved='motorcycle',collision_type='self accident',cause='loss of control',damage_injury='abrasion')
    r.update(kwargs);return r

def probe(name,expected,fn):
    start=time.perf_counter()
    try:actual=fn()
    except Exception as e:actual={'exception':type(e).__name__,'message':str(e)}
    results.append(dict(name=name,expected=expected,actual=actual,seconds=round(time.perf_counter()-start,3)))

def clean(**kw):return ds.prepare(pd.DataFrame([record(**kw)]))['items'][0]['cleaned']
probe('negated_injury','No fracture should not confirm an injury outcome',lambda:eng.severity('no fracture'))
probe('uncertain_fatality','Suspected fatality should require verification',lambda:eng.severity('suspected fatal injury, outcome not confirmed'))
probe('manual_severity_overwrite','An explicit conflicting outcome must not be silently replaced',lambda:clean(severity='Fatal')['severity'])
probe('damage_type_erasure','New categorical damage_type values must survive',lambda:{k:v for k,v in clean(damage_type='Scratched bumper').items() if k=='damage_type'})
probe('numeric_month_erasure','Derived month should remain March',lambda:clean(month=3)['month'])
probe('date_only_excel_midnight','Date-only Excel cell must not fabricate an accident time',lambda:{'excel':clean(date=pd.Timestamp('2026-03-01'),time=None)['time'],'csv':clean(time=None)['time']})
probe('mixed_numeric_date_policy','Known day-first fixture should remain April 3 / April 25',lambda:[e['cleaned']['date'] for e in ds.prepare(pd.DataFrame([record(date='03/04/2026'),record(date='25/04/2026')]))['items']])
probe('missingness_disagreement','Summary and profile should explain semantic missingness consistently',lambda:(lambda p:{'summary_missing':p['stats']['missing_values'],'weather_profile':next(v for v in p['stats']['variables'] if v['name']=='weather')['missing']})(ds.prepare(pd.DataFrame([record(weather='N/A')]))))
probe('numeric_range','Negative age and implausible speed should be flagged',lambda:(lambda p:{'status':ds.assess(p,[])['items'][0]['status'],'age':p['items'][0]['cleaned']['age'],'speed':p['items'][0]['cleaned']['speed']})(ds.prepare(pd.DataFrame([record(age=-5,speed=900)]))))
def duplicate():
    a=record(incident_id='SAME-SOURCE',speed=None)
    first=ds.prepare(pd.DataFrame([a,record(incident_id='OTHER-A',speed=20)]))
    again=ds.prepare(pd.DataFrame([a,record(incident_id='OTHER-B',speed=80)]))
    existing=dict(first['items'][0]['cleaned'],record_id='stored')
    return {'first_speed':existing['speed'],'repeat_speed':again['items'][0]['cleaned']['speed'],'repeat_status':ds.assess(again,[existing])['items'][0]['status']}
probe('batch_dependent_duplicate','Same source row should not be imported again because a median changed',duplicate)
probe('integer_overflow','Oversized numeric values should yield a controlled validation response',lambda:clean(age='999999999999999999999999999'))
# HTTP checks use an isolated app and no database connection.
from app import app
from services import review_store as db
db.rows=lambda:[]
app.logger.disabled=True
client=app.test_client()
with client.session_transaction() as session:session['authenticated']=True;session['csrf_token']='alpha-token'
headers={'X-CSRF-Token':'alpha-token'}
probe('invalid_xlsx_response','400 with readable file validation error',lambda:{'http':(r:=client.post('/api/dataset/inspect',data={'file':(io.BytesIO(b'not an excel file'),'broken.xlsx')},headers=headers)).status_code,'json':r.json})
def tabs():
    def inspect(name):return client.post('/api/dataset/inspect',data={'file':(io.BytesIO(pd.DataFrame([record()]).to_csv(index=False).encode()),name)},headers=headers).json['source_token']
    first=inspect('first.csv');inspect('second.csv')
    r=client.post('/api/dataset/prepare',json={'source_token':first},headers=headers)
    return {'http':r.status_code,'body':r.json}
probe('second_upload_invalidates_first','Other-tab upload should not silently destroy an active preview',tabs)
def http_overflow():
    data=pd.DataFrame([record(age='999999999999999999999999999')]).to_csv(index=False).encode()
    source=client.post('/api/dataset/inspect',data={'file':(io.BytesIO(data),'oversized.csv')},headers=headers).json['source_token']
    response=client.post('/api/dataset/prepare',json={'source_token':source},headers=headers)
    return {'http':response.status_code,'json':response.is_json}
probe('integer_overflow_http','A bad numeric value must not cause a server error',http_overflow)
def excel_date_only():
    data=io.BytesIO()
    pd.DataFrame([record(date=pd.Timestamp('2026-03-01'),time=None)]).to_excel(data,index=False)
    frame=upload.parse_upload('date-only.xlsx',data.getvalue())
    prepared=ds.prepare(frame)
    return {'parsed_date_type':type(frame.iloc[0]['date']).__name__,'cleaned_time':prepared['items'][0]['cleaned']['time'],'time_period':prepared['items'][0]['cleaned']['time_period']}
probe('actual_excel_missing_time','An Excel date-only cell must preserve unknown time',excel_date_only)
for size in (150,1000):
    probe(f'prepare_{size}_rows','Interactive processing benchmark (not a concurrency/load test)',lambda size=size:{'rows':len(ds.prepare(pd.DataFrame([record(incident_id=str(i)) for i in range(size)]))['items'])})
(OUT/'probe-results.json').write_text(json.dumps(results,indent=2,default=str),encoding='utf-8')
print(json.dumps(results,indent=2,default=str))
