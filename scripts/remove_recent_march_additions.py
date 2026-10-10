"""Remove only the two user-identified March 2026 additions; retain recovery history."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from services import review_store as db
from arm.pipeline import ARMPipeline
import pandas as pd
TARGETS={'94453189edc5412d939dc184d30429ed','be751195845042019a3430dcde18e98d'}
with db.transaction() as cursor:
    rows=db.approved(cursor)
    targets=[r for r in rows if r['record_id'] in TARGETS]
    if not targets:
        print('The two requested records are already removed.')
    else:
        if len(targets)!=2 or any(r.get('source_file')!='MOTOR VEHICLE CRASH 2026 - MARCH 2026.csv' or r.get('record_revision')!=1 for r in targets):
            raise RuntimeError('Target records changed; no records were removed.')
        remaining=[r for r in rows if r['record_id'] not in TARGETS]
        candidate=ARMPipeline();candidate.data=pd.DataFrame(remaining);candidate._coerce_types(candidate.data);candidate._staging=True;candidate.run(force=True)
        for row in targets:
            db.history(cursor,row['record_id'],'administrator','record removed',row,None,reason='User requested removal of the recently added March 2026 records.')
            cursor.execute('DELETE FROM MDRRMC_RECORDS WHERE RECORD_ID=:i AND REVISION=1',i=row['record_id'])
            if cursor.rowcount!=1:raise RuntimeError('A target changed; removal rolled back.')
        cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
        print(f'Removed {len(targets)} recent additions. {len(remaining)} records remain. Recovery history retained. Analysis rebuild verified.')
