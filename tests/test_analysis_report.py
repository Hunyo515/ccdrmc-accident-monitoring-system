"""Report coverage and action wording regression checks."""
import pymupdf
from services.contextual_prescriptions import contextual_actions
from services.prescription_service import FEATURE_LABELS


def test_analysis_download_contains_requested_figures_and_exclusions():
    from app import app
    response = app.test_client().get('/api/export/analysis.pdf')
    assert response.status_code == 200
    assert 'road-accident-analysis-report.pdf' in response.headers['Content-Disposition']
    pdf = pymupdf.open(stream=response.data, filetype='pdf')
    text = '\n'.join(page.get_text() for page in pdf)
    for title in ['Road Accident Analysis Report', 'Crash records over the years',
                  'Crash records by month', 'Crash records by hour',
                  'Crash records by day of week', 'Leading recorded causes',
                  'Collision types', 'Vehicles involved',
                  'Barangays with the most crash records', 'Top barangays by day of week',
                  'Top barangays by month', 'Accident map', 'Patterns and suggested actions']:
        assert title in text
    for excluded in ['Approved records\nFatal', 'Pattern connections',
                     'Connection strength', 'Focus on records', 'leads to', 'Lift:', 'Injury details', 'injury details', 'POSO']:
        assert excluded not in text
    assert 'Barangay Tanod' in text and 'highest count' in text
    assert any(page.get_images() for page in pdf)
    # Text must remain inside the printable page, including long source URLs.
    for page in pdf:
        for word in page.get_text('words'):
            assert word[0] >= 35 and word[2] <= page.rect.width-35


def test_actions_retain_location_and_time_without_scope_filler():
    rule = {'items': [('cause','Alcohol Intake'), ('barangay','Cabugao'),
                      ('time_period','8:01PM-12MN')]}
    actions = contextual_actions(rule, FEATURE_LABELS)
    assert len(actions) == 3
    for action in actions:
        assert 'Cabugao' in action['action']
        assert '8:01 PM' in action['action']
        assert 'Focus on records' not in action['action']
    enforcement = actions[0]['action']
    assert 'POSO' not in enforcement
    assert 'PNP' in enforcement and 'sober ride' in enforcement
