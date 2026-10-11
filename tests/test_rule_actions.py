from services.rule_actions import concise_actions
from services.contextual_prescriptions import PERIODS


def test_slippery_motorcycle_night_rule_targets_surface_and_visibility():
    actions = concise_actions({'cause':'Slippery Road', 'vehicle_involved':'Single Motor',
                               'time_period':'8:01PM-12MN'}, PERIODS)
    assert 'drains' in actions[1] and 'water pooling' in actions[1]
    assert 'after dark' in actions[1]
    assert 'wet roads' in actions[2] and 'helmet' in actions[2]
    assert all(len(a.split()) < 75 for a in actions)


def test_broad_cause_uses_specific_collision_without_inventing_alcohol():
    actions = concise_actions({'cause':'Human Error', 'collision_type':'Rear-end Hit'}, PERIODS)
    assert 'queue visibility' in actions[1]
    assert 'following gaps' in actions[2]
    assert 'alcohol' not in ' '.join(actions)


def test_time_only_rule_does_not_assume_drinking_or_pedestrians():
    actions = concise_actions({'time_period':'12:01AM-4AM'}, PERIODS)
    assert 'lighting' in actions[1]
    assert 'night travel' in actions[2]
    assert not any(word in ' '.join(actions) for word in ('sober', 'helmet', 'crossing'))


def test_speed_rule_requires_assessment_not_automatic_humps():
    engineering = concise_actions({'cause':'Over Speeding'}, PERIODS)[1]
    assert 'assess' in engineering and 'road owner' in engineering
    assert 'Install' not in engineering


def test_pedestrian_context_kept_when_cause_has_priority():
    actions = concise_actions({'cause':'Loss of Control', 'vehicle_involved':'Single Motor vs Pedestrian'}, PERIODS)
    assert 'visible crossings' in actions[1]
    assert 'yield' in actions[2]


def test_motorcycle_rules_change_with_night_and_injury_evidence():
    base = {'collision_type':'Self-accident', 'vehicle_involved':'Single Motor'}
    plain = concise_actions(base, PERIODS)
    night = concise_actions(dict(base, time_period='8:01PM-12MN'), PERIODS)
    injury = concise_actions(dict(base, severity='Non-Fatal'), PERIODS)
    assert 'reflective equipment' in night[0] and 'reflective equipment' not in plain[0]
    assert 'medical assistance' in injury[0] and 'medical assistance' not in plain[0]
    assert 'Confirm roads from incident records' in plain[1]
    assert 'Patrol crash locations' not in ' '.join(plain)
    assert 'this pattern provides neither' not in plain[0]
    assert all(len(a.split()) <= 50 for a in plain)


def test_named_barangay_is_used_without_inventing_another_location():
    actions = concise_actions({'barangay':'Cabugao', 'collision_type':'Rear-end Hit'}, PERIODS)
    assert all('Cabugao' in a for a in actions)
    assert all('San Fabian' not in a for a in actions)



def test_patrol_and_social_campaign_use_rule_timing():
    actions = concise_actions({'vehicle_involved':'Single Motor', 'collision_type':'Self-accident',
                               'day':'Friday','time_period':'8:01PM-12MN'}, PERIODS)
    assert 'ronda' in actions[0] and 'motorcycle' in actions[0]
    assert 'Friday' in actions[0] and '8:01 PM' in actions[0]
    assert 'LGU and barangay Facebook pages' in actions[2] and 'helmet' in actions[2]
    assert 'before 8:01 PM' in actions[2]
    assert 'liquor ban' not in ' '.join(actions)
