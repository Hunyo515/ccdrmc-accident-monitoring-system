"""One-time converter: expert-validated Word catalog -> data/prescriptions.json.

Usage: python scripts/build_prescription_catalog.py path/to/CCDRMC-Prescription-Catalog-Validation.docx

The wording of every action and its "applies when" text is copied from the
Word file as-is. This script only adds the machine-readable `match` rule that
lets the system test a mined pattern against each entry. Entries whose trigger
needs data the dataset does not hold stay in the file, marked inactive with the
reason, so nothing the panel validated is lost.
"""
import json
import sys
from pathlib import Path

import docx

OUT = Path(__file__).resolve().parent.parent / "data" / "prescriptions.json"

WEEKEND = ["Friday", "Saturday", "Sunday"]
NIGHT = ["8:01PM-12MN", "12:01AM-4AM"]


def c(feature, *values, exclude=()):
    cond = {"feature": feature}
    if values:
        cond["values"] = list(values)
    if exclude:
        cond["exclude"] = list(exclude)
    return cond


def m(*conds):
    return {"all": list(conds)}


NO_HELMET = "The dataset has no helmet-compliance records."
NO_CITES = "The dataset has no citation or violation records."
NO_ZONES = "The dataset does not say which barangays have school or market zones."
NO_GEOMETRY = "The dataset has no road-geometry information (curves, embankments, intersections)."
NO_HISTORY = "This depends on how rankings change across data refreshes, which the system does not track."
SYSTEM = "This describes how the system should behave after a refresh, not a condition found in a pattern."
SHARE = "This depends on the overall share of motorcycle records, not on any single pattern."

MATCH = {
    "ENF": {
        1: m(c("cause", "Over Speeding")),
        2: m(c("cause", "Alcohol Intake")),
        3: m(c("day", *WEEKEND), c("time_period", *NIGHT)),
        4: m(c("barangay")),
        5: m(c("vehicle_involved", "Tricycle")),
        6: m(c("barangay"), c("day", *WEEKEND), c("time_period", *NIGHT)),
        7: NO_HELMET, 8: m(c("cause", "Wrong Overtaking")), 9: NO_CITES, 10: NO_ZONES,
        11: m(c("vehicle_involved", "Car", "SUV", "Pick-up")),
        12: SYSTEM,
    },
    "ENG": {
        1: m(c("cause", "Over Speeding")),
        2: m(c("collision_type", "Head-on Hit")),
        3: m(c("collision_type", "Rear-end Hit")),
        4: m(c("cause", "Slippery Road")),
        5: m(c("cause", "Environmental Factor")),
        6: m(c("collision_type", "Hit and Run")),
        7: m(c("collision_type", "Side-swipe Hit")),
        8: m(c("vehicle_involved", "Pedestrian")),
        9: m(c("vehicle_involved", "Bicycle")),
        10: NO_GEOMETRY, 11: NO_HISTORY, 12: NO_GEOMETRY,
        14: m(c("cause", "Animal on Road")),
    },
    "IEC": {
        1: m(c("cause", exclude=["Unknown"])),
        2: SHARE,
        3: m(c("cause", "Alcohol Intake")),
        4: m(c("cause", "Mechanical Failure")),
        5: m(c("day", "Saturday", "Sunday")),
        6: m(c("vehicle_involved", "Pedestrian")),
        7: m(c("barangay")),
        8: m(c("barangay")),
        9: m(c("vehicle_involved", "Tricycle", "E-Trike", "Jeep", "Bus", "Multicab")),
    },
}
AGENCY = {"ENF": "enforcement", "ENG": "engineering", "IEC": "education"}


def main(path):
    d = docx.Document(path)
    entries = []
    for code, table in zip(["ENF", "ENG", "IEC"], d.tables):
        for row in table.rows[1:]:
            cells = [x.text.strip() for x in row.cells]
            num = int(cells[0])
            rule = MATCH[code][num]
            entry = {
                "id": f"{code}-{num:02d}",
                "agency": AGENCY[code],
                "status": cells[1],
                "applies_when": cells[2].replace("\u201c", '"').replace("\u201d", '"'),
                "action": cells[3].replace("\u201c", '"').replace("\u201d", '"'),
                "active": isinstance(rule, dict),
            }
            if isinstance(rule, dict):
                entry["match"] = rule
            else:
                entry["inactive_reason"] = rule
            entries.append(entry)
    OUT.write_text(json.dumps({"version": 1, "source": "CCDRMC Prescription Catalog (expert-validated)",
                               "prescriptions": entries}, indent=2, ensure_ascii=False) + "\n")
    active = sum(e["active"] for e in entries)
    print(f"Wrote {len(entries)} entries ({active} active) to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
