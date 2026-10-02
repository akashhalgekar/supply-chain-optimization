"""Network design: which DCs to open, and how many pallets of each item flow plant -> DC -> market.

A facility-location problem solved as a mixed integer linear program. Minimise the weekly cost of
production + inbound transport + DC fixed cost + DC handling + outbound transport, so that every
market's demand is met and no plant or DC exceeds its weekly capacity.

Capacity is checked against the PEAK week, not the average. Demand in the busiest week is `co.peak` times the average,
so an average-week volume may only use 1/peak of a site's weekly capacity, and planners keep a safety margin on top
(terms.max_utilisation, 90% by default). Without this a network can look fine on average and be impossible to run in July.

Service rule: a market may only be served from a DC within terms.max_delivery_miles. Without it a model happily ships to Seattle
from Atlanta, which no delivery promise allows.
"""
from dataclasses import dataclass
import pandas as pd
import pulp
from .company import Company, Terms


@dataclass
class NetworkPlan:
    status: str
    open_dcs: list
    cost: dict                 # production, inbound, dc_fixed, handling, outbound, total (USD per week)
    co2_kg_week: float
    demand_pallets: float
    plant_volume: pd.DataFrame  # plant, sku, pallets
    flows_in: pd.DataFrame      # plant, dc, sku, pallets
    flows_out: pd.DataFrame     # dc, market, sku, pallets
    plant_load: dict            # plant -> average-week volume as a share of weekly capacity (peak week = this x co.peak)

    @property
    def ok(self):
        return self.status == "Optimal"


def design(co: Company, terms: Terms, dc_set=None, plants_down=()):
    """dc_set forces exactly that set of DCs open (used to test alternatives). plants_down removes plant capacity."""
    P, D, M, S = co.codes("plants"), co.codes("dcs"), co.codes("markets"), co.codes("skus")
    reach = {(d, m) for d in D for m in M if co.mi_out.loc[d, m] <= terms.max_delivery_miles}
    usable = set(D) if dc_set is None else set(dc_set)
    if any(not any((d, m) in reach for d in usable) for m in M):         # some market has no DC within the delivery radius
        empty = pd.DataFrame(columns=["plant", "dc", "sku", "pallets"])
        return NetworkPlan("Infeasible", [], {}, 0.0, 0.0, empty[["plant", "sku", "pallets"]], empty,
                           pd.DataFrame(columns=["dc", "market", "sku", "pallets"]), {})
    plant, dc = co.plants.set_index("code"), co.dcs.set_index("code")
    item_cost = co.skus.set_index("code")["cost_pallet"]
    need = {(r.market, r.sku): r.mu * terms.demand_scale for r in co.demand.itertuples()}
    fixed_week = {d: dc.loc[d, "fixed_year"] * terms.dc_fixed_scale / terms.weeks_per_year for d in D}
    rate = terms.rate_per_pallet_mile

    lp = pulp.LpProblem("network", pulp.LpMinimize)
    inbound = {(p, d, s): pulp.LpVariable(f"in_{p}_{d}_{s}", lowBound=0) for p in P for d in D for s in S if s in co.can_make(p)}
    outbound = {(d, m, s): pulp.LpVariable(f"out_{d}_{m}_{s}", lowBound=0) for d in D for m in M for s in S if (d, m) in reach}
    opened = {d: pulp.LpVariable(f"open_{d}", cat="Binary") for d in D}

    parts = {
        "production": pulp.lpSum(item_cost[s] * plant.loc[p, "cost_index"] * v for (p, d, s), v in inbound.items()),
        "inbound": pulp.lpSum(rate * co.mi_in.loc[p, d] * v for (p, d, s), v in inbound.items()),
        "dc_fixed": pulp.lpSum(fixed_week[d] * opened[d] for d in D),
        "handling": pulp.lpSum(dc.loc[d, "handling"] * v for (d, m, s), v in outbound.items()),
        "outbound": pulp.lpSum(rate * co.mi_out.loc[d, m] * v for (d, m, s), v in outbound.items()),
    }
    lp += pulp.lpSum(parts.values())

    for m in M:
        for s in S:
            lp += pulp.lpSum(outbound[d, m, s] for d in D if (d, m) in reach) == need.get((m, s), 0.0)
    for d in D:
        for s in S:
            lp += pulp.lpSum(v for (p, dd, ss), v in inbound.items() if dd == d and ss == s) == pulp.lpSum(outbound[d, m, s] for m in M if (d, m) in reach)
        lp += pulp.lpSum(v for (dd, m, s), v in outbound.items() if dd == d) <= dc.loc[d, "capacity"] * terms.max_utilisation / co.peak * opened[d]
    for p in P:
        cap = 0 if p in plants_down else plant.loc[p, "capacity"] * terms.max_utilisation / co.peak
        lp += pulp.lpSum(v for (pp, d, s), v in inbound.items() if pp == p) <= cap
    if dc_set is not None:
        for d in D:
            lp += opened[d] == (1 if d in set(dc_set) else 0)

    lp.solve(pulp.PULP_CBC_CMD(msg=0, gapRel=0, threads=4))
    val = lambda v: v.value() or 0.0
    flows_in = pd.DataFrame([(p, d, s, val(v)) for (p, d, s), v in inbound.items() if val(v) > 1e-6], columns=["plant", "dc", "sku", "pallets"])
    flows_out = pd.DataFrame([(d, m, s, val(v)) for (d, m, s), v in outbound.items() if val(v) > 1e-6], columns=["dc", "market", "sku", "pallets"])
    cost = {k: float(pulp.value(v) or 0.0) for k, v in parts.items()}
    cost["total"] = sum(cost.values())
    co2 = terms.co2_per_pallet_mile * (
        sum(co.mi_in.loc[r.plant, r.dc] * r.pallets for r in flows_in.itertuples())
        + sum(co.mi_out.loc[r.dc, r.market] * r.pallets for r in flows_out.itertuples()))
    volume = flows_in.groupby(["plant", "sku"], as_index=False).pallets.sum() if len(flows_in) else pd.DataFrame(columns=["plant", "sku", "pallets"])
    load = {p: (flows_in[flows_in.plant == p].pallets.sum() / plant.loc[p, "capacity"]) if len(flows_in) else 0.0 for p in P}
    return NetworkPlan(pulp.LpStatus[lp.status], [d for d in D if val(opened[d]) > 0.5], cost, co2, float(sum(need.values())),
                       volume, flows_in, flows_out, load)
