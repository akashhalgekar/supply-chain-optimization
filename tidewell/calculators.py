"""Calculators for a visitor's OWN supply chain: the three Tidewell methods, cut loose from the Tidewell data.

    safety_stock()     z x sqrt(LT x sigma_D^2 + D^2 x sigma_LT^2), the same formula as tidewell/safetystock.py
    lot_sizing()       Wagner-Whitin, the same solver as tidewell/lotsizing.py, compared with lot-for-lot and EOQ
    network_design()   a facility location MIP (PuLP/CBC), the same idea as tidewell/network.py, for any set of
                       warehouses and customers

Each takes a plain dict (what Claude sends as tool input) and returns a plain dict of results. Bad input raises
ValueError with a message written for the model to read and correct. Nothing is stored.
"""
from itertools import combinations
from math import asin, cos, radians, sin, sqrt
import numpy as np
import pulp
from scipy.stats import norm
from .company import ROAD_FACTOR
from .lotsizing import wagner_whitin

PERIODS_PER_YEAR = {"day": 365, "week": 52, "month": 12}
MAX_PERIODS = 104
MAX_WAREHOUSES, MAX_CUSTOMERS, MAX_LANES = 25, 200, 3000   # MAX_LANES also caps warehouses x customers in lat/lon mode
SOLVE_SECONDS = 10


# ---- input helpers ---------------------------------------------------------------------------------------------
def _num(args, key, lo=None, hi=None, default=None, required=True, integer=False):
    v = args.get(key, default)
    if v is None:
        if required:
            raise ValueError(f"{key} is required.")
        return None
    if isinstance(v, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number; got {v!r}.") from None
    if not np.isfinite(v):
        raise ValueError(f"{key} must be a finite number.")
    if lo is not None and v < lo:
        raise ValueError(f"{key} must be at least {lo}; got {v:g}.")
    if hi is not None and v > hi:
        raise ValueError(f"{key} must be at most {hi}; got {v:g}.")
    return int(round(v)) if integer else v


def _only(args, allowed):
    if not isinstance(args, dict):
        raise ValueError("Inputs must be an object.")
    extra = set(args) - set(allowed)
    if extra:
        raise ValueError(f"Unknown inputs: {', '.join(sorted(extra))}. Allowed: {', '.join(allowed)}.")


def _r(x, nd=2):
    return round(float(x), nd)


# ---- 1. safety stock -------------------------------------------------------------------------------------------
SAFETY_STOCK_INPUTS = ("average_demand_per_period", "demand_std_dev_per_period", "lead_time_periods", "lead_time_std_dev_periods",
                       "service_level", "period", "order_quantity", "unit_cost", "holding_rate_per_year")


def _ss(z, d, sd, lt, sdlt):
    return z * sqrt(lt * sd ** 2 + d ** 2 * sdlt ** 2)


def safety_stock(args):
    _only(args, SAFETY_STOCK_INPUTS)
    d = _num(args, "average_demand_per_period", lo=0)
    sd = _num(args, "demand_std_dev_per_period", lo=0)
    lt = _num(args, "lead_time_periods", lo=0, hi=1000)
    sdlt = _num(args, "lead_time_std_dev_periods", lo=0, hi=1000, default=0.0)
    sl = _num(args, "service_level", lo=0.5, hi=0.9999, default=0.95)
    period = args.get("period", "week")
    if period not in PERIODS_PER_YEAR:
        raise ValueError(f"period must be one of {list(PERIODS_PER_YEAR)}.")
    q = _num(args, "order_quantity", lo=0, required=False)
    cost = _num(args, "unit_cost", lo=0, required=False)
    rate = _num(args, "holding_rate_per_year", lo=0, hi=2, required=False)
    if d == 0:
        raise ValueError("average_demand_per_period must be above zero.")

    z = float(norm.ppf(sl))
    spread = sqrt(lt * sd ** 2 + d ** 2 * sdlt ** 2)              # std dev of demand over the lead time
    ss, ss_demand = z * spread, z * sd * sqrt(lt)
    q = q if q else d                                              # assume one period of demand per order if not given
    short_per_cycle = spread * (norm.pdf(z) - z * (1 - norm.cdf(z)))
    out = {
        "z": _r(z, 3),
        "safety_stock_units": _r(ss, 1),
        "reorder_point_units": _r(d * lt + ss, 1),
        "safety_stock_if_lead_time_were_perfectly_reliable": _r(ss_demand, 1),
        "share_of_safety_stock_caused_by_lead_time_variability": _r(1 - ss_demand / ss, 3) if ss > 0 else 0.0,
        "safety_stock_in_periods_of_demand": _r(ss / d, 2),
        "cycle_service_level": sl,
        "fill_rate": _r(max(0.0, 1 - short_per_cycle / q), 4) if q > 0 else None,
        "order_quantity_assumed_for_fill_rate": _r(q, 1),
        "order_quantity_was_assumed": "order_quantity" not in args or not args.get("order_quantity"),
        "safety_stock_at_other_service_levels": {f"{int(round(s * 100))}%": _r(float(norm.ppf(s)) * spread, 1)
                                                 for s in (0.90, 0.95, 0.98, 0.99) if abs(s - sl) > 1e-9},
        "safety_stock_if_lead_time_std_dev_halved": _r(_ss(z, d, sd, lt, sdlt / 2), 1),
        "safety_stock_if_lead_time_one_period_shorter": _r(_ss(z, d, sd, max(lt - 1, 0), sdlt), 1),
        "period": period,
    }
    if cost is not None and rate is not None:
        out["safety_stock_value"] = _r(ss * cost, 0)
        out["safety_stock_holding_cost_per_year"] = _r(ss * cost * rate, 0)
        out["holding_cost_saved_per_year_if_lead_time_std_dev_halved"] = _r((ss - _ss(z, d, sd, lt, sdlt / 2)) * cost * rate, 0)
    return out


# ---- 2. lot sizing ---------------------------------------------------------------------------------------------
LOT_SIZING_INPUTS = ("demand_per_period", "setup_cost", "holding_cost_per_unit_per_period", "max_periods_per_batch")


def lot_sizing(args):
    _only(args, LOT_SIZING_INPUTS)
    dem = args.get("demand_per_period")
    if not isinstance(dem, list) or not 2 <= len(dem) <= MAX_PERIODS:
        raise ValueError(f"demand_per_period must be a list of 2 to {MAX_PERIODS} numbers, one per period.")
    d = np.array([_num({f"demand_per_period[{i}]": x}, f"demand_per_period[{i}]", lo=0) for i, x in enumerate(dem)])
    if d.sum() <= 0:
        raise ValueError("demand_per_period must contain some demand.")
    s = _num(args, "setup_cost", lo=0)
    h = _num(args, "holding_cost_per_unit_per_period", lo=0)
    cover = _num(args, "max_periods_per_batch", lo=1, hi=MAX_PERIODS, required=False, integer=True)
    if h == 0:
        raise ValueError("holding_cost_per_unit_per_period must be above zero, or every unit would be made in period 1.")

    best = wagner_whitin(d, s, h, max_cover=cover)
    l4l_runs = int((d > 0).sum())
    l4l_cost = l4l_runs * s
    avg = float(d.mean())
    eoq = sqrt(2 * avg * s / h) if s > 0 else 0.0
    nz = d[d > 0]
    cv = float(nz.std() / nz.mean()) if len(nz) > 1 else 0.0
    return {
        "plan": [{"period": i + 1, "demand": _r(x, 1), "produce": _r(p, 1), "ending_stock": _r(st, 1)}
                 for i, (x, p, st) in enumerate(zip(d, best["produce"], best["stock"]))],
        "runs": best["runs"],
        "setup_cost_total": _r(best["setup"], 0),
        "holding_cost_total": _r(best["holding"], 0),
        "total_cost": _r(best["total"], 0),
        "lot_for_lot": {"runs": l4l_runs, "total_cost": _r(l4l_cost, 0), "note": "make exactly each period's demand: no stock, a setup every period"},
        "saving_vs_lot_for_lot": _r(l4l_cost - best["total"], 0),
        "saving_vs_lot_for_lot_pct": _r((l4l_cost - best["total"]) / l4l_cost * 100, 1) if l4l_cost else 0.0,
        "eoq_units": _r(eoq, 1),
        "eoq_in_periods_of_average_demand": _r(eoq / avg, 2) if avg else None,
        "demand_variability_cv": _r(cv, 2),
        "batch_cover_limit_periods": cover,
        "method": "Wagner-Whitin dynamic programme: provably cheapest for one item with no capacity limit.",
    }


# ---- 3. network design -----------------------------------------------------------------------------------------
NETWORK_INPUTS = ("warehouses", "customers", "lanes", "cost_per_unit_mile", "max_miles", "must_open", "must_close",
                  "max_open")


def _road_miles(a, b):
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 3958.8 * asin(sqrt(min(1.0, h))) * ROAD_FACTOR


def _named(items, kind, limit, fields):
    if not isinstance(items, list) or not 1 <= len(items) <= limit:
        raise ValueError(f"{kind} must be a list of 1 to {limit} objects.")
    out = {}
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("name"), str) or not it["name"].strip():
            raise ValueError(f"Every entry in {kind} needs a text name.")
        extra = set(it) - set(fields) - {"name"}
        if extra:
            raise ValueError(f"Unknown fields in {kind}: {', '.join(sorted(extra))}.")
        name = it["name"].strip()
        if name in out:
            raise ValueError(f"Duplicate name in {kind}: {name}.")
        out[name] = it
    return out


def _solve(W, C, cost, fixed, cap, demand, force_open=(), force_closed=(), max_open=None):
    """Min fixed + transport. y[w] open, x[w,c] units. Returns None if infeasible."""
    m = pulp.LpProblem("network", pulp.LpMinimize)
    y = {w: pulp.LpVariable(f"y{i}", cat="Binary") for i, w in enumerate(W)}
    x = {(w, c): pulp.LpVariable(f"x{i}_{j}", lowBound=0) for i, w in enumerate(W) for j, c in enumerate(C) if (w, c) in cost}
    m += pulp.lpSum(fixed[w] * y[w] for w in W) + pulp.lpSum(cost[k] * v for k, v in x.items())
    for c in C:
        m += pulp.lpSum(v for (w, cc), v in x.items() if cc == c) == demand[c]
    for w in W:
        out = pulp.lpSum(v for (ww, c), v in x.items() if ww == w)
        m += out <= (cap[w] if cap[w] is not None else sum(demand.values())) * y[w]
        for (ww, c), v in x.items():                      # tight link so the relaxation is strong
            if ww == w:
                m += v <= demand[c] * y[w]
    for w in force_open:
        m += y[w] == 1
    for w in force_closed:
        m += y[w] == 0
    if max_open is not None:
        m += pulp.lpSum(y.values()) <= max_open
    m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVE_SECONDS))
    status = pulp.LpStatus[m.status]
    if status == "Infeasible":
        return None
    if status != "Optimal" or any(v.value() is None for v in y.values()):
        raise ValueError(f"The network could not be solved within {SOLVE_SECONDS} seconds. Try fewer warehouses or customers, "
                         "or group small customers into regions.")
    open_ = [w for w in W if y[w].value() > 0.5]
    flows = {k: v.value() for k, v in x.items() if v.value() and v.value() > 1e-6}
    f = sum(fixed[w] for w in open_)
    t = sum(cost[k] * q for k, q in flows.items())
    return {"open": open_, "flows": flows, "fixed": f, "transport": t, "total": f + t}


def network_design(args):
    _only(args, NETWORK_INPUTS)
    W = _named(args.get("warehouses"), "warehouses", MAX_WAREHOUSES, ("fixed_cost_per_period", "capacity_per_period", "lat", "lon"))
    C = _named(args.get("customers"), "customers", MAX_CUSTOMERS, ("demand_per_period", "lat", "lon"))
    fixed = {w: _num(v, "fixed_cost_per_period", lo=0) for w, v in W.items()}
    cap = {w: _num(v, "capacity_per_period", lo=0, required=False) for w, v in W.items()}
    demand = {c: _num(v, "demand_per_period", lo=0) for c, v in C.items()}
    rate = _num(args, "cost_per_unit_mile", lo=0, required=False)
    max_miles = _num(args, "max_miles", lo=1, required=False)
    max_open = _num(args, "max_open", lo=1, hi=len(W), required=False, integer=True)

    cost, miles = {}, {}
    lanes = args.get("lanes")
    if lanes is not None:
        if not isinstance(lanes, list) or not lanes or len(lanes) > MAX_LANES:
            raise ValueError(f"lanes must be a list of 1 to {MAX_LANES} objects.")
        for ln in lanes:
            if not isinstance(ln, dict) or set(ln) - {"warehouse", "customer", "cost_per_unit", "miles"}:
                raise ValueError("Each lane needs warehouse, customer and cost_per_unit (miles optional), nothing else.")
            w, c = ln.get("warehouse"), ln.get("customer")
            if w not in W or c not in C:
                raise ValueError(f"Lane {w} -> {c} names a warehouse or customer that is not in the lists.")
            cost[w, c] = _num(ln, "cost_per_unit", lo=0)
            if ln.get("miles") is not None:
                miles[w, c] = _num(ln, "miles", lo=0)
    else:
        if rate is None:
            raise ValueError("Give either lanes (cost per unit for each warehouse-customer pair) or cost_per_unit_mile "
                             "plus lat and lon for every warehouse and customer.")
        for name, it in list(W.items()) + list(C.items()):
            _num(it, "lat", lo=-90, hi=90), _num(it, "lon", lo=-180, hi=180)
        for w, wi in W.items():
            for c, ci in C.items():
                mi = _road_miles((wi["lat"], wi["lon"]), (ci["lat"], ci["lon"]))
                miles[w, c], cost[w, c] = mi, mi * rate
    if len(cost) > MAX_LANES:
        raise ValueError(f"That is {len(cost)} warehouse-customer pairs; the limit is {MAX_LANES}. Group customers into regions.")
    if max_miles is not None:
        if not miles:
            raise ValueError("max_miles needs miles on the lanes, or lat/lon with cost_per_unit_mile.")
        cost = {k: v for k, v in cost.items() if miles.get(k, float("inf")) <= max_miles}
    for c in C:
        if demand[c] > 0 and not any(cc == c for (_, cc) in cost):
            raise ValueError(f"Customer {c} has no allowed lane from any warehouse" + (" within max_miles." if max_miles else "."))
    must_open = args.get("must_open") or []
    must_close = args.get("must_close") or []
    for lst, label in ((must_open, "must_open"), (must_close, "must_close")):
        if not isinstance(lst, list) or any(w not in W for w in lst):
            raise ValueError(f"{label} must be a list of warehouse names from {list(W)}.")
    if set(must_open) & set(must_close):
        raise ValueError("A warehouse cannot be in both must_open and must_close.")

    Wl, Cl = list(W), list(C)
    best = _solve(Wl, Cl, cost, fixed, cap, demand, must_open, must_close, max_open)
    if best is None:
        return {"feasible": False,
                "note": "No plan serves every customer: total capacity is too small, a customer is out of reach, or the "
                        "must_open / must_close / max_open rules conflict."}
    total_demand = sum(demand.values())

    def assign(sol):
        rows = {}
        for (w, c), q in sol["flows"].items():
            rows.setdefault(c, []).append({"warehouse": w, "units": _r(q, 1), "share": _r(q / demand[c], 3) if demand[c] else 0.0,
                                           **({"miles": round(miles[w, c])} if (w, c) in miles else {})})
        return rows

    out = {
        "feasible": True,
        "open_warehouses": best["open"],
        "closed_warehouses": [w for w in Wl if w not in best["open"]],
        "total_cost_per_period": _r(best["total"], 0),
        "fixed_cost_per_period": _r(best["fixed"], 0),
        "transport_cost_per_period": _r(best["transport"], 0),
        "cost_per_unit": _r(best["total"] / total_demand, 3) if total_demand else None,
        "assignments": assign(best),
        "warehouse_load": {w: {"units": _r(sum(q for (ww, _), q in best["flows"].items() if ww == w), 1),
                               **({"utilisation": _r(sum(q for (ww, _), q in best["flows"].items() if ww == w) / cap[w], 3)}
                                  if cap[w] else {})} for w in best["open"]},
    }
    if miles:
        moved = sum(q * miles[k] for k, q in best["flows"].items() if k in miles)
        out["average_miles_per_unit"] = _r(moved / total_demand, 0) if total_demand else None
        out["share_of_demand_within_600_miles"] = _r(sum(q for k, q in best["flows"].items() if miles.get(k, 1e9) <= 600) / total_demand, 3) if total_demand else None

    # What each decision is worth: re-solve with each open warehouse forced shut, and each closed one forced open.
    if len(Wl) <= 12 and len(cost) <= 1200:
        alt = {}
        for w in Wl:
            if w in must_open or w in must_close:
                continue
            closing = w in best["open"]
            sol = _solve(Wl, Cl, cost, fixed, cap, demand, list(must_open) + ([] if closing else [w]),
                         list(must_close) + ([w] if closing else []), max_open)
            key = f"close {w}" if closing else f"open {w}"
            alt[key] = "infeasible" if sol is None else {"total_cost_per_period": _r(sol["total"], 0),
                                                          "change_vs_best": _r(sol["total"] - best["total"], 0)}
        out["cost_of_changing_one_decision"] = alt
        if not must_close and max_open is None:
            every = _solve(Wl, Cl, cost, fixed, cap, demand, Wl)
            if every:
                out["if_every_warehouse_open"] = {"total_cost_per_period": _r(every["total"], 0),
                                                  "change_vs_best": _r(every["total"] - best["total"], 0)}
    return out


def brute_force_network(W, C, cost, fixed, cap, demand):
    """Every subset solved as a transport LP: the check that the MIP picks the true cheapest set (small cases only)."""
    best = None
    for k in range(1, len(W) + 1):
        for subset in combinations(W, k):
            sol = _solve(W, C, cost, fixed, cap, demand, force_open=subset, force_closed=[w for w in W if w not in subset])
            if sol and (best is None or sol["total"] < best["total"] - 1e-6):
                best = sol
    return best
