"""Versioned, auditable preparation of incoming agency logs."""
import re
from functools import lru_cache
from datetime import datetime
import pandas as pd
from rapidfuzz import process, fuzz, utils
from services import upload_service as legacy, schema_service as schema

VERSION='dataset-v3'
FUZZY_THRESHOLD=85
SPARSE_THRESHOLD=.70
MODEL_FIELDS={'vehicle_involved','collision_type','cause','barangay','time_period','day','severity'}
HISTORICAL_FIELDS=['time','date','at_user','vehicle_involved','collision_type','cause','damage_injury','latitude','longitude','barangay','municipality','province','year','month','day','hour','minute','time_period','severity']
MISSING={'','nan','none','null','n/a','na','unknown','not specified','-'}
DERIVED={'year','month','day','hour','minute','time_period'}
# Conservative intake checks, not claims about clinical or legal thresholds.
NUMERIC_RANGES={'age':(0,130),'speed':(0,400),'speed_kmh':(0,400)}

def missing(v):return pd.isna(v) or str(v).strip().casefold() in MISSING

@lru_cache(maxsize=1)
def historical():
    from services.storage_service import CSV_PATH
    data=pd.read_csv(CSV_PATH)
    return data.loc[pd.to_numeric(data['year'],errors='coerce').between(2019,2025)]

def fuzzy(value, choices):
    if missing(value):return 'Unknown',None
    matches=process.extract(str(value),choices,scorer=fuzz.ratio,processor=utils.default_process,score_cutoff=FUZZY_THRESHOLD,limit=2)
    # A tied/near-tied match is not a reliable canonical label.
    if not matches or (len(matches)>1 and matches[0][1]-matches[1][1]<3):return str(value).strip(),None
    return matches[0][0],round(matches[0][1],2)

def severity(text):
    s='' if missing(text) else str(text).lower()
    if not s:return 'Unknown',True
    if re.search(r'\b(suspect\w*|possible|possibly|unconfirmed|uncertain|pending|alleged|rule out|r/o)\b|not (?:yet )?confirmed',s):return 'Unknown',True
    # Negations are handled before positive death words.
    s=re.sub(r'\b(no|without)\s+(fatalities|fatality|deaths?|injuries|injury)\b',' ',s)
    s=re.sub(r'\b(not|no|without)\s+(dead|death|fatal|injured|injury|pain|bleeding)\b',' ',s)
    s=re.sub(r'\b(?:no|without|denies|negative for)\s+(?:evidence of\s+)?(?:fractur\w*|abras\w*|lacerat\w*|contus\w*|wound\w*|bruise\w*|sprain\w*|swelling)\b',' ',s)
    nonfatal=bool(re.search(r'\bnon[ -]?fatal\b',s))
    s=re.sub(r'\bnon[ -]?fatal\b',' ',s)
    if re.search(r'\b(dead|died|deceased|fatalities|fatality|fatal|death|doa|dead on arrival)\b',s):return 'Fatal',False
    if re.search(r'\b(unresponsive|unconscious|cardiac arrest|no pulse|not breathing|casualt\w*)\b',s):return 'Unknown',True
    if nonfatal or re.search(r'\b(abras\w*|lacerat\w*|fractur\w*|contus\w*|wound\w*|bruise\w*|sprain\w*|injur\w*|swelling|pain|bleeding)\b',s):return 'Non-Fatal',False
    if re.search(r'\b(pdo|property damage|damage.to.property|damage only|damaged (vehicle|car|motorcycle))\b',s):return 'Damage-to-Property',False
    return 'Unknown',True

def datetime_value(value, order='auto'):
    if missing(value):return pd.NaT,False,False
    raw=str(value).strip();serial=False;ambiguous=False
    try:
        if re.fullmatch(r'\d{5}(?:\.\d+)?',raw):
            stamp=pd.Timestamp('1899-12-30')+pd.to_timedelta(float(raw),unit='D');stamp=stamp.round('s');serial=True
        else:
            if re.fullmatch(r'\d+(?:\.\d+)?',raw) and not re.fullmatch(r'\d{8}',raw):return pd.NaT,False,False
            match=re.match(r'^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})',raw)
            dayfirst=order=='day_first'
            if match:
                first,second=int(match[1]),int(match[2]);ambiguous=first<=12 and second<=12 and first!=second
                if first>12:dayfirst=True
                elif second>12:dayfirst=False
            stamp=pd.to_datetime(value,format='mixed',dayfirst=dayfirst,errors='coerce')
        if not pd.isna(stamp) and stamp.tzinfo:stamp=stamp.tz_localize(None)
        return stamp,serial,ambiguous
    except (ValueError,TypeError,OverflowError):return pd.NaT,serial,ambiguous

def resolve_severity(description, supplied, verified=False):
    derived,uncertain=severity(description)
    aliases={'fatal':'Fatal','non-fatal':'Non-Fatal','non fatal':'Non-Fatal','damage-to-property':'Damage-to-Property','property damage':'Damage-to-Property','property damage only':'Damage-to-Property','pdo':'Damage-to-Property'}
    supplied=aliases.get(str(supplied).strip().lower(),'Unknown')
    if verified and supplied!='Unknown':return supplied,False,'',derived,supplied
    if supplied!='Unknown' and derived!=supplied:
        return 'Unknown',True,'Supplied outcome conflicts with or is not supported by the description. Confirm the outcome.',derived,supplied
    return derived,uncertain,'Outcome needs confirmation.' if uncertain else '',derived,supplied


def run(frame, mapping=None, drops=None, order='auto', verified_severity=False):
    if order not in ('auto','day_first','month_first'):raise ValueError('Choose day/month/year or month/day/year.')
    mapped=schema.apply(frame,mapping,drops).copy()
    if 'date' not in mapped:raise ValueError('No accident date column was recognised. Rename that heading to Date and upload the file again.')
    audit=[];profiles=[];serials=ambiguous=0
    problems={i:[] for i in mapped.index};filled={i:[] for i in mapped.index}
    # Never accept imported pipeline metadata as an instruction or identity.
    mapped=mapped.drop(columns=['source_fingerprint','estimated_fields','validation_notes','derived_severity','supplied_severity'],errors='ignore')
    supplied_outcomes=mapped.get('severity',pd.Series('Unknown',index=mapped.index)).copy()
    mask=mapped.map(missing)
    # Source accident identifiers are preserved; the destination ID is allocated at commit.
    if 'accident_id' in mapped:
        target='exported_accident_id' if mapped['accident_id'].dropna().astype(str).str.fullmatch(r'ACC-\d+').all() else 'source_accident_id'
        if target in mapped:target='uploaded_accident_id'
        mapped=mapped.rename(columns={'accident_id':target})
    mapped['date']=mapped['date'].astype(object)
    if 'time' in mapped:mapped['time']=mapped['time'].astype(object)
    for index,row in mapped.iterrows():
        stamp,serial,amb=datetime_value(row.get('date'),order);serials+=int(serial);ambiguous+=int(amb)
        if amb and order=='auto':problems[index].append('Choose the date format for this file.')
        if not pd.isna(stamp):
            mapped.loc[index,'date']=stamp.strftime('%Y-%m-%d')
            native_date=isinstance(row.get('date'),datetime)
            has_time=(serial and float(str(row['date']))%1) or (native_date and (stamp.hour or stamp.minute or stamp.second)) or (not native_date and re.search(r'[T ]\d{1,2}:',str(row.get('date'))))
            if missing(row.get('time')) and has_time:
                mapped.loc[index,'time']=stamp.strftime('%H:%M:%S')
            if amb and order=='auto':mapped.loc[index,'date']=pd.NA
        # Full Excel serials and midnight fractions in the time column.
        rawtime=row.get('time')
        if not missing(rawtime) and re.fullmatch(r'\d+(?:\.\d+)?',str(rawtime).strip()):
            num=float(rawtime)
            if 0<=num<1 or 10000<=num<=100000:
                mins=round((num%1)*1440)%1440;mapped.loc[index,'time']=f'{mins//60:02}:{mins%60:02}:00'
        loc=legacy.text(row.get('location'))
        if loc:
            parts=[p.strip() for p in loc.split(',')]
            if missing(row.get('barangay')):
                area=re.sub(r'^(?:(?:PUROK|ZONE|SITIO)\s*\w+|P\s*\d+)\s*[-:]?\s*','',parts[0],flags=re.I)
                area=re.sub(r'\s+ECHAGUE(?:\s+ISABELA)?$','',area,flags=re.I)
                mapped.loc[index,'barangay']=area
            if len(parts)>1 and missing(row.get('municipality')):mapped.loc[index,'municipality']=parts[1]
            if len(parts)>2 and missing(row.get('province')):mapped.loc[index,'province']=parts[2]
    canonical={'barangay':legacy.MAPS['CANONICAL_BARANGAYS'],'cause':list(dict.fromkeys(legacy.normalize_category('cause',c) for c in legacy.MAPS['CANONICAL_CAUSES'])),'collision_type':legacy.MAPS['CANONICAL_COLLISIONS'],'vehicle_involved':legacy.MAPS['CANONICAL_VEHICLES'],'municipality':['Echague'],'province':['Isabela']}
    for column,choices in canonical.items():
        if column not in mapped:continue
        lookup={}
        for value in mapped[column].dropna().unique():
            base=legacy.normalize_category(column,value)
            if column=='vehicle_involved':
                found=[fuzzy(part,choices) for part in base.split(' vs ')];after=' vs '.join(sorted(set(v for v,_ in found)));score=min((s for _,s in found if s is not None),default=None)
            else:after,score=fuzzy(base,choices)
            lookup[value]=after
            if str(value)!=after:audit.append(dict(field=column,before=str(value),after=after,method='manual mapping / fuzzy' if score else 'manual mapping',score=score))
        mapped[column]=mapped[column].map(lambda v:lookup.get(v,'Unknown'))
    from services.dataset_service import fingerprint
    source_hashes=mapped.apply(lambda row:fingerprint(row.to_dict()),axis=1)
    # Assess new variables before imputation so missingness cannot be concealed.
    reference=historical()
    for coordinate in ('latitude','longitude'):
        if coordinate not in mapped:mapped[coordinate]=float('nan')
    for column in list(mapped.columns):
        if column in DERIVED or column.endswith('_imputed') or column.startswith('extra_') and column[6:] in ('estimated_fields','source_fingerprint','validation_notes','derived_severity','supplied_severity'):continue
        series=mapped[column];null=series.map(missing);observed=series.mask(null)
        new=column not in HISTORICAL_FIELDS
        identifier=bool(re.search(r'(^no$|number$|(^|_)id$|^source_|name|phone|contact)',column))
        numeric=pd.to_numeric(observed,errors='coerce').astype('float64').replace([float('inf'),-float('inf')],float('nan'))
        ratio=numeric.notna().sum()/max(1,observed.notna().sum())
        numeric_name=bool(re.search(r'(^|_)(age|speed|distance|duration|cost|amount|count|latitude|longitude|weight|temperature|response_minutes)($|_)',column))
        is_numeric=column not in ('date','time','damage_injury','severity') and not identifier and (numeric_name or ratio>=.8 and observed.notna().any())
        use='Active analysis' if column in MODEL_FIELDS else 'Historical schema' if not new else 'Analysis candidate'
        reason='Established analysis field' if column in MODEL_FIELDS else 'Preserved with the record'
        sparsity=float(null.mean());cardinality=int(observed.nunique())
        if new and sparsity>=SPARSE_THRESHOLD:use='Storage/Auditing Only';reason='At least 70% missing before imputation'
        elif new and not is_numeric and cardinality>max(50,len(series)*.8):use='Storage/Auditing Only';reason='High-cardinality text; retained without automatic category merging'
        if identifier:use='Storage/Auditing Only';reason='Identifier, not an analysis measurement'
        imputed=0;dtype='string'
        if is_numeric:
            invalid=numeric.abs().ge(float(2**63))
            if column in NUMERIC_RANGES:
                lo,hi=NUMERIC_RANGES[column];invalid|=numeric.notna() & ~numeric.between(lo,hi)
            for index in mapped.index[invalid]:problems[index].append(f'{column.replace("_"," ").title()} is outside the supported range; verify the value and unit.')
            numeric=numeric.mask(invalid)
            if column in ('latitude','longitude'):
                lo,hi=(-90,90) if column=='latitude' else (-180,180);numeric=numeric.where(numeric.between(lo,hi))
                previous=mapped.get(column+'_imputed',pd.Series(False,index=mapped.index)).astype(str).str.lower().isin(['true','1'])
                mapped[column+'_imputed']=numeric.isna()|previous
            median=(numeric.median() if numeric.notna().any() else pd.to_numeric(reference[column],errors='coerce').median() if column in reference else float('nan')) if column not in ('year','hour','minute','latitude','longitude') else float('nan')
            if pd.notna(median):
                for index in mapped.index[numeric.isna()]:filled[index].append(column)
                imputed=int(numeric.isna().sum());numeric=numeric.fillna(median)
            integral=column not in ('latitude','longitude') and numeric.dropna().map(lambda x:float(x).is_integer()).all() and numeric.notna().any()
            dtype='Int64' if integral else 'float64';mapped[column]=numeric.astype(dtype)
            reason+=f'; median={float(median):g}' if pd.notna(median) else '; no observed median available, null retained'
        elif column not in ('date','time','damage_injury'):
            if new and not identifier and use!='Storage/Auditing Only':
                series=series.map(lambda v:'Unknown' if missing(v) else legacy.text(v).title())
                for before in observed.dropna().unique():
                    after=legacy.text(before).title()
                    if str(before)!=after:audit.append(dict(field=column,before=str(before),after=after,method='case / whitespace',score=None))
                observed=series.mask(null)
                counts=observed.astype('string').value_counts();anchors=list(counts[counts>=2].index[:500])
                for value in counts.index:
                    if value in anchors:continue
                    after,score=fuzzy(value,anchors)
                    if score and after!=value:
                        series=series.replace(value,after);audit.append(dict(field=column,before=str(value),after=after,method='fuzzy category',score=score))
            imputed=int(null.sum());mapped[column]=series.mask(null,'Unknown').astype('string')
        profiles.append(dict(name=column,new=new,missing=int(null.sum()),missing_percent=round(sparsity*100,1),unique=cardinality,type=dtype,use=use,reason=reason,imputed=imputed,unique_after=int(mapped[column].nunique(dropna=True))))
    # Only explicit reporting fields may yield a presence feature. It records
    # documentation, not a negative clinical finding when absent.
    for column in ('alcohol_detected','helmet_observed','seatbelt_observed','hazard_reported'):
        if column in mapped and column not in HISTORICAL_FIELDS:
            profile=next(p for p in profiles if p['name']==column)
            if profile['missing_percent']>=70:
                flag=column+'_information_present'
                mapped[flag]=~mask[column]
                profiles.append(dict(name=flag,new=True,missing=0,missing_percent=0,unique=int(mapped[flag].nunique()),unique_after=int(mapped[flag].nunique()),type='boolean',use='Analysis candidate (presence flag)',reason='Information reported; absence does not mean a negative finding',imputed=0))
    # Preserve empty medical text for rule-based labeling; never mode-fill an outcome.
    clean,report=legacy.preprocess(mapped,'month_first',deduplicate=False)
    if clean.empty:raise ValueError('This file has no accident rows.')
    for col in HISTORICAL_FIELDS:
        if col not in clean:clean[col]=pd.NA if col in ('year','hour','minute','latitude','longitude') else 'Unknown'
    for p in profiles:
        col=p['name']
        if col not in DERIVED and p['type'] in ('float64','Int64'):clean[col]=pd.to_numeric(clean[col],errors='coerce').astype(p['type'])
    for col in ('year','hour','minute'):clean[col]=pd.to_numeric(clean[col],errors='coerce').astype('Int64')
    for flag in [c for c in clean if c in ('latitude_imputed','longitude_imputed') or c.endswith('_information_present')]:
        if flag in clean:clean[flag]=clean[flag].astype(str).str.lower().isin(['true','1'])
    for col in ('latitude','longitude'):clean[col]=pd.to_numeric(clean[col],errors='coerce').astype('float64')
    labels=[resolve_severity(row.get('damage_injury'),supplied_outcomes.iloc[pos],verified_severity) for pos,(_,row) in enumerate(clean.iterrows())]
    clean['severity']=[v[0] for v in labels];clean['needs_manual_review']=[v[1] for v in labels]
    clean['review_notes']=[v[2] for v in labels]
    clean['derived_severity']=[v[3] for v in labels];clean['supplied_severity']=[v[4] for v in labels]
    clean['source_fingerprint']=list(source_hashes)
    clean['estimated_fields']=[', '.join(filled[i]) for i in mapped.index]
    clean['validation_notes']=[' '.join(problems[i]) for i in mapped.index]
    ordered=HISTORICAL_FIELDS+[c for c in clean if c not in HISTORICAL_FIELDS]
    return clean[ordered],report,dict(version=VERSION,fuzzy_threshold=FUZZY_THRESHOLD,sparse_threshold=SPARSE_THRESHOLD,excel_dates_converted=serials,ambiguous_dates=ambiguous,date_choice_required=ambiguous>0 and order=='auto',date_policy='Choose a format for ambiguous numeric dates' if order=='auto' and ambiguous else order,variables=profiles,normalizations=audit)
