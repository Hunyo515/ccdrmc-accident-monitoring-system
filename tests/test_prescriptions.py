"""Tests for catalog loading, rule matching and the API. Run: python -m pytest tests -q"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from services import prescription_service as ps  # noqa: E402


def rule(*items, lift=1.5, conf=0.5):
    labels = [v for _, v in items]
    return {
        "items": [list(i) for i in items], "antecedents": labels[:1], "consequents": labels[1:],
        "antecedent_label": labels[0], "consequent_label": " & ".join(labels[1:]),
        "support": 0.05, "confidence": conf, "lift": lift,
    }


@pytest.fixture(scope="module")
def cat():
    return ps.PrescriptionCatalog.load(ROOT / "data" / "prescriptions.json")


def ids(hits):
    return {h["id"] for h in hits}


def test_catalog_counts(cat):
    assert len(cat.entries) == 34
    assert len(cat.active) == 26


def test_cause_matches_on_either_side(cat):
    a = rule(("cause", "Alcohol Intake"), ("collision_type", "Self-accident"))
    b = rule(("collision_type", "Self-accident"), ("cause", "Alcohol Intake"))
    assert {"ENF-02", "IEC-03"} <= ids(cat.match_catalog_rule(a))
    assert ids(cat.match_catalog_rule(a)) == ids(cat.match_catalog_rule(b))


def test_vehicle_combination_matches_each_part(cat):
    hits = ids(cat.match_catalog_rule(rule(("collision_type", "Head-on Hit"), ("vehicle_involved", "Single Motor vs Tricycle"))))
    assert {"ENG-02", "ENF-05", "IEC-09"} <= hits


def test_feature_is_respected(cat):
    # "Collision" as a collision type must not trigger anything written for a cause.
    hits = ids(cat.match_catalog_rule(rule(("collision_type", "Collision"), ("barangay", "Cabugao"))))
    assert "IEC-01" not in hits and "ENF-04" in hits


def test_unknown_cause_is_ignored(cat):
    assert "IEC-01" not in ids(cat.match_catalog_rule(rule(("cause", "Unknown"), ("barangay", "Cabugao"))))


def test_compound_trigger_needs_every_condition(cat):
    only_day = rule(("day", "Friday"), ("collision_type", "Head-on Hit"))
    both = rule(("day", "Friday"), ("time_period", "8:01PM-12MN"))
    assert "ENF-03" not in ids(cat.match_catalog_rule(only_day))
    assert "ENF-03" in ids(cat.match_catalog_rule(both))


def test_no_legacy_match_still_has_three_contextual_domains(cat):
    hits=cat.match_rule(rule(("time_period", "12:01PM-4PM"), ("collision_type", "Unknown")))
    assert len(hits)==3 and all(h.get("contextual") for h in hits)


def test_inactive_entries_never_match(cat):
    inactive = {e["id"] for e in cat.entries if not e["active"]}
    everything = [rule(("cause", c), ("vehicle_involved", "Single Motor")) for c in
                  ["Loss of Control", "Wrong Overtaking", "Alcohol Intake"]]
    for r in everything:
        assert not (ids(cat.match_catalog_rule(r)) & inactive)


def test_mirrored_rules_count_once(cat):
    ab = rule(("cause", "Alcohol Intake"), ("barangay", "Cabugao"), lift=1.4)
    ba = rule(("barangay", "Cabugao"), ("cause", "Alcohol Intake"), lift=1.4)
    out = ps.summarize(cat, [ab, ba])
    assert out["pattern_count"] == 1
    for ag in out["agencies"]:
        for a in ag["actions"]:
            assert a["pattern_count"] == 1


def test_bad_catalog_is_rejected(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({"prescriptions": [
        {"id": "X-1", "agency": "enforcement", "status": "Candidate", "applies_when": "a", "action": "b", "active": True}
    ]}))
    with pytest.raises(ps.CatalogError):
        ps.PrescriptionCatalog.load(bad)


def test_every_entry_in_the_file_is_well_formed(cat):
    for e in cat.entries:
        assert e["action"].strip() and e["applies_when"].strip()
        assert e["active"] or e["inactive_reason"]


@pytest.fixture
def client():
    from app import app
    return app.test_client()


def test_api_rules_include_actions_and_hide_items(client):
    data = client.get("/api/rules?min_support=0.05&min_lift=1&limit=10").get_json()
    assert data["rules"] and all("actions" in r and "items" not in r for r in data["rules"])


def test_api_only_with_actions(client):
    data = client.get("/api/rules?min_lift=1&limit=200&only_with_actions=1").get_json()
    assert data["total"] > 0 and all(r["actions"] for r in data["rules"])


def test_api_rollup_shrinks_when_thresholds_tighten(client):
    loose = client.get("/api/rules/actions?min_support=0.05&min_lift=1").get_json()
    tight = client.get("/api/rules/actions?min_support=0.05&min_lift=2").get_json()
    assert tight["action_count"] < loose["action_count"]
    assert tight["pattern_count"] < loose["pattern_count"]


def test_removed_scenario_routes(client):
    assert client.post("/api/scenario", json={}).status_code == 404
    assert client.get("/advisor").status_code == 404


def test_pages_render(client):
    for path in ["/explorer", "/data", "/upload"]:
        assert client.get(path).status_code == 200
