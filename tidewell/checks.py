"""Checks that hold for ANY company, not just Tidewell. verify.py runs them on Tidewell; robustness.py runs them on random companies.

company_checks(truth, co, tables, emit) takes the true company, the company the ETL recovered from the messy files, and the clean tables.
emit(name, passed, detail) records each result.
"""
import itertools
import numpy as np
import pandas as pd
from . import chain, lotsizing, safetystock, analytics, network
from .sources import ORDER_PROCESSING_DAYS, TRUCK_MILES_PER_DAY


def _same(a, b, atol=1e-9):
    try:
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True), check_dtype=False, atol=atol)
        return True
    except AssertionError:
        return False


def company_checks(truth, co, tables, emit):
    t = co.terms

    # 1. the ETL recovers the true company from the messy extracts
    emit("ETL: items", _same(truth.skus, co.skus))
    emit("ETL: plants (capacity, cost index, items)", _same(truth.plants, co.plants))
    emit("ETL: DCs (fixed cost, weekly capacity, handling)", _same(truth.dcs, co.dcs))
    emit("ETL: market codes and cities", _same(truth.markets[["code", "city"]], co.markets[["code", "city"]]))
    m = truth.demand.merge(co.demand, on=["market", "sku"], suffixes=("_t", "_c"))
    emit("ETL: demand mean, every market x item", len(m) == len(truth.demand) and np.allclose(m.mu_t, m.mu_c, atol=0.05), f"{len(m)} pairs, max gap {abs(m.mu_t - m.mu_c).max():.2f} pallets")
    emit("ETL: demand spread, every market x item", np.allclose(m.sigma_t, m.sigma_c, atol=0.05), f"max gap {abs(m.sigma_t - m.sigma_c).max():.2f} pallets")
    emit("ETL: plant-to-DC distances", (truth.mi_in.values == co.mi_in.values).all())
    emit("ETL: DC-to-market distances", (truth.mi_out.values == co.mi_out.values).all())
    tt = truth.terms
    emit("ETL: cost terms", np.allclose([tt.setup_cost, tt.holding_rate_year, tt.rate_per_pallet_mile, tt.co2_per_pallet_mile],
                                        [t.setup_cost, t.holding_rate_year, t.rate_per_pallet_mile, t.co2_per_pallet_mile]))
    emit("ETL: seasonal profile from the demand planners", np.allclose(co.season, truth.season))
    expected = np.array([(ORDER_PROCESSING_DAYS + truth.mi_in[d].mean() / TRUCK_MILES_PER_DAY) / 7 for d in co.codes("dcs")])
    measured = np.array([dict((d, mn) for d, mn, _ in t.lead_time_by_dc)[d] for d in co.codes("dcs")])
    emit("ETL: lead times measured from receipts match order processing plus driving time", np.allclose(expected, measured, atol=0.03), f"max gap {abs(expected - measured).max():.3f} weeks")

    # 2. the models agree on the true and the recovered company
    truth.terms = t
    a, b = chain.run(truth), chain.run(co)
    emit("MODELS: the chain is feasible", b.kpi["feasible"] and a.kpi["feasible"])
    if not b.kpi["feasible"]:
        return None
    emit("MODELS: same open DCs on true and recovered data", a.kpi["open_dcs"] == b.kpi["open_dcs"], ", ".join(co.city(d) for d in b.kpi["open_dcs"]))
    emit("MODELS: weekly cost within 0.01% on true and recovered data", abs(a.kpi["weekly_cost"] - b.kpi["weekly_cost"]) / a.kpi["weekly_cost"] < 1e-4,
         f"{a.kpi['weekly_cost']:,.0f} vs {b.kpi['weekly_cost']:,.0f}")

    # 3. the plan is feasible
    net, lots, stock = b.net, b.lots, b.stock
    out = net.flows_out.groupby(["market", "sku"]).pallets.sum()
    need = co.demand.set_index(["market", "sku"]).mu * t.demand_scale
    emit("PLAN: every market's demand is met exactly", np.allclose(out.reindex(need.index).fillna(0), need, atol=1e-6))
    dc_in, dc_out = net.flows_in.groupby("dc").pallets.sum(), net.flows_out.groupby("dc").pallets.sum()
    emit("PLAN: what enters each DC equals what leaves", np.allclose(dc_in.reindex(net.open_dcs).fillna(0), dc_out.reindex(net.open_dcs).fillna(0), atol=1e-6))
    emit("PLAN: no plant above the planning limit in the peak week", all(v * co.peak <= t.max_utilisation + 1e-6 for v in net.plant_load.values()))
    dcl = dc_out * co.peak / co.dcs.set_index("code").capacity.reindex(dc_out.index)
    emit("PLAN: no DC above the planning limit in the peak week", (dcl <= t.max_utilisation + 1e-6).all(), f"busiest {dcl.max():.0%}")
    emit("PLAN: every delivery is within the service radius", all(co.mi_out.loc[r.dc, r.market] <= t.max_delivery_miles for r in net.flows_out.itertuples()), f"{t.max_delivery_miles:,.0f} miles")
    emit("PLAN: every plant only makes items it can make", all(r.sku in co.can_make(r.plant) for r in net.flows_in.itertuples()))
    capacity = co.plants.set_index("code").capacity
    limit = capacity * t.max_utilisation                                 # planning limit, the same rule the network uses
    weekly_load = lots.weekly.groupby(["plant", "week"]).produce.sum().reset_index()
    busiest = max((r.produce / capacity[r.plant] for r in weekly_load.itertuples()), default=0.0)
    emit("PLAN: production never exceeds a plant's planning limit in any week", all(r.produce <= limit[r.plant] + 1e-3 for r in weekly_load.itertuples()),
         f"busiest week {busiest:.0%} of capacity")
    emit("PLAN: every item's production covers its demand", np.allclose(lots.weekly.groupby(["plant", "sku"]).produce.sum(), lots.weekly.groupby(["plant", "sku"]).demand.sum(), atol=1e-4))
    bad = []
    for (plant, sku), g in lots.weekly.groupby(["plant", "sku"]):
        g, k = g.sort_values("week"), co.max_cover_weeks(sku, t)
        bad += [(plant, sku, r.week) for i, r in enumerate(g.itertuples()) if r.stock > g.demand.iloc[i + 1: i + k].sum() + 1e-3]
    emit("PLAN: no stock sits longer than the shelf-life limit", not bad, "limits in weeks: " + ", ".join(f"{s} {co.max_cover_weeks(s, t)}" for s in co.codes("skus")))

    # 4. production plan versus textbook Wagner-Whitin
    ww_total, differ, overloaded = 0.0, set(), set()
    for plant, grp in net.plant_volume.groupby("plant"):
        series = {r.sku: [r.pallets * s for s in co.season] for r in grp.itertuples() if r.pallets > 1e-6}
        if not series:
            continue
        plans = {s: lotsizing.wagner_whitin(v, t.setup_cost, co.hold_week(s, t), co.max_cover_weeks(s, t)) for s, v in series.items()}
        load = np.sum([p["produce"] for p in plans.values()], axis=0)
        if (load > limit[plant] + 1e-6).any():
            overloaded.add(plant)
        ww = sum(p["total"] for p in plans.values())
        ww_total += ww
        if abs(lots.by_plant.set_index("plant").loc[plant, "total"] - ww) > 1:
            differ.add(plant)
    emit("WW: the capacity-aware plan never beats the textbook lower bound", lots.total >= ww_total - 1, f"${lots.total:,.0f} vs ${ww_total:,.0f}")
    emit("WW: plants where the two differ are exactly those where the textbook plan breaks the planning limit", differ == overloaded, f"{len(differ)} differ")
    free = lotsizing.plan(co, t, net.plant_volume, force_solver=True)
    emit("WW: forcing the capacity solver gives the same cost as the fast path", abs(free.total - lots.total) < 1.0)

    # 5. safety stock
    d = stock.detail
    emit("STOCK: with lead-time risk, never below demand-only", (d.safety_stock >= d.safety_demand_only - 1e-6).all())
    emit("STOCK: fill rate at or above the cycle service level", stock.fill_rate >= t.service_level, f"{stock.fill_rate:.1%} vs {t.service_level:.0%}")
    emit("STOCK: higher service level means more stock", safetystock.size(co, t.with_(service_level=min(0.995, t.service_level + 0.03)), net).safety_stock > stock.safety_stock)
    emit("STOCK: DC volumes add up to total demand", np.isclose(d.groupby("dc").mu.sum().sum(), net.demand_pallets))

    # 6. the network choice against brute force over every set of DCs
    dcs = co.codes("dcs")
    best = np.inf
    for k in range(1, len(dcs) + 1):
        for subset in itertools.combinations(dcs, k):
            r = network.design(co, t, dc_set=list(subset))
            if r.ok:
                best = min(best, r.cost["total"])
    emit("BRUTE FORCE: the model's DC choice is the cheapest of every workable set on network cost", abs(net.cost["total"] - best) <= 1e-6 * best + 1e-6, f"{2 ** len(dcs) - 1} sets tried")

    # 7. analytics
    wf = analytics.savings_waterfall(co, b)
    emit("ANALYTICS: savings waterfall adds up", abs(wf.usd_per_week.iloc[0] + wf.usd_per_week.iloc[1] + wf.usd_per_week.iloc[2] - wf.usd_per_week.iloc[3]) < 1e-6)
    for item, plants in analytics.single_sourced_items(co).items():
        emit(f"ANALYTICS: losing {co.city(plants[0])} stops {item} (single-sourced), so the model reports infeasible", not chain.run(co, t, plants_down=plants).kpi["feasible"])
    h = analytics.demand_headroom(co, t)
    emit("ANALYTICS: headroom is the edge of feasibility", network.design(co, t.with_(demand_scale=h)).ok and not network.design(co, t.with_(demand_scale=h + 0.05)).ok, f"+{h - 1:.0%}")
    return b
