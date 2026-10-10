import pandas as pd
import pytest
from services import map_service as maps


def records():
    base = dict(year=2026, barangay='Test', severity='Non-Fatal', date='2026-01-01',
                latitude=16.70, longitude=121.68)
    return pd.DataFrame([base, dict(base, longitude=121.56),
                         dict(base, latitude=16.55, longitude=122.01),
                         dict(base, latitude=None), dict(base, latitude_imputed=True),
                         dict(base, longitude='invalid')])


def test_boundary_excludes_rectangle_false_positive_and_keeps_eastern_extent():
    points = maps.get_map_points(records())
    assert len(points) == 2
    assert points[1]['lng'] == 122.01  # Previously outside the hard-coded rectangle.
    assert all(maps.contains(p['lng'], p['lat']) for p in points)


def test_coverage_keeps_unplottable_records_in_barangay_counts():
    data = maps.map_summary(records())
    assert (data['total'], data['plotted'], data['excluded']) == (6, 2, 4)
    assert data['barangays'] == [dict(name='Test', total=6, plotted=2)]


@pytest.mark.parametrize('filters', [dict(year='2025'), dict(barangay='Absent'), dict(severity='Fatal')])
def test_filters_and_empty_results(filters):
    data = maps.map_summary(records(), **filters)
    assert data['total'] == data['plotted'] == data['excluded'] == 0
    assert data['points'] == data['barangays'] == []


def test_numeric_year_and_string_coordinates():
    df = records().iloc[:1].copy()
    df['year'] = 2026.0
    df['latitude'] = '16.70'
    assert len(maps.get_map_points(df, year='2026')) == 1


def test_polygon_edge_is_included():
    lng, lat = maps.boundary()['features'][0]['geometry']['coordinates'][0][0]
    assert maps.contains(lng, lat)


def test_barangay_area_counts_include_missing_coordinates_and_match_pob_names():
    df = records().iloc[:2].copy()
    df['barangay'] = 'Cabugao'
    df['latitude'] = None
    data = maps.map_summary(df)
    area = next(row for row in data['heat_barangays'] if row['name'] == 'Cabugao (Pob.)')
    assert area['total'] == 2
    assert data['heat_unmatched'] == 0
    assert data['plotted'] == 0


def test_barangay_filter_keeps_same_color_reference():
    df = records().iloc[:3].copy()
    df['barangay'] = ['San Fabian', 'San Fabian', 'Ipil']
    data = maps.map_summary(df, barangay='Ipil')
    assert data['heat_reference_max'] == 2
    assert sum(row['total'] for row in data['heat_barangays']) == 1


def test_unknown_barangay_is_reported_without_inventing_geometry():
    data = maps.map_summary(records())
    assert data['heat_unmatched'] == 6
    assert sum(row['total'] for row in data['heat_barangays']) == 0
    assert len(maps.barangay_boundary()['features']) == 64


def test_map_endpoints_and_local_assets(monkeypatch):
    from app import app
    from arm.pipeline import pipeline
    monkeypatch.setattr(pipeline, 'data', records())
    client = app.test_client()
    assert len(client.get('/api/map').get_json()) == 2
    assert client.get('/api/map/summary?year=2026').get_json()['excluded'] == 4
    page = client.get('/map')
    assert page.status_code == 200
    assert b'maplibre-gl.js' in page.data and b'vendor/leaflet' not in page.data
    assert client.get('/static/geo/echague.geojson').status_code == 200
    import json
    style = json.loads(client.get('/static/geo/openfreemap-liberty.json').data)
    assert style['sources']['openmaptiles']['url'] == 'https://tiles.openfreemap.org/planet'
