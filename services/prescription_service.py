"""Match imported catalog entries and add three contextual plans per pattern.
New plans and imported catalog applicability require local expert review.
"""
from __future__ import annotations

import json
from pathlib import Path
from services.contextual_prescriptions import contextual_actions

AGENCIES = [
    {"key": "enforcement", "name": "Enforcement", "who": "Barangay Tanod / Traffic Enforcement"},
    {"key": "engineering", "name": "Engineering", "who": "LGU Engineering & Infrastructure"},
    {"key": "education", "name": "Public information & education", "who": "Public Information & Education"},
]
AGENCY_KEYS = {a["key"] for a in AGENCIES}

FEATURE_LABELS = {
    "vehicle_involved": "Vehicle",
    "collision_type": "Collision type",
    "cause": "Cause",
    "barangay": "Barangay",
    "time_period": "Time of day",
    "day": "Day of week",
    "severity": "Severity",
}

STATUS_LABELS = {
    "Implemented": "Already in place",
    "Candidate": "Not yet in place",
}

_REQUIRED = ("id", "agency", "status", "applies_when", "action", "active")


class CatalogError(ValueError):
    """Raised at startup when prescriptions.json is malformed."""


class PrescriptionCatalog:
    def __init__(self, entries: list[dict], source: str = ""):
        self.entries = entries
        self.source = source
        self.active = [e for e in entries if e["active"]]

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "PrescriptionCatalog":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CatalogError(f"Prescription catalog not found at {path}.")
        except json.JSONDecodeError as e:
            raise CatalogError(f"Prescription catalog is not valid JSON: {e}")

        entries = raw.get("prescriptions")
        if not isinstance(entries, list) or not entries:
            raise CatalogError("Prescription catalog has no 'prescriptions' list.")

        seen: set[str] = set()
        for e in entries:
            missing = [k for k in _REQUIRED if k not in e]
            if missing:
                raise CatalogError(f"Entry {e.get('id', '?')} is missing: {', '.join(missing)}.")
            if e["id"] in seen:
                raise CatalogError(f"Duplicate catalog id {e['id']}.")
            seen.add(e["id"])
            if e["agency"] not in AGENCY_KEYS:
                raise CatalogError(f"Entry {e['id']} has unknown agency '{e['agency']}'.")
            if e["active"]:
                conds = (e.get("match") or {}).get("all")
                if not conds:
                    raise CatalogError(f"Active entry {e['id']} needs a non-empty match.all list.")
                for cond in conds:
                    if cond.get("feature") not in FEATURE_LABELS:
                        raise CatalogError(f"Entry {e['id']} uses unknown field '{cond.get('feature')}'.")
            elif not e.get("inactive_reason"):
                raise CatalogError(f"Inactive entry {e['id']} must explain why in 'inactive_reason'.")
        return cls(entries, raw.get("source", ""))

    # ---- matching ------------------------------------------------------
    def match_catalog_rule(self, rule: dict) -> list[dict]:
        """Every active catalog entry that applies to this rule, with what triggered it."""
        items = [tuple(i) for i in rule.get("items", [])]
        if not items:
            return []
        hits = []
        for entry in self.active:
            matched = _match_entry(entry["match"]["all"], items)
            if matched is not None:
                hits.append(_hit(entry, matched))
        return hits

    def match_rule(self, rule: dict) -> list[dict]:
        """Exactly one contextual prescription per domain; retain catalog provenance."""
        hits = self.match_catalog_rule(rule)
        plans = contextual_actions(rule, FEATURE_LABELS)
        for plan in plans:
            plan['source_catalog_ids'] = [hit['id'] for hit in hits if hit['agency'] == plan['agency']]
        return plans

    def public_catalog(self) -> list[dict]:
        out = []
        for e in self.entries:
            out.append({
                "id": e["id"],
                "agency": e["agency"],
                "status": e["status"],
                "status_label": STATUS_LABELS.get(e["status"], e["status"]),
                "applies_when": e["applies_when"],
                "action": e["action"],
                "active": e["active"],
                "inactive_reason": e.get("inactive_reason", ""),
            })
        return out


# ---- matching helpers --------------------------------------------------
def _values_of(feature: str, value: str) -> list[str]:
    """Vehicle fields hold combinations ('Single Motor vs Tricycle'); match each part."""
    if feature == "vehicle_involved":
        return [part.strip() for part in value.split(" vs ")]
    return [value]


def _match_condition(cond: dict, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    wanted = cond.get("values")
    excluded = set(cond.get("exclude", []))
    found = []
    for feature, value in items:
        if feature != cond["feature"]:
            continue
        for part in _values_of(feature, value):
            ok = (part in wanted) if wanted else (part not in excluded)
            if ok:
                found.append((feature, value))
                break
    return found


def _match_entry(conditions: list[dict], items: list[tuple[str, str]]):
    """Returns the rule items that satisfied the entry, or None if any condition failed."""
    matched: list[tuple[str, str]] = []
    for cond in conditions:
        found = _match_condition(cond, items)
        if not found:
            return None
        for f in found:
            if f not in matched:
                matched.append(f)
    return matched


def _hit(entry: dict, matched: list[tuple[str, str]]) -> dict:
    return {
        "id": entry["id"],
        "agency": entry["agency"],
        "status": entry["status"],
        "status_label": STATUS_LABELS.get(entry["status"], entry["status"]),
        "action": entry["action"],
        "applies_when": entry["applies_when"],
        "validation_status": entry.get("validation_status", "Imported catalog · revalidation required"),
        "matched_on": [{"field": FEATURE_LABELS.get(f, f), "value": v} for f, v in matched],
    }


# ---- roll-up across many rules ----------------------------------------
def summarize(catalog: PrescriptionCatalog, rules: list[dict], top_examples: int = 3) -> dict:
    """De-duplicated list of actions for a set of rules, grouped by agency.

    Mining reports a combination in both directions (A -> B and B -> A). Both
    would trigger identical actions, so patterns are keyed by their item set and
    counted once, keeping the direction with the higher connection strength.
    """
    patterns: dict[frozenset, dict] = {}
    for r in rules:
        key = frozenset(tuple(i) for i in r.get("items", []))
        if not key:
            continue
        best = patterns.get(key)
        if best is None or (r["lift"], r["confidence"]) > (best["lift"], best["confidence"]):
            patterns[key] = r

    buckets: dict[str, dict] = {}
    for rule in patterns.values():
        for hit in catalog.match_rule(rule):
            b = buckets.setdefault(hit["id"], {**hit, "matched_on": [], "_patterns": []})
            b["_patterns"].append(rule)
            for m in hit["matched_on"]:
                if m not in b["matched_on"]:
                    b["matched_on"].append(m)

    grouped = {a["key"]: [] for a in AGENCIES}
    for b in buckets.values():
        pats = sorted(b.pop("_patterns"), key=lambda r: (r["lift"], r["confidence"]), reverse=True)
        b["pattern_count"] = len(pats)
        b["best_lift"] = pats[0]["lift"]
        b["examples"] = [
            {
                "text": f"{p['antecedent_label']} \u2192 {p['consequent_label']}",
                "confidence": p["confidence"],
                "lift": p["lift"],
            }
            for p in pats[:top_examples]
        ]
        b["matched_on"].sort(key=lambda m: (m["field"], m["value"]))
        grouped[b["agency"]].append(b)

    agencies = []
    for a in AGENCIES:
        actions = sorted(grouped[a["key"]], key=lambda x: (x["pattern_count"], x["best_lift"]), reverse=True)
        agencies.append({**a, "actions": actions})

    return {
        "agencies": agencies,
        "action_count": sum(len(a["actions"]) for a in agencies),
        "pattern_count": len(patterns),
    }


# Module-level singleton, loaded once by the app factory.
catalog: PrescriptionCatalog | None = None


def init(path: Path) -> PrescriptionCatalog:
    global catalog
    catalog = PrescriptionCatalog.load(path)
    return catalog


def get() -> PrescriptionCatalog:
    if catalog is None:
        raise CatalogError("Prescription catalog has not been loaded.")
    return catalog
