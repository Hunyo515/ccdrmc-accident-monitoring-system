"""Agency data -> auditable preview -> user verification -> persistence.
Only exact, known spelling mappings are automatic; never fuzzy-guess a cause.
"""
import io
import json
import re
from datetime import datetime, date, time
from pathlib import Path
import pandas as pd
from services.contextual_prescriptions import PERIODS
from services import schema_service

MAPS = json.loads((Path(__file__).resolve().parent.parent / 'data/normalization.json').read_text())


def parse_upload(filename, raw_bytes, sheet_name=None):
    """Read a tabular export and locate an agency header within its first 20 rows."""
    import csv
    lower=filename.lower();sheets=[];selected=None
    if lower.endswith(('.csv','.tsv')):
        try: source=raw_bytes.decode('utf-8-sig')
        except UnicodeDecodeError: source=raw_bytes.decode('cp1252')
        if lower.endswith('.tsv'): delimiter='\t'
        else:
            try: delimiter=csv.Sniffer().sniff(source[:8192],delimiters=',;\t|').delimiter
            except csv.Error: delimiter=','
        rows=list(csv.reader(io.StringIO(source),delimiter=delimiter))
        if not rows:raise ValueError('The file has no rows.')
        width=max(map(len,rows)); table=pd.DataFrame([r+['']*(width-len(r)) for r in rows])
    elif lower.endswith('.xlsx'):
        import zipfile
        try:
            with pd.ExcelFile(io.BytesIO(raw_bytes)) as book:
                sheets=book.sheet_names
                selected=sheet_name or sheets[0]
                if selected not in sheets:raise ValueError('Choose a worksheet from this file.')
                table=pd.read_excel(book,sheet_name=selected,header=None,dtype=object)
        except (ValueError,TypeError,zipfile.BadZipFile,KeyError,IndexError) as error:
            raise ValueError('This Excel file could not be read. Open it in Excel, save a new .xlsx or CSV copy, and upload that copy.') from error
    else:raise ValueError('Choose a CSV, TSV or XLSX file.')
    if table.empty:raise ValueError('This worksheet has no rows.')
    scores=[]
    for idx,row in table.head(20).iterrows():
        fields={schema_service.infer(v) for v in row if not pd.isna(v)}-{None}
        scores.append((len(fields)+(3 if 'date' in fields else 0),-idx,idx))
    best=max(scores);header=best[2] if best[0]>=2 else 0
    headers=[];seen={}
    for i,v in enumerate(table.iloc[header]):
        name=text(v) or f'Column {i+1}';seen[name]=seen.get(name,0)+1
        headers.append(name if seen[name]==1 else f'{name} [{seen[name]}]')
    frame=table.iloc[header+1:].copy();frame.columns=headers
    frame=frame.replace('',pd.NA).dropna(how='all')
    frame.attrs.update(sheet_names=sheets,selected_sheet=selected,header_row=header+1,source_row_numbers=True)
    return frame


def text(value):
    return '' if pd.isna(value) else re.sub(r'\s+',' ',str(value)).strip()


def date_value(value, order):
    if isinstance(value,(datetime,date,pd.Timestamp)): return pd.Timestamp(value).normalize()
    s=text(value)
    if re.fullmatch(r'\d{5}(?:\.0+)?',s):
        return pd.Timestamp('1899-12-30')+pd.Timedelta(days=int(float(s)))
    if re.match(r'^\d{4}-\d{2}-\d{2}T',s):
        try:return pd.Timestamp(datetime.fromisoformat(s.replace('Z','+00:00'))).tz_localize(None).normalize()
        except ValueError:return pd.NaT
    formats=['%Y-%m-%d','%Y-%m-%d %H:%M:%S','%Y/%m/%d', '%d %B %Y', '%B %d, %Y']
    formats+= ['%d/%m/%Y','%d-%m-%Y','%d.%m.%Y'] if order=='day_first' else ['%m/%d/%Y','%m-%d-%Y','%m.%d.%Y']
    for f in formats:
        try: return pd.Timestamp(datetime.strptime(s,f)).normalize()
        except ValueError: pass
    return pd.NaT


def time_value(value, hour=None, minute=None):
    if isinstance(value,(datetime,pd.Timestamp,time)): return value.hour,value.minute
    s=text(value).upper().replace('::',':').replace(';',':').replace('NN','PM').replace('MN','AM')
    if re.fullmatch(r'0?\.\d+',s):
        mins=round(float(s)*1440)%1440; return mins//60,mins%60
    if re.match(r'^\d{4}-\d{2}-\d{2}T',s):
        try:
            t=datetime.fromisoformat(s.replace('Z','+00:00')); return t.hour,t.minute
        except ValueError:return None,None
    s=re.sub(r'\s*(AM|PM)$',r' \1',s)
    for f in ('%H:%M:%S','%H:%M','%I:%M %p','%I:%M:%S %p','%I %p'):
        try:
            t=datetime.strptime(s,f); return t.hour,t.minute
        except ValueError: pass
    if not s and text(hour):
        try:
            h=float(hour); m=float(minute) if text(minute) else 0
            if h.is_integer() and m.is_integer() and 0<=h<24 and 0<=m<60: return int(h),int(m)
        except (TypeError,ValueError): pass
    return None,None


def period_for(h,m):
    if h is None: return 'Unknown'
    minutes=h*60+m
    # Match the notebooks' right-closed bins; midnight belongs to the final window.
    return list(PERIODS)[5 if minutes==0 else min((minutes-1)//240,5)]


def normalize_category(field,value):
    s=text(value)
    if not s or s.lower() in ('nan','n/a','unknown','unknown/not specified','not specified'): return 'Unknown'
    key=s.upper()
    if field=='cause':
        mapped=MAPS['CAUSE_MAP'].get(key,s)
        # Align with historical labels without splitting arbitrary slash-containing labels.
        return {'Human Error/Fast Driving':'Human Error','Reckless/Distracted Driving':'Reckless','UNKNOWN':'Unknown'}.get(mapped,{c.upper():c for c in MAPS['CANONICAL_CAUSES']}.get(mapped.upper(),mapped.title()))
    if field=='collision_type':
        key=MAPS['COLLISION_MAP'].get(key,key)
        lookup={x.upper():x for x in MAPS['CANONICAL_COLLISIONS']}
        return lookup.get(key,'Unknown' if key=='UNKNOWN' else s.title())
    if field=='vehicle_involved':
        parts=re.split(r'\s+(?:VS\.?|AND)\s+|[,/|]',key)
        lookup={x.upper():x for x in MAPS['CANONICAL_VEHICLES']}
        clean=[]
        for p in parts:
            p=MAPS['VEHICLE_TYPO_MAP'].get(p.strip(),p.strip())
            if p: clean.append(lookup.get(p,p.title()))
        return ' vs '.join(sorted(set(clean))) or 'Unknown'
    if field=='barangay':
        key=re.sub(r'^(BARANGAY|BRGY\.?)\s+','',key)
        key=MAPS['LOCATION_TYPO_MAP'].get(key,key)
        return {x.upper():x for x in MAPS['CANONICAL_BARANGAYS']}.get(key,key.title())
    return s.title()


def preprocess(frame, date_order='month_first', mapping=None, drop_columns=None, deduplicate=True):
    if date_order not in ('month_first','day_first'): raise ValueError('Choose month-first or day-first dates.')
    df=frame.copy().dropna(how='all')
    if len(df)>100000: raise ValueError('Use files with at most 100,000 rows per upload.')
    df=schema_service.apply(df,mapping,drop_columns)
    if 'date' not in df:raise ValueError('Match a column to “Date of crash” before importing. Column order does not matter.')
    # Missing categories are explicit unknowns, never inferred from column position.
    absent=[f for f in ('vehicle_involved','collision_type','cause') if f not in df]
    for f in absent:df[f]=pd.NA
    if 'barangay' not in df and 'location' not in df:df['barangay']=pd.NA
    known={'cause':{normalize_category('cause',v) for v in MAPS['CANONICAL_CAUSES']} | {'Human Error','Reckless'},
           'collision_type':set(MAPS['CANONICAL_COLLISIONS']), 'vehicle_involved':set(MAPS['CANONICAL_VEHICLES'])}
    records=[]; issues=[]; changes=[]
    for position,(index,row) in enumerate(df.iterrows(),start=2):
        rownum=int(index)+1 if frame.attrs.get("source_row_numbers") else position
        original=row.to_dict(); out={k:text(v) for k,v in original.items()}; notes=[]; errors=[]
        dt=date_value(row.get('date'),date_order)
        if pd.isna(dt): errors.append('Date is invalid for the selected date format.')
        elif dt.year<1900 or dt.date()>date.today(): errors.append('Date must be between 1900 and today.')
        else:
            out.update(date=dt.strftime('%Y-%m-%d'),year=dt.year,month=dt.strftime('%B'),day=dt.strftime('%A'))
        h,m=time_value(row.get('time'),row.get('hour'),row.get('minute'))
        supplied_period=text(row.get('time_period'))
        period_lookup={re.sub(r'\s+','',v).upper():k for k,v in PERIODS.items()}
        supplied_period=period_lookup.get(re.sub(r'\s+','',supplied_period).upper(),supplied_period)
        if h is None:
            if text(row.get('time')) or text(row.get('hour')): errors.append('Time or hour is invalid; use 24-hour time or add AM/PM.')
            if supplied_period and supplied_period not in PERIODS and supplied_period!='Unknown': errors.append('Time period is not recognised; provide a time or one of the six documented periods.')
            out.update(time='',hour=None,minute=None,time_period=supplied_period if supplied_period in PERIODS else 'Unknown')
            notes.append('Exact time unavailable; hour chart excludes this row.')
        else:
            out.update(time=f'{h:02}:{m:02}:00',hour=h,minute=m,time_period=period_for(h,m))
        if not text(row.get('barangay')):
            loc=text(row.get('location'))
            parts=[p.strip() for p in loc.split(',')]
            loc=re.sub(r'\s+Echague(?:\s*,?\s*Isabela)?\.?$','',parts[0],flags=re.I)
            out['barangay']=loc
            if len(parts)>2:
                out['municipality']=parts[1]; out['province']=parts[2]
            elif len(parts)==2 and parts[1].rstrip('.').lower()=='isabela' and re.search(r'\bEchague\b',parts[0],re.I):
                out['municipality']='Echague'; out['province']='Isabela'
            elif len(parts)>1:
                out['municipality']=parts[1]
                notes.append('Verify municipality and province parsed from the location.')

        for f in ('vehicle_involved','collision_type','cause','barangay'):
            old=out.get(f,''); out[f]=normalize_category(f,old)
            if old!=out[f] and len(changes)<100: changes.append(dict(row=rownum,field=f,before=old,after=out[f]))
            if out[f]=='Unknown': notes.append(f'{f.replace("_"," ").title()} is unknown.')
            if f in known and out[f]!='Unknown' and any(v not in known[f] for v in (out[f].split(' vs ') if f=='vehicle_involved' else [out[f]])):
                notes.append(f'New {f.replace("_"," ")} value kept; verify its meaning before import.')
        if out['barangay'] not in MAPS['CANONICAL_BARANGAYS']: notes.append('Verify barangay spelling and whether this record is in the agency’s area.')
        severity=text(row.get('severity'))
        aliases={'fatal':'Fatal','non-fatal':'Non-Fatal','non fatal':'Non-Fatal','damage-to-property':'Damage-to-Property','property damage':'Damage-to-Property','property damage only':'Damage-to-Property','pdo':'Damage-to-Property','unknown':'Unknown'}
        if severity and severity.lower() not in aliases: notes.append('Unrecognised severity retained as Unknown; verify against the original report.')
        out['severity']=aliases.get(severity.lower(),'Unknown')
        if out['severity']=='Unknown': notes.append('Severity needs verification against the report; injury text is not automatically classified.')
        for f,lo,hi in (('latitude',-90,90),('longitude',-180,180)):
            raw=text(row.get(f)); val=pd.to_numeric(raw,errors='coerce')
            if pd.isna(val) or not lo<=val<=hi:
                out[f]=None
                if raw: notes.append(f'Invalid {f} removed from map coordinates.')
            else: out[f]=float(val)
        out['needs_manual_review']=bool(notes or errors)
        out['review_notes']=' '.join(notes+errors)
        out['_source_row']=rownum
        records.append(out)
        for message in errors: issues.append(dict(row=rownum,level='error',message=message))
        for message in notes: issues.append(dict(row=rownum,level='review',message=message))
    cleaned=pd.DataFrame(records)
    duplicates=0
    if len(cleaned) and deduplicate:
        keys=[c for c in cleaned if c not in ('_source_row','review_notes','needs_manual_review')]
        duplicate_mask=cleaned.duplicated(subset=keys)
        duplicates=int(duplicate_mask.sum()); cleaned=cleaned.loc[~duplicate_mask].reset_index(drop=True)
    report=dict(input_rows=len(frame),cleaned_rows=len(cleaned),duplicates_removed=duplicates,
        error_count=sum(i['level']=='error' for i in issues),review_count=sum(bool(r['needs_manual_review']) for r in records),
        issues=issues[:200],issues_truncated=len(issues)>200,invalid_rows=sorted({i['row'] for i in issues if i['level']=='error'}),changes=changes,date_order=date_order,
        missing_fields=absent,
        note='Exact duplicate rows are removed within this upload. Separate casualty rows remain separate records. Missing causes and severity are not guessed.')
    return cleaned,report


def validate(df):
    return ['The file has no data rows.'] if df.empty else []


def prepare_for_append(df, existing_columns):
    return df.drop(columns=['_source_row'],errors='ignore').copy()


def preview_payload(df,report):
    return dict(report=report,columns=list(df.columns),preview=json.loads(df.head(50).to_json(orient='records',date_format='iso')),preview_limit=50)
