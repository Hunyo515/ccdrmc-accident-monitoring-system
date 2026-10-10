"""CSV reporting over one consistent dataset snapshot."""
import csv
import io
import json
from datetime import datetime, timezone
import pandas as pd
from services import overview_service, rules_service, prescription_service, map_service


def safe_cell(value):
    if value is None:return ''
    if isinstance(value,(dict,list,tuple)):value=json.dumps(value,ensure_ascii=False)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')):return "'"+value
    return value


def csv_bytes(rows,columns):
    output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=columns,extrasaction='ignore')
    writer.writeheader()
    for row in rows:writer.writerow({k:safe_cell(v) for k,v in row.items()})
    return output.getvalue().encode('utf-8-sig')


def filtered_data(df,filters,search=''):
    if filters.get('date_from') and filters.get('date_to') and filters['date_from']>filters['date_to']:
        raise ValueError('The start date must not follow the end date.')
    result=overview_service._apply_filters(df,filters,include_year_range=True)
    for key,op in [('date_from','ge'),('date_to','le')]:
        if filters.get(key):
            dates=pd.to_datetime(result['date'],errors='coerce',format='mixed')
            boundary=pd.to_datetime(filters[key],errors='raise')
            result=result[getattr(dates,op)(boundary)]
    if filters.get('severity'):
        result=result[result['severity']==filters['severity']]
    if search:
        text=result.astype('string').fillna('')
        mask=text.apply(lambda col:col.str.contains(search,case=False,regex=False)).any(axis=1)
        result=result[mask]
    return result


def records(df):
    return json.loads(df.to_json(orient='records',date_format='iso'))


def pattern_rows(rules,thresholds):
    filtered,_=rules_service.filter_rules(rules,**thresholds,limit=len(rules))
    cat=prescription_service.get();out=[]
    for r in filtered:
        actions={a['agency']:a['action'] for a in cat.match_rule(r)}
        out.append(dict(conditions=r['antecedent_label'],outcome=r['consequent_label'],
            support=r['support'],confidence=r['confidence'],lift=r['lift'],
            enforcement=actions.get('enforcement',''),engineering=actions.get('engineering',''),
            public_information_education=actions.get('education',''),validation='Pending expert validation'))
    return out

PATTERN_COLUMNS=['conditions','outcome','support','confidence','lift','enforcement','engineering','public_information_education','validation']
METRIC_LABELS={'total_accidents':'Total crash records','fatal_count':'Fatal records','non_fatal_count':'Non-fatal injury records','property_damage_count':'Property damage records','unknown_severity_count':'Records with unknown severity','fatal_rate_pct':'Fatal records as a percentage','top_cause':'Most frequent recorded cause','top_cause_count':'Records for most frequent cause','top_barangay':'Barangay with most records','top_barangay_count':'Records in leading barangay','year_range':'Years included','count':'Total records','fatal':'Fatal records','non_fatal':'Non-fatal injury records','property_damage':'Property damage records','unknown':'Unknown severity','n_transactions':'Records used for mining','n_rules':'Mined rules before display filters','mined_at':'Patterns last rebuilt','min_support':'Minimum share of records','algorithm':'Pattern method'}
REPORT_COLUMNS=['section','metric','category','series','value','unit','scope']+PATTERN_COLUMNS+['generated_at_utc','dataset_revision','filters']


def analysis_report(df,rules,meta,filters):
    generated=datetime.now(timezone.utc).isoformat(timespec='seconds');rows=[]
    scope=json.dumps({k:v for k,v in filters.items() if v is not None},sort_keys=True)
    def add(section,metric,category='',series='',value='',unit='records',source_scope='Selected dashboard filters',**extra):
        rows.append(dict(section=section,metric=METRIC_LABELS.get(metric,metric.replace("_"," ").capitalize()),category=category,series=series,value=value,unit=unit,
            scope=source_scope,generated_at_utc=generated,dataset_revision=meta.get('dataset_revision',''),filters=scope,**extra))
    add('Report notes','Counting unit',value='Counts are submitted records, not guaranteed unique crashes.',unit='text')
    add('Report notes','Pattern scope',value='Patterns use the full working dataset with support >= 0.05, confidence >= 0.60 and lift >= 1.20. Dashboard date/category filters apply to overview sections only.',unit='text',source_scope='Full dataset')
    add('Report notes','Interpretation',value='Associations do not prove causation. Recent years may be incomplete. Prescriptions require expert validation.',unit='text')
    for key in ('n_transactions','n_rules','mined_at','min_support','algorithm'):
        add('Model',key,value=meta.get(key,''),unit='model metadata',source_scope='Full dataset')
    overview=overview_service.build_overview(df,filters)
    for key,value in overview['kpis'].items():
        if key=='time_period':
            add('Overview','Most frequent crash time',category=value['label'],value=value['count'])
        else:add('Overview',key,value=value,unit='percent' if key=='fatal_rate_pct' else ('text' if isinstance(value,str) else 'records'))
    for key,value in overview['fatality_trend'].items():
        add('Fatal record trend',key,value=value,unit='text' if isinstance(value,str) else 'value',source_scope='Selected categories; comparison may include prior year outside selected range')
    sections={'hourly_distribution':'By hour','day_distribution':'By weekday','month_distribution':'By month',
              'top_causes':'Leading causes','top_barangays':'Top 5 barangays','top_vehicles':'Top 10 vehicles','collision_types':'Collision types'}
    for key,label in sections.items():
        for row in overview[key]:
            for measure in ('count','fatal','non_fatal','property_damage','unknown'):
                add(label,measure,category=row['label'],value=row[measure])
    for row in overview['yearly_trend']:add('By year','count',category=row['year'],value=row['count'])
    breakdown=overview_service.build_barangay_breakdown(df,filters)
    for kind,axis,label in [('by_day','days','Top 5 barangays by weekday'),('by_month','months','Top 5 barangays by month')]:
        for barangay,counts in breakdown[kind].items():
            for category,count in zip(breakdown[axis],counts):add(label,'count',category=category,series=barangay,value=count)
    subset=filtered_data(df,filters)
    points=map_service.get_map_points(subset)
    add('Map','Records with usable coordinates in Echague',value=len(points))
    add('Map','Records not plotted',value=len(subset)-len(points))
    for p in pattern_rows(rules,{}):add('Patterns','Association rule',unit='rule',source_scope='Full dataset; default thresholds',**p)
    filtered,_=rules_service.filter_rules(rules,limit=len(rules))
    for r in filtered[:18]:
        add('Pattern network','Connection',category=r['antecedent_label'],series=r['consequent_label'],value=r['lift'],unit='lift',source_scope='Full dataset; top 18 default-threshold rules')
    heat=rules_service.heatmap_data(filtered)
    for i,a in enumerate(heat['antecedents']):
        for j,c in enumerate(heat['consequents']):
            if heat['matrix'][i][j] is not None:add('Pattern heatmap','Connection',category=a,series=c,value=heat['matrix'][i][j],unit='lift',source_scope='Full dataset; single-condition default-threshold rules')
    return csv_bytes(rows,REPORT_COLUMNS)
