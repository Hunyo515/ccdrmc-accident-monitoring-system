"""
Association rule mining pipeline for the Echague road accident dataset.

Reproduces the feature set and thresholds used in the capstone notebook
(Notebooks/06-Association-Rule-Mining.ipynb):
    features    = vehicle_involved, collision_type, cause, barangay,
                  time_period, day, severity
    min_support = 0.05, max_len = 3 (frequent itemset mining)

Panel review (see CCDRMC feedback) narrowed this to FP-Growth alone: the
capstone had already shown Apriori, FP-Growth and ECLAT agree exactly on
this dataset, so carrying three algorithms in the live dashboard added
mining time and UI complexity without changing a single result.

Rules are mined once at process startup (or on demand via /api/admin/refresh
or after a data upload) and cached to disk as pickle, keyed by a hash of the
source CSV, so restarts don't re-mine the same data every time.
"""
import hashlib
import pickle
import threading
import time
from pathlib import Path

import pandas as pd
from mlxtend.frequent_patterns import fpgrowth, association_rules
from services import storage_service

ARM_FEATURES = [
    "vehicle_involved",
    "collision_type",
    "cause",
    "barangay",
    "time_period",
    "day",
    "severity",
]

MIN_SUPPORT = 0.05
MAX_LEN = 3

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "Echague-Road-Accident-Cleaned.csv"
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    h.update(f"{MIN_SUPPORT}-{MAX_LEN}-fpgrowth-items-v5".encode())
    return h.hexdigest()[:16]


def clean_label(item: str) -> str:
    """'cause_Overspeeding' -> 'Overspeeding' for display."""
    for feat in sorted(ARM_FEATURES, key=len, reverse=True):
        prefix = feat + "_"
        if item.startswith(prefix):
            return item[len(prefix):]
    return item


def split_item(item: str) -> tuple[str, str]:
    """'cause_Over Speeding' -> ('cause', 'Over Speeding').

    clean_label() drops the feature name, which makes 'Collision' (a cause AND
    a collision type) and 'Unknown' (several fields) ambiguous. Prescription
    matching needs the feature, so rules also carry feature-tagged items.
    """
    for feat in sorted(ARM_FEATURES, key=len, reverse=True):
        prefix = feat + "_"
        if item.startswith(prefix):
            return feat, item[len(prefix):]
    return "", item


def itemset_label(frozenset_val) -> str:
    return " & ".join(clean_label(i) for i in sorted(frozenset_val))


def _rules_to_records(rules_df: pd.DataFrame) -> list[dict]:
    records = []
    for row in rules_df.itertuples(index=False):
        antecedents = sorted(clean_label(i) for i in row.antecedents)
        consequents = sorted(clean_label(i) for i in row.consequents)
        records.append({
            "antecedent_items": sorted(split_item(i) for i in row.antecedents),
            "consequent_items": sorted(split_item(i) for i in row.consequents),
            "antecedents": antecedents,
            "consequents": consequents,
            "items": sorted(
                {split_item(i) for i in row.antecedents} | {split_item(i) for i in row.consequents}
            ),
            "antecedent_label": " & ".join(antecedents),
            "consequent_label": " & ".join(consequents),
            "support": round(float(row.support), 4),
            "confidence": round(float(row.confidence), 4),
            "lift": round(float(row.lift), 4),
        })
    return records


class ARMPipeline:
    """Loads the dataset once and holds FP-Growth-mined rules."""

    def __init__(self):
        self.data: pd.DataFrame | None = None
        self.encoded: pd.DataFrame | None = None
        self.rules: list[dict] = []
        self.itemsets: pd.DataFrame | None = None
        self.meta: dict = {}
        # Serializes uploads: append-to-CSV then re-mine is a read-modify-write,
        # so two simultaneous uploads must not interleave.
        self._write_lock = threading.Lock()

    def load_data(self) -> pd.DataFrame:
        df = storage_service.load()
        self._coerce_types(df)
        self.data = df
        return df

    @staticmethod
    def _coerce_types(df: pd.DataFrame) -> None:
        """Normalizes dtypes used across the app, in place."""
        for col in ("hour", "minute", "latitude", "longitude"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")

    def run(self, force: bool = False) -> dict:
        """Mine (or load cached) FP-Growth rules."""
        cache_key = _file_hash(DATA_PATH) if storage_service.backend() == "csv" else "oracle"
        cache_file = CACHE_DIR / f"rules_{cache_key}.pkl"

        if self.data is None:
            self.load_data()

        if storage_service.backend() == "csv" and not force and cache_file.exists():
            with open(cache_file, "rb") as f:
                cached = pickle.load(f)
            self.rules = cached["rules"]
            self.itemsets = cached["itemsets"]
            self.meta = cached["meta"]
            return self.meta

        start = time.time()
        features = self.data[ARM_FEATURES].astype("string")
        features = features.mask(features.apply(lambda col: col.str.lower().str.startswith("unknown", na=True)))
        encoded = pd.get_dummies(features, drop_first=False).astype(bool)
        self.encoded = encoded

        fi_fpgrowth = fpgrowth(encoded, min_support=MIN_SUPPORT, use_colnames=True, max_len=MAX_LEN)
        rules_fpgrowth = association_rules(fi_fpgrowth, metric="confidence", min_threshold=0.0) if not fi_fpgrowth.empty else pd.DataFrame()

        self.itemsets = fi_fpgrowth
        self.rules = _rules_to_records(rules_fpgrowth)

        elapsed = round(time.time() - start, 2)
        self.meta = {
            "mined_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": elapsed,
            "n_transactions": int(len(self.data)),
            "n_rules": len(self.rules),
            "min_support": MIN_SUPPORT,
            "max_len": MAX_LEN,
            "features": ARM_FEATURES,
            "algorithm": "FP-Growth",
            "dataset_revision": hashlib.sha256(self.data.to_csv(index=False).encode()).hexdigest()[:16],
        }

        if storage_service.backend() == "csv" and not getattr(self, "_staging", False):
            with open(cache_file, "wb") as f:
                pickle.dump({"rules": self.rules, "itemsets": self.itemsets, "meta": self.meta}, f)
        return self.meta

    def snapshot(self):
        """Consistent read for data pages and multi-section reports."""
        with self._write_lock:
            return self.data.copy(), list(self.rules), dict(self.meta)

    def append_and_remine(self, new_df: pd.DataFrame) -> dict:
        """Mine a candidate snapshot first; publish only after persistence succeeds."""
        with self._write_lock:
            # One application worker owns the in-memory snapshot (see Procfile).
            current = storage_service.load()
            new_df = storage_service.unique_new(current, new_df)
            if new_df.empty:
                return {**self.meta, "rows_added": 0}
            self._coerce_types(new_df)
            combined = pd.concat([current, new_df], ignore_index=True)
            candidate = ARMPipeline()
            candidate.data = combined
            candidate._staging = True
            candidate.run(force=True)
            storage_service.save_append(new_df, combined)
            self.data, self.rules, self.itemsets, self.meta = candidate.data, candidate.rules, candidate.itemsets, candidate.meta
            return {**self.meta, "rows_added": len(new_df)}


# Single shared instance used across the app
pipeline = ARMPipeline()
