"""Deterministic column recognition; column position never defines meaning."""
import re
FIELDS = {
 'date':'Date of crash','time':'Time of crash','hour':'Hour','minute':'Minute','time_period':'Time period',
 'vehicle_involved':'Vehicle involved','collision_type':'Collision type','cause':'Recorded cause',
 'barangay':'Barangay','location':'Full location','severity':'Severity','damage_injury':'Injury / damage description',
 'latitude':'Latitude','longitude':'Longitude','at_user':'Road user','municipality':'Municipality','province':'Province',
 'record_id':'Unique record ID','incident_id':'Incident ID','accident_id':'Accident ID',
 'year':'Year','month':'Month','day':'Day of week',
}
ALIASES = {
 'date_of_accident':'date','accident_date':'date','incident_date':'date','crash_date':'date','date_occurred':'date',
 'time_of_accident':'time','accident_time':'time','incident_time':'time','time_occurred':'time',
 'vehicle':'vehicle_involved','vehicles_involved':'vehicle_involved','vehicle_type':'vehicle_involved',
 'type_of_collision':'collision_type','collision':'collision_type','collission_type':'collision_type',
 'probable_cause':'cause','accident_causation':'cause','causation':'cause',
 'brgy':'barangay','brgy_name':'barangay','village':'barangay','place_of_incident':'location','address':'location',
 'injury':'damage_injury','damage_injuries':'damage_injury','damage_or_injury':'damage_injury','injury_damage':'damage_injury',
 'injury_severity':'severity','outcome':'severity','lat':'latitude','lng':'longitude','lon':'longitude',
 'road_user':'at_user','case_id':'record_id','report_id':'record_id',
}

def normalized(name):
    return re.sub(r'[^a-z0-9]+','_',str(name).strip().lower()).strip('_')

def infer(name):
    key=normalized(name)
    if key in FIELDS:return key
    for field,label in FIELDS.items():
        if key==normalized(label):return field
    if key in ALIASES:return ALIASES[key]
    # Exact agency heading families from the supplied extraction notebook.
    prefixes={'exact_location':'location','at_user_involved':'at_user','other_vehicle_involved':'vehicle_involved',
              'collission_type_':'collision_type','collision_type_':'collision_type','damage_injury_':'damage_injury'}
    for prefix,target in prefixes.items():
        if key.startswith(prefix):return target
    return None

def describe(frame):
    return [dict(source=str(c),matched_field=infer(c),suggestion=infer(c) or '__keep__',
                 samples=[str(v) for v in frame[c].dropna().head(3).tolist()]) for c in frame.columns]

def apply(frame,mapping=None,drop_columns=None):
    mapping=mapping or {};drop_columns=drop_columns or []
    if not isinstance(mapping,dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in mapping.items()):
        raise ValueError('Choose a valid meaning for each column.')
    if not isinstance(drop_columns,list) or not all(isinstance(v,str) for v in drop_columns):
        raise ValueError('Choose which columns to remove.')
    if set(drop_columns)-set(frame.columns):raise ValueError('A removed column does not exist in this upload.')
    out=frame.drop(columns=drop_columns).copy();names=[]
    for c in out.columns:
        choice=mapping.get(str(c))
        if choice=='__drop__':raise ValueError('Use the remove-column selection before preparing data.')
        if choice=='__keep__':
            name=normalized(c) or 'extra_column'
            if name in FIELDS or name in ('needs_manual_review','review_notes','source_file','imported_at','source_row','record_revision','preprocessing_version'):
                name='extra_'+name
        elif choice:
            # Explicit field names are required; free-form extra names remain supported for older clients.
            name=infer(choice) or normalized(choice)
        else:
            name=infer(c) or normalized(c) or 'extra_column'
            if name in ('needs_manual_review','review_notes','source_file','imported_at','source_row','record_revision','preprocessing_version'):
                name='extra_'+name
        names.append(name)
    if len(names)!=len(set(names)):raise ValueError('Two columns have the same meaning. Keep one, or choose “Keep as extra” for the other.')
    out.columns=names
    return out
