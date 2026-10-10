"""Filtering, sorting and chart-shaping for the Rule Explorer page."""


def filter_rules(
    rules: list[dict],
    min_support: float = 0.05,
    min_confidence: float = 0.60,
    min_lift: float = 1.2,
    search: str = "",
    sort_by: str = "lift",
    order: str = "desc",
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    search = (search or "").strip().lower()

    filtered = [
        r for r in rules
        if r["support"] >= min_support
        and r["confidence"] >= min_confidence
        and r["lift"] >= min_lift
        and (
            not search
            or search in r["antecedent_label"].lower()
            or search in r["consequent_label"].lower()
        )
    ]

    filtered = deduplicate_rules(filtered)
    reverse = order != "asc"
    if sort_by not in ("support", "confidence", "lift"):
        sort_by = "lift"
    filtered.sort(key=lambda r: (r[sort_by], r["confidence"], r["support"], r["antecedent_label"]), reverse=reverse)

    total = len(filtered)
    page = filtered[offset:offset + limit]
    return page, total


def network_data(rules: list[dict], top_n: int = 20) -> dict:
    """Node/edge structure for a vis-network style directed graph."""
    top_rules = sorted(rules, key=lambda r: r["lift"], reverse=True)[:top_n]

    node_ids: dict[str, int] = {}
    nodes = []
    edges = []

    def get_node(label: str) -> int:
        if label not in node_ids:
            node_ids[label] = len(node_ids)
            nodes.append({"id": node_ids[label], "label": label, "degree": 0})
        return node_ids[label]

    seen_edges: dict[tuple[int, int], dict] = {}
    for r in top_rules:
        a_label = r["antecedent_label"]
        c_label = r["consequent_label"]
        a_id, c_id = get_node(a_label), get_node(c_label)
        key = (a_id, c_id)
        if key not in seen_edges or r["lift"] > seen_edges[key]["lift"]:
            seen_edges[key] = {
                "source": a_id, "target": c_id,
                "support": r["support"], "confidence": r["confidence"], "lift": r["lift"],
            }

    edges = list(seen_edges.values())
    degree = {n["id"]: 0 for n in nodes}
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    for n in nodes:
        n["degree"] = degree[n["id"]]

    max_lift = max((e["lift"] for e in edges), default=1.0)
    return {"nodes": nodes, "edges": edges, "max_lift": max_lift}


def heatmap_data(rules: list[dict], top_antecedents: int = 10, top_consequents: int = 8) -> dict:
    """Lift matrix for single-antecedent -> single-consequent rules only."""
    singles = [r for r in rules if len(r["antecedents"]) == 1 and len(r["consequents"]) == 1]

    ante_best: dict[str, float] = {}
    cons_best: dict[str, float] = {}
    for r in singles:
        a, c = r["antecedent_label"], r["consequent_label"]
        ante_best[a] = max(ante_best.get(a, 0), r["lift"])
        cons_best[c] = max(cons_best.get(c, 0), r["lift"])

    top_ante = [k for k, _ in sorted(ante_best.items(), key=lambda kv: kv[1], reverse=True)[:top_antecedents]]
    top_cons = [k for k, _ in sorted(cons_best.items(), key=lambda kv: kv[1], reverse=True)[:top_consequents]]

    lookup = {(r["antecedent_label"], r["consequent_label"]): r["lift"] for r in singles}
    matrix = [[lookup.get((a, c)) for c in top_cons] for a in top_ante]

    return {"antecedents": top_ante, "consequents": top_cons, "matrix": matrix}


def deduplicate_rules(rules):
    """Collapse the same feature-value combination; prune unhelpful supersets.
    Keep the strongest qualifying direction. A longer antecedent is redundant
    only with the same consequent and no gain in confidence or lift.
    """
    ranked=sorted(rules,key=lambda r:(r['lift'],r['confidence'],r['support'],r['antecedent_label']),reverse=True)
    seen=set(); unique=[]
    for r in ranked:
        key=frozenset(tuple(i) for i in r.get('items',[]))
        if not key: key=(r['antecedent_label'],r['consequent_label'])
        if key in seen: continue
        seen.add(key); unique.append(r)
    kept=[]
    for r in unique:
        ant=set(map(tuple,r.get('antecedent_items',[])))
        cons=set(map(tuple,r.get('consequent_items',[])))
        redundant=bool(ant and cons) and any(
            set(map(tuple,s.get('antecedent_items',[]))) < ant
            and set(map(tuple,s.get('consequent_items',[]))) == cons
            and s['confidence'] >= r['confidence'] and s['lift'] >= r['lift']
            for s in ranked if s is not r)
        if not redundant: kept.append(r)
    return kept
