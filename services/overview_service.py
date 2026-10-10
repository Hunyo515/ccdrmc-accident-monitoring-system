"""KPI and summary chart data for the Overview page."""
import pandas as pd
from services.contextual_prescriptions import PERIODS

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_ABBR = [m[:3] for m in MONTH_ORDER]

UNKNOWN_FIELDS = ["cause", "collision_type", "time_period", "vehicle_involved"]
FILTERABLE_FIELDS = ["barangay", "collision_type", "cause"]


def _drop_unknown(df: pd.DataFrame, field: str) -> pd.DataFrame:
    if field not in UNKNOWN_FIELDS:
        return df
    return df[~df[field].astype(str).str.lower().str.startswith("unknown")]


def _row(label, count, fatal, non_fatal=0, property_damage=0):
    return dict(label=str(label),count=int(count),fatal=int(fatal),non_fatal=int(non_fatal),
                property_damage=int(property_damage),unknown=int(count-fatal-non_fatal-property_damage))


def _category_row(df, field, value, label=None):
    sub=df[df[field]==value]; counts=sub['severity'].value_counts()
    return _row(label if label is not None else value,len(sub),counts.get('Fatal',0),counts.get('Non-Fatal',0),counts.get('Damage-to-Property',0))


def _top_n_severity(df: pd.DataFrame, field: str, n: int = 8, include_other: bool = True) -> list[dict]:
    """Top-N categories by count, each carrying its own fatal/non-fatal split, plus an Other bucket."""
    clean = _drop_unknown(df, field)
    counts = clean[field].value_counts()
    fatal_counts = clean[clean["severity"] == "Fatal"][field].value_counts()

    top = counts.head(n)
    records = [_category_row(clean, field, label) for label in top.index]

    if include_other:
        other = counts.iloc[n:]
        if len(other):
            other_labels = other.index
            o_count = int(other.sum())
            o_fatal = int(fatal_counts.reindex(other_labels).fillna(0).sum())
            other_df=clean[clean[field].isin(other_labels)]
            records.append(_row("Other", o_count, o_fatal, (other_df.severity=="Non-Fatal").sum(), (other_df.severity=="Damage-to-Property").sum()))
    return records


def _ordered_severity(df: pd.DataFrame, field: str, order: list[str], drop_unknown: bool = False) -> list[dict]:
    """Category breakdown in a fixed (non-count) order, e.g. calendar order for days."""
    clean = _drop_unknown(df, field) if drop_unknown else df
    counts = clean[field].value_counts()
    fatal_counts = clean[clean["severity"] == "Fatal"][field].value_counts()
    return [_category_row(clean, field, label) for label in order]


def _hourly_distribution(df: pd.DataFrame) -> list[dict]:
    clean = df.dropna(subset=["hour"])
    counts = clean.groupby("hour").size()
    fatal_counts = clean[clean["severity"] == "Fatal"].groupby("hour").size()
    return [_category_row(clean, "hour", h, f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}") for h in range(24)]


def _busiest_period(df):
    counts=_drop_unknown(df,"time_period")["time_period"].value_counts()
    if counts.empty: return {"label":"No known time period","count":0,"periods":[]}
    maximum=int(counts.max())
    periods=sorted(counts[counts==maximum].index.tolist(),key=lambda x:list(PERIODS).index(x) if x in PERIODS else 99)
    return {"label":" / ".join(PERIODS.get(v,v) for v in periods),"count":maximum,"periods":periods}


def available_years(df: pd.DataFrame) -> list[int]:
    return sorted(int(y) for y in df["year"].dropna().unique())


def _yearly_fatal_series(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby("year")
        .agg(total=("severity", "size"), fatal=("severity", lambda s: (s == "Fatal").sum()))
        .reset_index()
        .sort_values("year")
    )
    return g


def _fatality_trend(trend_df: pd.DataFrame, year_to: int | None) -> dict:
    """Compares fatalities in the latest selected year to the prior year."""
    yearly = _yearly_fatal_series(trend_df)
    years = yearly["year"].tolist()
    if not years:
        return {"direction": "flat", "delta": 0, "current_year": None, "previous_year": None}

    target = year_to if year_to in years else years[-1]
    idx = years.index(target)
    current = int(yearly.iloc[idx]["fatal"])
    if idx == 0:
        return {"direction": "flat", "delta": 0, "current_year": target, "previous_year": None, "current": current}

    previous_year = years[idx - 1]
    previous = int(yearly.iloc[idx - 1]["fatal"])
    delta = current - previous
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    return {
        "direction": direction, "delta": delta,
        "current": current, "previous": previous,
        "current_year": target, "previous_year": previous_year,
    }


def build_monthly_comparison(full_df: pd.DataFrame, filters: dict) -> dict:
    """Monthly totals for every year in range, for the cross-year line chart."""
    df = _apply_filters(full_df, filters, include_year_range=True)
    years = sorted(int(y) for y in df["year"].dropna().unique())
    series = {}
    for y in years:
        sub = df[df["year"] == y]
        counts = sub.groupby("month").size().reindex(MONTH_ORDER, fill_value=0)
        series[str(y)] = [int(c) for c in counts.tolist()]
    return {"months": MONTH_ABBR, "years": years, "series": series}


def build_barangay_breakdown(full_df: pd.DataFrame, filters: dict, top_n: int = 5) -> dict:
    """Top-N barangays crossed with day-of-week and month, for the grouped bar charts."""
    df = _apply_filters(full_df, filters, include_year_range=True, skip_barangay=False)
    top_barangays = df["barangay"].value_counts().head(top_n).index.tolist()
    sub = df[df["barangay"].isin(top_barangays)]

    by_day = {}
    by_month = {}
    for b in top_barangays:
        bsub = sub[sub["barangay"] == b]
        day_counts = bsub.groupby("day").size().reindex(DAY_ORDER, fill_value=0)
        by_day[b] = [int(c) for c in day_counts.tolist()]
        month_counts = bsub.groupby("month").size().reindex(MONTH_ORDER, fill_value=0)
        by_month[b] = [int(c) for c in month_counts.tolist()]

    return {
        "barangays": top_barangays,
        "days": DAY_ORDER,
        "months": MONTH_ABBR,
        "by_day": by_day,
        "by_month": by_month,
        "colors": barangay_colors(full_df),
    }


def _apply_filters(full_df: pd.DataFrame, filters: dict, include_year_range: bool = False, skip_barangay: bool = False) -> pd.DataFrame:
    df = full_df
    if include_year_range:
        year_from = filters.get("year_from")
        year_to = filters.get("year_to")
        if year_from is not None:
            df = df[df["year"] >= year_from]
        if year_to is not None:
            df = df[df["year"] <= year_to]
    for field in FILTERABLE_FIELDS:
        if skip_barangay and field == "barangay":
            continue
        value = filters.get(field)
        if value:
            df = df[df[field] == value]
    return df


def build_overview(full_df: pd.DataFrame, filters: dict) -> dict:
    df = _apply_filters(full_df, filters, include_year_range=True)

    # Trend context spans every year, respecting non-year filters only, so the
    # fatality-trend comparison always has two years to compare.
    trend_filters = {k: v for k, v in filters.items() if k not in ("year_from", "year_to")}
    trend_df = _apply_filters(full_df, trend_filters, include_year_range=False)

    total = len(df)
    fatal = int((df["severity"] == "Fatal").sum())
    non_fatal = int((df["severity"] == "Non-Fatal").sum())
    fatal_rate = round(fatal / total * 100, 2) if total else 0.0

    cause_clean = _drop_unknown(df, "cause")
    top_cause = cause_clean["cause"].value_counts().idxmax() if len(cause_clean) else "\u2014"
    top_cause_count = int(cause_clean["cause"].value_counts().max()) if len(cause_clean) else 0
    top_barangay = df["barangay"].value_counts().idxmax() if total else "\u2014"
    top_barangay_count = int(df["barangay"].value_counts().max()) if total else 0

    year_min = int(full_df["year"].min())
    year_max = int(full_df["year"].max())
    year_from = filters.get("year_from") or year_min
    year_to = filters.get("year_to") or year_max

    return {
        "kpis": {
            "total_accidents": total,
            "fatal_count": fatal,
            "non_fatal_count": non_fatal,
            "property_damage_count": int((df["severity"] == "Damage-to-Property").sum()),
            "unknown_severity_count": int((df["severity"] == "Unknown").sum()),
            "fatal_rate_pct": fatal_rate,
            "top_cause": top_cause,
            "top_cause_count": top_cause_count,
            "top_barangay": top_barangay,
            "top_barangay_count": top_barangay_count,
            "time_period": _busiest_period(df),
            "year_range": f"{year_from}\u2013{year_to}" if year_from != year_to else f"{year_from}",
        },
        "fatality_trend": _fatality_trend(trend_df, year_to if filters.get("year_to") else None),
        "hourly_distribution": _hourly_distribution(df),
        "top_causes": _top_n_severity(df, "cause", 8),
        "top_barangays": _top_n_severity(df, "barangay", 5, include_other=False),
        "top_vehicles": _top_n_severity(df, "vehicle_involved", 10, include_other=False),
        "collision_types": _top_n_severity(df, "collision_type", 8),
        "day_distribution": sorted(_ordered_severity(df, "day", DAY_ORDER),key=lambda r:-r["count"]),
        "month_distribution": _ordered_severity(df, "month", MONTH_ORDER),
        "yearly_trend": [{"year": int(y), "count":int(n)} for y,n in df.groupby("year").size().sort_index().items()],
        "barangay_colors": barangay_colors(full_df),
    }


def barangay_colors(full_df):
    # Stable mapping from the complete dataset, independent of filter/rank order.
    palette=['#2463a7','#168779','#b56a22','#8060b4','#c74762','#517781','#9b793c']
    names=full_df['barangay'].value_counts().index.tolist()
    return {name:palette[i%len(palette)] for i,name in enumerate(names)}
