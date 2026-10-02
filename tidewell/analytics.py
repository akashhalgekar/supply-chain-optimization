"""Decision analytics on top of the chain model.

  savings_waterfall    what the recommended chain saves against "change nothing"
  dc_set_comparison    cost every possible set of open DCs on the whole chain, not just the network
  stress_tests         what happens to cost and the network when something breaks
  input_sensitivity    which input moves total cost the most
  cost_to_serve        what it costs to deliver one pallet to each market
"""
import itertools
import pandas as pd
from . import chain
from .company import Company, Terms


def savings_waterfall(co: Company, base: chain.ChainResult):
    """Reference case = keep every candidate DC open and make every item every week. (It is a stated yardstick, not a measured
    current state: replace it with the client's real network when there is one.) Two steps move it to the recommendation:
    close the DCs the network does not need, then batch production."""
    sq = chain.run(co, base.terms, dc_set=co.codes("dcs"))
    sq_cost = sq.kpi["network_cost"] + sq.lots.baseline_total / 12 + sq.kpi["stock_cost"]
    opt_weekly_runs = base.lots.baseline_total / 12
    step_dcs = sq_cost - (base.kpi["network_cost"] + opt_weekly_runs + base.kpi["stock_cost"])
    step_batch = opt_weekly_runs - base.kpi["planning_cost"]
    assert abs(sq_cost - step_dcs - step_batch - base.kpi["weekly_cost"]) < 1e-6
    return pd.DataFrame([
        ("Reference case: every DC open, every item made weekly", sq_cost, None),
        ("Close the DCs the network does not need", -step_dcs, step_dcs / sq_cost),
        ("Batch production runs", -step_batch, step_batch / sq_cost),
        ("Recommended chain", base.kpi["weekly_cost"], 1 - base.kpi["weekly_cost"] / sq_cost),
    ], columns=["step", "usd_per_week", "share_of_reference"])


def dc_set_comparison(co: Company, terms: Terms):
    """Every non-empty set of DCs, costed on network + production planning + safety stock."""
    rows = []
    for k in range(1, len(co.dcs) + 1):
        for subset in itertools.combinations(co.codes("dcs"), k):
            r = chain.run(co, terms, dc_set=list(subset))
            if not r.kpi["feasible"]:
                continue
            rows.append((", ".join(co.city(d) for d in subset), k, r.kpi["network_cost"], r.kpi["planning_cost"], r.kpi["stock_cost"], r.kpi["weekly_cost"], r.kpi["next_day_share"]))
    df = pd.DataFrame(rows, columns=["open_dcs", "n_open", "network_usd_week", "planning_usd_week", "stock_usd_week", "total_usd_week", "next_day_share"])
    df["rank_total"] = df.total_usd_week.rank(method="min").astype(int)
    df["rank_network_only"] = df.network_usd_week.rank(method="min").astype(int)
    return df.sort_values("total_usd_week").reset_index(drop=True)


def stress_tests(co: Company, terms: Terms):
    base = chain.run(co, terms)
    scen = [("Demand +20%", dict(terms=terms.with_(demand_scale=1.2))), ("Demand +50%", dict(terms=terms.with_(demand_scale=1.5))),
            ("Transport rate x2", dict(terms=terms.with_(rate_per_pallet_mile=terms.rate_per_pallet_mile * 2))),
            ("Deliveries 50% slower (lead times x1.5)", dict(terms=terms.with_(lead_time_scale=1.5))),
            ("Next-day delivery promise (600 miles)", dict(terms=terms.with_(max_delivery_miles=600))),
            ("DC fixed cost +50%", dict(terms=terms.with_(dc_fixed_scale=1.5)))]
    scen += [(f"{r.city} plant is down", dict(terms=terms, plants_down=[r.code])) for r in co.plants.itertuples()]
    rows = [("Base case", "feasible", ", ".join(co.city(d) for d in base.kpi["open_dcs"]), base.kpi["weekly_cost"], 0.0, base.kpi["cost_per_pallet"], base.kpi["safety_stock"], base.kpi["busiest_plant_peak_load"])]
    for name, kw in scen:
        r = chain.run(co, **kw)
        if not r.kpi["feasible"]:
            rows.append((name, "cannot meet demand", "", None, None, None, None, None))
            continue
        k = r.kpi
        rows.append((name, "feasible", ", ".join(co.city(d) for d in k["open_dcs"]), k["weekly_cost"], k["weekly_cost"] / base.kpi["weekly_cost"] - 1,
                     k["cost_per_pallet"], k["safety_stock"], k["busiest_plant_peak_load"]))
    return pd.DataFrame(rows, columns=["scenario", "status", "open_dcs", "weekly_cost_usd", "change_vs_base", "cost_per_pallet_usd", "safety_stock_pallets", "busiest_plant_peak_load"])


def input_sensitivity(co: Company, terms: Terms, spread=0.20):
    """Move each input down and up by `spread` (service level by 2 points) and record total weekly cost."""
    mid = chain.run(co, terms).kpi["weekly_cost"]
    plan = [("Demand", "demand_scale", terms.demand_scale), ("Transport rate per mile", "rate_per_pallet_mile", terms.rate_per_pallet_mile),
            ("DC fixed cost", "dc_fixed_scale", terms.dc_fixed_scale), ("Holding cost rate", "holding_rate_year", terms.holding_rate_year),
            ("Production setup cost", "setup_cost", terms.setup_cost), ("Lead times", "lead_time_scale", terms.lead_time_scale)]
    rows = []
    for label, key, v in plan:
        lo = chain.run(co, terms.with_(**{key: v * (1 - spread)})).kpi["weekly_cost"]
        hi = chain.run(co, terms.with_(**{key: v * (1 + spread)})).kpi["weekly_cost"]
        rows.append((label, abs(hi - lo), abs(hi - lo) / mid))
    lo = chain.run(co, terms.with_(service_level=terms.service_level - 0.02)).kpi["weekly_cost"]
    hi = chain.run(co, terms.with_(service_level=terms.service_level + 0.02)).kpi["weekly_cost"]
    rows.append(("Service level (+/- 2 points)", abs(hi - lo), abs(hi - lo) / mid))
    return pd.DataFrame(rows, columns=["input", "swing_usd_week", "swing_share_of_cost"]).sort_values("swing_usd_week", ascending=False).reset_index(drop=True)


def cost_to_serve(co: Company, base: chain.ChainResult):
    """Logistics cost to deliver one pallet to each market. Production cost is left out so markets compare fairly across product mix:
    inbound plant -> DC, DC handling, DC fixed cost spread over its volume, outbound DC -> market."""
    net, t = base.net, base.terms
    dc = co.dcs.set_index("code")
    fi = net.flows_in.assign(usd=lambda d: [t.rate_per_pallet_mile * co.mi_in.loc[a, b] for a, b in zip(d.plant, d.dc)])
    inbound = (fi.usd * fi.pallets).groupby([fi.dc, fi.sku]).sum() / fi.pallets.groupby([fi.dc, fi.sku]).sum()
    dc_volume = net.flows_out.groupby("dc").pallets.sum()
    f = net.flows_out.copy()
    f["inbound"] = [inbound[d, s] for d, s in zip(f.dc, f.sku)]
    f["handling"] = f.dc.map(dc.handling)
    f["dc_fixed"] = [dc.loc[d, "fixed_year"] * t.dc_fixed_scale / t.weeks_per_year / dc_volume[d] for d in f.dc]
    f["outbound"] = [t.rate_per_pallet_mile * co.mi_out.loc[d, m] for d, m in zip(f.dc, f.market)]
    parts = ["inbound", "handling", "dc_fixed", "outbound"]
    g = f.assign(**{c: f[c] * f.pallets for c in parts}).groupby("market")[["pallets"] + parts].sum()
    for c in parts:
        g[c] = g[c] / g.pallets
    g["logistics_usd_per_pallet"] = g[parts].sum(axis=1)
    g["served_from"] = f.groupby("market").dc.agg(lambda s: ", ".join(co.city(d) for d in sorted(s.unique())))
    g.insert(0, "city", [co.city(m) for m in g.index])
    return g.sort_values("logistics_usd_per_pallet", ascending=False).reset_index().rename(columns={"market": "market_code", "pallets": "pallets_per_week"})


def demand_headroom(co: Company, terms: Terms, tol=0.01):
    """The largest demand multiplier the network can still serve (bisection on the network model only)."""
    from . import network
    lo, hi = 1.0, 4.0
    if not network.design(co, terms.with_(demand_scale=lo)).ok:
        return 1.0
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if network.design(co, terms.with_(demand_scale=mid)).ok else (lo, mid)
    return lo


def single_sourced_items(co: Company):
    """Items that only one plant can make: losing that plant stops the item completely."""
    return {s: [p for p in co.codes("plants") if s in co.can_make(p)] for s in co.codes("skus") if sum(s in co.can_make(p) for p in co.codes("plants")) == 1}


def assumption_sensitivity(co: Company, terms: Terms):
    """How much do the planning assumptions (not the data) change the answer? Each is moved across a plausible range."""
    from dataclasses import replace
    base = chain.run(co, terms)
    sets = [("Delivery radius (miles)", "max_delivery_miles", [900, 1100, 1300]),
            ("Capacity margin (share of peak-week capacity planned)", "max_utilisation", [0.85, 0.90, 0.95]),
            ("Shelf-life cover share", "cover_share_of_shelf_life", [0.4, 0.5, 0.6]),
            ("Holding rate (share of value a year)", "holding_rate_year", [0.15, 0.22, 0.30]),
            ("Freight rate (USD per pallet-mile)", "rate_per_pallet_mile", [0.085, 0.10, 0.115])]
    rows = []
    for label, key, values in sets:
        for v in values:
            r = chain.run(co, terms.with_(**{key: v}))
            rows.append((label, v, "feasible" if r.kpi["feasible"] else "cannot meet demand",
                         r.kpi["weekly_cost"] if r.kpi["feasible"] else None,
                         (r.kpi["weekly_cost"] / base.kpi["weekly_cost"] - 1) if r.kpi["feasible"] else None,
                         ", ".join(co.city(d) for d in r.kpi["open_dcs"]) if r.kpi["feasible"] else ""))
    for f in (1.10, 1.15, 1.20):                                    # road factor: rescale distances as if the factor were different
        scale = f / 1.15
        alt = replace(co, mi_in=(co.mi_in * scale).round(), mi_out=(co.mi_out * scale).round())
        r = chain.run(alt, terms)
        rows.append(("Road factor (road miles / straight line)", f, "feasible" if r.kpi["feasible"] else "cannot meet demand",
                     r.kpi["weekly_cost"] if r.kpi["feasible"] else None,
                     (r.kpi["weekly_cost"] / base.kpi["weekly_cost"] - 1) if r.kpi["feasible"] else None,
                     ", ".join(co.city(d) for d in r.kpi["open_dcs"]) if r.kpi["feasible"] else ""))
    return pd.DataFrame(rows, columns=["assumption", "value", "status", "weekly_cost_usd", "change_vs_base", "open_dcs"])
