"""Municipal crash density; counts are not exposure-adjusted or predicted risk."""
import json
import re
from pathlib import Path
from functools import lru_cache
from collections import Counter
import pandas as pd

@lru_cache(maxsize=1)
def boundary():
    path = Path(__file__).resolve().parents[1] / 'static/geo/echague.geojson'
    return json.loads(path.read_text(encoding='utf-8-sig'))

@lru_cache(maxsize=1)
def barangay_boundary():
    path = Path(__file__).resolve().parents[1] / 'static/geo/echague-barangays.geojson'
    return json.loads(path.read_text(encoding='utf-8-sig'))

def _barangay_key(name):
    return re.sub(r'[^a-z0-9]', '', re.sub(r'\s*\(Pob\.\)', '', str(name), flags=re.I).lower())

def _polygons():
    for feature in boundary()['features']:
        geometry = feature['geometry']
        if geometry['type'] == 'Polygon':
            yield geometry['coordinates']
        elif geometry['type'] == 'MultiPolygon':
            yield from geometry['coordinates']

def bounds():
    coords = [point for polygon in _polygons() for point in polygon[0]]
    return dict(lat_min=min(p[1] for p in coords), lat_max=max(p[1] for p in coords),
                lng_min=min(p[0] for p in coords), lng_max=max(p[0] for p in coords))

ECHAGUE_BBOX = bounds()

def _in_ring(x, y, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside

def contains(lng, lat):
    return any(_in_ring(lng, lat, polygon[0]) and
               not any(_in_ring(lng, lat, hole) for hole in polygon[1:])
               for polygon in _polygons())

def _filtered(df, year='', barangay='', severity=''):
    subset = df
    if year:
        subset = subset[pd.to_numeric(subset['year'], errors='coerce') == pd.to_numeric(year, errors='coerce')]
    if barangay:
        subset = subset[subset['barangay'] == barangay]
    if severity:
        subset = subset[subset['severity'] == severity]
    return subset.copy()

def _located(subset):
    subset = subset.copy()
    for column in ('latitude', 'longitude'):
        subset[column] = pd.to_numeric(subset[column], errors='coerce')
    for flag in ('latitude_imputed', 'longitude_imputed'):
        if flag in subset:
            subset = subset.loc[~subset[flag].fillna(False).astype(str).str.lower().isin(['true', '1', '1.0'])]
    b = ECHAGUE_BBOX
    subset = subset[subset.latitude.between(b['lat_min'], b['lat_max']) &
                    subset.longitude.between(b['lng_min'], b['lng_max'])]
    keep = [contains(row.longitude, row.latitude) for row in subset.itertuples()]
    return subset.loc[pd.Series(keep, index=subset.index, dtype=bool)]

def _points(subset):
    fields = ('severity', 'barangay', 'cause', 'collision_type', 'vehicle_involved', 'date', 'time_period')
    return [dict(lat=float(row.latitude), lng=float(row.longitude),
                 **{field: '' if pd.isna(getattr(row, field, None)) else str(getattr(row, field)) for field in fields})
            for row in subset.itertuples()]

def get_map_points(df: pd.DataFrame, year='', barangay='', severity='') -> list[dict]:
    return _points(_located(_filtered(df, year, barangay, severity)))

def map_summary(df, year='', barangay='', severity=''):
    selected = _filtered(df, year, barangay, severity)
    located = _located(selected)
    plotted_counts = located.groupby('barangay').size()
    counts = selected.groupby('barangay').size().sort_values(ascending=False)
    reference = _filtered(df, year, '', severity).groupby('barangay').size()
    by_name, reference_by_name = Counter(), Counter()
    for name, count in counts.items():
        by_name[_barangay_key(name)] += int(count)
    for name, count in reference.items():
        reference_by_name[_barangay_key(name)] += int(count)
    areas = [dict(code=f['properties']['ADM4_PCODE'], name=f['properties']['ADM4_EN'],
                  total=by_name.get(_barangay_key(f['properties']['ADM4_EN']), 0))
             for f in barangay_boundary()['features']]
    known = {_barangay_key(f['properties']['ADM4_EN']) for f in barangay_boundary()['features']}
    return dict(points=_points(located), total=len(selected), plotted=len(located),
                excluded=len(selected) - len(located),
                heat_barangays=areas,
                heat_reference_max=max([reference_by_name.get(key, 0) for key in known], default=0),
                heat_unmatched=sum(count for key, count in by_name.items() if key not in known),
                barangays=[dict(name=str(name), total=int(count), plotted=int(plotted_counts.get(name, 0)))
                           for name, count in counts.items()])
