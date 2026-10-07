"""Production planning: when and how much each plant makes of each item.

Each plant must make a known weekly volume of each item (from the network design), shaped over the planning weeks by the
demand planners' seasonal profile. Starting a production run costs a setup; keeping finished pallets costs money every week
(a share of the item's value). Few big runs save setups but build stock. That trade-off is the classic lot-sizing problem.

Beverages also expire. Stock may not sit longer than a share of the item's shelf life (retailers will not accept product with
less than about half its life left), so a batch may only cover that many weeks of demand.

Two solvers, on purpose:
  wagner_whitin()   the textbook dynamic programme for ONE item with no capacity limit. Provably optimal.
  plan()            all items of a plant together as a mixed integer program, so the plant's weekly planning limit
                    (capacity x max_utilisation) is respected.
                    Equals Wagner-Whitin whenever capacity does not bind.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
import pulp
from .company import Company, Terms


def wagner_whitin(demand, setup_cost, hold_cost, max_cover=None):
    """Cheapest production plan for one item. max_cover limits how many weeks of demand one batch may serve (shelf life).
    Returns dict(produce, stock, runs, setup, holding, total)."""
    d = np.asarray(demand, dtype=float)
    n = len(d)
    cover = n if max_cover is None else max_cover
    after = np.concatenate([[0.0], np.cumsum(d)])
    best, came_from = np.full(n + 1, np.inf), np.zeros(n + 1, dtype=int)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(max(1, j - cover + 1), j + 1):            # make in week i everything needed for weeks i..j
            holding = hold_cost * float((d[i - 1:j] * np.arange(0, j - i + 1)).sum())
            cost = best[i - 1] + setup_cost + holding
            if cost < best[j] - 1e-12:
                best[j], came_from[j] = cost, i
    produce, j = np.zeros(n), n
    while j > 0:
        i = came_from[j]
        produce[i - 1] = after[j] - after[i - 1]
        j = i - 1
    stock = np.cumsum(produce - d)
    runs = int((produce > 1e-9).sum())
    return dict(produce=produce, stock=stock, runs=runs, setup=runs * setup_cost, holding=float(hold_cost * stock.sum()), total=float(best[n]))


@dataclass
class LotPlan:
    weekly: pd.DataFrame        # plant, sku, week, demand, produce, stock
    by_plant: pd.DataFrame      # plant, items, runs, setup_cost, holding_cost, total
    runs: int
    setup_cost: float
    holding_cost: float
    total: float
    weekly_runs_baseline: int   # runs if every item were made every week
    baseline_total: float       # cost of making to demand each week (a setup every week, no stock)
    avg_stock: float

    @property
    def saved(self):
        return self.baseline_total - self.total


def _capacitated(co, plant, cap, vol, need, terms, weeks):
    """All items of one plant at once, respecting weekly capacity and shelf life. Returns {(sku, week): (make, keep)} and the runs."""
    total_need = {s: sum(need[s, w] for w in weeks) for s in vol}
    lp = pulp.LpProblem(f"lots_{plant}", pulp.LpMinimize)
    make = {(s, w): pulp.LpVariable(f"q_{s}_{w}", lowBound=0) for s in vol for w in weeks}
    keep = {(s, w): pulp.LpVariable(f"i_{s}_{w}", lowBound=0) for s in vol for w in weeks}
    run = {(s, w): pulp.LpVariable(f"z_{s}_{w}", cat="Binary") for s in vol for w in weeks}
    lp += pulp.lpSum(terms.setup_cost * run[k] + co.hold_week(k[0], terms) * keep[k] for k in run)
    for s in vol:
        cover = co.max_cover_weeks(s, terms)
        for w in weeks:
            lp += keep[s, w] == (keep[s, w - 1] if w > 1 else 0) + make[s, w] - need[s, w]
            lp += make[s, w] <= min(total_need[s], cap) * run[s, w]
            lp += keep[s, w] <= sum(need[s, t] for t in weeks if w < t <= w + cover - 1)      # FIFO: nothing older than the cover limit
    for w in weeks:
        lp += pulp.lpSum(make[s, w] for s in vol) <= cap
    lp.solve(pulp.PULP_CBC_CMD(msg=0, gapRel=0, threads=4))
    if pulp.LpStatus[lp.status] != "Optimal":
        raise RuntimeError(f"No feasible production plan for {plant}: the peak weeks exceed its weekly planning limit")
    return {k: (make[k].value() or 0.0, keep[k].value() or 0.0) for k in make}, sum(1 for k in run if (run[k].value() or 0) > 0.5)


_CACHE = {}


def plan(co: Company, terms: Terms, plant_volume: pd.DataFrame, force_solver=False) -> LotPlan:
    """Fast path: solve every item with Wagner-Whitin and keep the answer if no week overloads the plant. Otherwise (or if
    force_solver) solve the plant as one capacity-aware program. Both give the same cost when capacity does not bind."""
    plants = co.plants.set_index("code")
    weeks = range(1, len(co.season) + 1)
    rows, summary, base_runs = [], [], 0
    for plant, grp in plant_volume.groupby("plant"):
        vol = {r.sku: r.pallets for r in grp.itertuples() if r.pallets > 1e-6}
        if not vol:
            continue
        cap = plants.loc[plant, "capacity"] * terms.max_utilisation      # same planning limit as the network model (90% by default)
        need = {(s, w): vol[s] * co.season[w - 1] for s in vol for w in weeks}
        base_runs += sum(1 for v in need.values() if v > 1e-6)
        key = (plant, tuple(sorted((k, round(v, 3)) for k, v in vol.items())), terms.setup_cost, terms.holding_rate_year, cap, force_solver,
               terms.cover_share_of_shelf_life)
        if key not in _CACHE:                                         # scenario sweeps often repeat a plant's volumes
            ww = {s: wagner_whitin([need[s, w] for w in weeks], terms.setup_cost, co.hold_week(s, terms), co.max_cover_weeks(s, terms)) for s in vol}
            week_load = np.sum([ww[s]["produce"] for s in vol], axis=0)
            if not force_solver and (week_load <= cap + 1e-6).all():
                _CACHE[key] = ({(s, w): (ww[s]["produce"][w - 1], ww[s]["stock"][w - 1]) for s in vol for w in weeks}, sum(ww[s]["runs"] for s in vol))
            else:
                _CACHE[key] = _capacitated(co, plant, cap, vol, need, terms, weeks)
        sol, n_runs = _CACHE[key]
        for s in vol:
            for w in weeks:
                rows.append((plant, s, w, need[s, w], sol[s, w][0], sol[s, w][1]))
        holding = sum(co.hold_week(k[0], terms) * v[1] for k, v in sol.items())
        summary.append((plant, len(vol), n_runs, n_runs * terms.setup_cost, holding, n_runs * terms.setup_cost + holding))

    weekly = pd.DataFrame(rows, columns=["plant", "sku", "week", "demand", "produce", "stock"])
    by_plant = pd.DataFrame(summary, columns=["plant", "items", "runs", "setup_cost", "holding_cost", "total"])
    return LotPlan(weekly, by_plant, int(by_plant.runs.sum()), float(by_plant.setup_cost.sum()), float(by_plant.holding_cost.sum()),
                   float(by_plant.total.sum()), base_runs, base_runs * terms.setup_cost, float(weekly.stock.mean()) if len(weekly) else 0.0)
