"""Live Oracle integration checks. Every test rolls back all database changes."""
import os
from contextlib import contextmanager
import pandas as pd
import pytest
from services import review_service as review, review_store as db, storage_service as storage
from test_review import row

pytestmark=pytest.mark.skipif(os.getenv('ORACLE_INTEGRATION_TESTS')!='1',reason='Set ORACLE_INTEGRATION_TESTS=1 for rollback-only local Oracle checks.')

@pytest.fixture
def oracle(monkeypatch):
    from arm.pipeline import pipeline
    real=storage.connect()
    original=(pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta)
    class BorrowedConnection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def cursor(self):return real.cursor()
    monkeypatch.setattr(storage,'connect',lambda:BorrowedConnection())
    monkeypatch.setenv('DATA_BACKEND','oracle')
    @contextmanager
    def transaction():
        with real.cursor() as cursor:
            cursor.execute('SAVEPOINT review_test_operation')
            cursor.execute('SELECT REVISION FROM MDRRMC_STATE WHERE STATE_ID=1 FOR UPDATE WAIT 10');cursor.fetchone()
            try:yield cursor
            except Exception:
                cursor.execute('ROLLBACK TO review_test_operation')
                raise
    monkeypatch.setattr(db,'transaction',transaction)
    try:yield real
    finally:
        real.rollback();real.close()
        pipeline.data,pipeline.rules,pipeline.itemsets,pipeline.meta=original


def verify(batch,draft,**kwargs):
    body=dict(revision=draft['revision'],raw=draft['raw'],reviewed=True,decision='separate')
    body.update(kwargs)
    return review.update_draft(batch,draft['id'],body,'integration-test')


def test_partial_approval_persists_unresolved_and_updates_analysis(oracle):
    from arm.pipeline import pipeline
    before=len(storage.load())
    batch=review.create_batch(pd.DataFrame([row(),row(severity='',damage_injury='unknown wording')]),'integration-test.csv','integration-test')
    drafts=review.get_batch(batch)
    for d in drafts:verify(batch,d)
    result=review.approve(batch,'integration-test')
    assert result['added']==1 and result['pending']==1
    assert len(storage.load())==before+1 and len(pipeline.data)==before+1
    assert sum(d['status']=='pending' for d in review.get_batch(batch))==1
    assert review.approve(batch,'integration-test')['added']==0


def test_edit_waits_for_approval_then_records_history(oracle):
    original=storage.load().iloc[0].to_dict()
    # JSON-safe source is fetched from the Oracle payload, not pandas NaN fields.
    original=next(r for r in db.rows() if r['record_id']==original['record_id'])
    with oracle.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM MDRRMC_HISTORY WHERE RECORD_ID=:i AND ACTION='update approved'",i=original['record_id'])
        prior_updates=cursor.fetchone()[0]
    raw={k:v for k,v in original.items() if k not in ('record_id','record_revision','review_notes','needs_manual_review')}
    raw.update(date='2026-10-01',time='20:30',severity='Non-Fatal')
    batch=review.create_batch(pd.DataFrame([raw]),'Edit test','integration-test',target=original['record_id'])
    d=review.get_batch(batch)[0]
    verify(batch,d,raw=dict(raw,cause='Loss of Control'),decision='update',target_id=original['record_id'],target_revision=original['record_revision'])
    assert next(r for r in db.rows() if r['record_id']==original['record_id'])==original
    result=review.approve(batch,'integration-test')
    updated=next(r for r in db.rows() if r['record_id']==original['record_id'])
    assert result['updated']==1 and updated['record_revision']==original['record_revision']+1
    with oracle.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM MDRRMC_HISTORY WHERE RECORD_ID=:i AND ACTION='update approved'",i=original['record_id'])
        assert cursor.fetchone()[0]==prior_updates+1


def test_mining_failure_rolls_back_records_and_draft_status(oracle,monkeypatch):
    from arm.pipeline import ARMPipeline, pipeline
    batch=review.create_batch(pd.DataFrame([row()]),'Rollback test','integration-test')
    verify(batch,review.get_batch(batch)[0]);before=len(db.rows());old_data=pipeline.data
    def fail(*args,**kwargs):raise RuntimeError('Simulated mining failure')
    monkeypatch.setattr(ARMPipeline,'run',fail)
    with pytest.raises(RuntimeError):review.approve(batch,'integration-test')
    assert len(db.rows())==before
    assert review.get_batch(batch)[0]['status']=='pending'
    assert pipeline.data is old_data


def test_duplicate_decisions_and_stale_draft_revision(oracle):
    source=next(r for r in db.rows() if r.get('severity')=='Non-Fatal')
    source={k:v for k,v in source.items() if k not in ('record_id','record_revision')}
    batch=review.create_batch(pd.DataFrame([source,source]),'Duplicate test','integration-test')
    a,b=review.get_batch(batch)
    a2=verify(batch,a,decision='skip')
    with pytest.raises(review.Conflict):verify(batch,a)
    verify(batch,b,decision='separate')
    result=review.approve(batch,'integration-test')
    assert result['skipped']==1 and result['added']==1


def test_http_staging_requires_review_and_rejects_legacy_confirm(oracle):
    import io
    from app import app
    client=app.test_client()
    content=pd.DataFrame([row(weather='Rainy')]).to_csv(index=False).encode()
    response=client.post('/api/upload/inspect',data={'file':(io.BytesIO(content),'integration.csv')})
    assert response.status_code==200
    token=response.json['source_token']
    staged=client.post('/api/review/stage-upload',json={'source_token':token,'date_order':'month_first'})
    assert staged.status_code==200
    drafts=client.get('/api/review/'+staged.json['batch_id']).json['rows']
    assert drafts[0]['cleaned']['weather']=='Rainy' and not drafts[0]['reviewed']
    assert client.post('/api/upload/confirm',json={'reviewed':True}).status_code==409


def test_dataset_import_adds_valid_rows_atomically(oracle):
    from services import dataset_service as dataset
    from arm.pipeline import pipeline
    import uuid
    before=len(db.rows());marker=uuid.uuid4().hex
    frame=pd.DataFrame([row(incident_id=marker),row(incident_id=marker),row(date='invalid',incident_id=marker+'bad')])
    prepared=dataset.prepare(frame)
    result=dataset.publish(prepared,'integration-dataset.csv',frame.to_csv(index=False).encode(),'integration-test',uuid.uuid4().hex)
    assert result['added']==1 and result['stats']['duplicates_skipped']==1 and result['stats']['excluded']==1
    assert len(db.rows())==before+1 and len(pipeline.data)==before+1
    assert dataset.assess(prepared,db.rows())['stats']['ready']==0


def test_dataset_mining_failure_rolls_back(oracle,monkeypatch):
    from services import dataset_service as dataset
    from arm.pipeline import ARMPipeline,pipeline
    import uuid
    prepared=dataset.prepare(pd.DataFrame([row(incident_id=uuid.uuid4().hex)]))
    before=len(db.rows());original=pipeline.data
    def fail(*args,**kwargs):raise RuntimeError('Dataset mining failed')
    monkeypatch.setattr(ARMPipeline,'run',fail)
    with pytest.raises(RuntimeError):dataset.publish(prepared,'rollback.csv',None,'integration-test',uuid.uuid4().hex)
    assert len(db.rows())==before and pipeline.data is original


def test_dataset_http_pagination_ownership_and_retry(oracle):
    import io,uuid
    from app import app
    client=app.test_client();marker=uuid.uuid4().hex
    frame=pd.DataFrame([row(incident_id=marker+str(i)) for i in range(26)])
    response=client.post('/api/upload/inspect',data={'file':(io.BytesIO(frame.to_csv(index=False).encode()),'integration.csv')})
    body=dict(source_token=response.json['source_token'])
    prepared=client.post('/api/dataset/prepare',json=body)
    assert prepared.status_code==200
    body['preview_token']=prepared.json['preview_token']
    result=client.post('/api/dataset/rows',json=dict(body,page_size=25,page=2,view='original'))
    assert result.json['total']==26 and len(result.json['rows'])==1
    assert app.test_client().post('/api/dataset/rows',json=body).status_code==400
    assert client.post('/api/dataset/import',json=dict(body,preview_token='stale')).status_code==400
    first=client.post('/api/dataset/import',json=body)
    assert first.status_code==200 and first.json['added']==26
    second=client.post('/api/dataset/import',json=body)
    assert second.json==first.json


def test_sequential_accident_ids_and_typed_values(oracle):
    import uuid
    from services import dataset_service as dataset
    marker=uuid.uuid4().hex
    a=dataset.prepare(pd.DataFrame([row(incident_id=marker+'a'),row(incident_id=marker+'b')]))
    dataset.publish(a,'id-test.csv',None,'integration-test',uuid.uuid4().hex)
    saved=[r for r in db.rows() if r.get('incident_id') in (marker+'a',marker+'b')]
    ids=sorted(int(r['accident_id'].split('-')[1]) for r in saved)
    assert len(ids)==2 and ids[1]==ids[0]+1
    b=dataset.prepare(pd.DataFrame([row(incident_id=marker+'c')]))
    dataset.publish(b,'id-test-next.csv',None,'integration-test',uuid.uuid4().hex)
    later=next(r for r in db.rows() if r.get('incident_id')==marker+'c')
    assert int(later['accident_id'].split('-')[1])==ids[1]+1
    assert isinstance(later['year'],int) and isinstance(later['needs_manual_review'],bool)


def test_import_receipt_downloads_and_guarded_undo(oracle):
    import uuid
    from services import dataset_service as dataset,import_history
    from app import app
    marker=uuid.uuid4().hex;batch=uuid.uuid4().hex;before=len(db.rows())
    frame=pd.DataFrame([row(incident_id=marker),row(date='bad',incident_id=marker+'bad')])
    raw=frame.to_csv(index=False).encode()
    dataset.publish(dataset.prepare(frame),'recoverable.csv',raw,'integration-test',batch)
    receipt=next(b for b in import_history.list_imports()['imports'] if b['id']==batch)
    assert receipt['added']==1 and receipt['excluded']==1 and not receipt['reversed']
    excluded=import_history.excluded_rows(batch)
    assert excluded[0]['original']['date']=='bad'
    client=app.test_client()
    assert client.get(f'/api/dataset/history/{batch}/original').data==raw
    assert b'bad' in client.get(f'/api/dataset/history/{batch}/excluded').data
    assert client.post(f'/api/dataset/history/{batch}/undo',json={}).status_code==400
    assert import_history.reverse(batch,'integration-test')['removed']==1
    assert len(db.rows())==before
    assert client.get(f'/api/dataset/history/{batch}/original').data==raw
    with pytest.raises(ValueError,match='already been undone'):import_history.reverse(batch,'integration-test')


def test_direct_edit_uses_pipeline_retains_identity_and_blocks_undo(oracle):
    import uuid
    from services import dataset_service as dataset,import_history
    marker=uuid.uuid4().hex;batch=uuid.uuid4().hex
    dataset.publish(dataset.prepare(pd.DataFrame([row(incident_id=marker,weather='Rainy')])), 'edit-alpha.csv',None,'integration-test',batch)
    saved=next(r for r in db.rows() if r.get('incident_id')==marker)
    result=dataset.update_record(saved['record_id'],dict(saved,weather='Clear',damage_type='Scratched bumper'),1,'integration-test')
    edited=result['record']
    assert edited['record_revision']==2 and edited['accident_id']==saved['accident_id']
    assert edited['weather']=='Clear' and edited['damage_type']=='Scratched Bumper' and edited['month']=='October'
    with pytest.raises(review.Conflict):dataset.update_record(saved['record_id'],saved,1,'integration-test')
    with pytest.raises(ValueError,match='changed since'):import_history.reverse(batch,'integration-test')
    assert next(r for r in db.rows() if r['record_id']==saved['record_id'])==edited


def test_undo_mining_failure_rolls_back(oracle,monkeypatch):
    import uuid
    from services import dataset_service as dataset,import_history
    from arm.pipeline import ARMPipeline,pipeline
    batch=uuid.uuid4().hex
    dataset.publish(dataset.prepare(pd.DataFrame([row(incident_id=uuid.uuid4().hex)])),'undo-rollback.csv',None,'integration-test',batch)
    before=len(db.rows());snapshot=pipeline.data
    def fail(*args,**kwargs):raise RuntimeError('Undo mining failed')
    monkeypatch.setattr(ARMPipeline,'run',fail)
    with pytest.raises(RuntimeError):import_history.reverse(batch,'integration-test')
    assert len(db.rows())==before and pipeline.data is snapshot
    assert not next(b for b in import_history.list_imports()['imports'] if b['id']==batch)['reversed']
