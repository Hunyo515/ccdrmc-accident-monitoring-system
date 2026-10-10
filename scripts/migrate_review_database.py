"""Repeatable migration. Preserve each historical row, including separate casualties."""
import sys, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
import pandas as pd
from services import review_store as db, storage_service as storage

def migrate():
    db.setup()
    source=pd.read_csv(storage.CSV_PATH)
    import json
    records=json.loads(source.to_json(orient='records'))
    added=0
    with db.transaction() as cursor:
        existing={r['record_id']:r for r in db.approved(cursor)}
        for index,row in enumerate(records):
            # Deterministic row identity preserves duplicate-looking historical rows.
            rid='legacy-'+uuid.uuid5(uuid.NAMESPACE_URL, 'echague-initial-dataset:'+str(index)).hex
            if rid in existing:
                stored=existing[rid]
                if any(stored.get(k)!=v for k,v in row.items()):
                    raise ValueError('Historical rows or source file have changed. Migration stopped; use the review workflow for updates.')
                continue
            row.update(record_id=rid,record_revision=1,source_file=storage.CSV_PATH.name,preprocessing_version='historical-approved')
            db.save_record(cursor,row)
            db.history(cursor,rid,'migration','initial migration',None,row)
            added+=1
        if added:cursor.execute('UPDATE MDRRMC_STATE SET REVISION=REVISION+1 WHERE STATE_ID=1')
    print(f'Migration complete: {added} historical rows added; {len(records)} source rows. Original CSV preserved.')
if __name__=='__main__':migrate()
