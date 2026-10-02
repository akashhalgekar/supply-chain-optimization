"""Does the project hold up on other data? Build several different synthetic companies and run the same checks on each.

    python -m tidewell.robustness            # 10 companies
    python -m tidewell.robustness 3          # a quick run

Each company goes through the whole pipeline: simulated ERP/WMS/TMS extracts, ETL, models, then every check in checks.py.
Writes output/13_robustness_companies.csv, output/14_robustness_checks.csv and docs/ROBUSTNESS.md.
"""
import os, sys, tempfile, shutil, time
import pandas as pd
from . import store, synthetic, chain
from .checks import company_checks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_company(seed):
    spec, truth, widened = synthetic.feasible_company(seed)
    tmp = tempfile.mkdtemp()
    results = []
    try:
        co, tables = store.build(data_dir=tmp, regenerate=True, truth=truth)
        base = company_checks(truth, co, tables, lambda name, ok, detail="": results.append((name, bool(ok), detail)))
    finally:
        shutil.rmtree(tmp)
    k = base.kpi if base else {}
    row = dict(seed=seed, items=len(spec.skus), plants=len(spec.plants), dcs=len(spec.dcs), markets=len(spec.markets), demand_pallets_week=round(truth.demand.mu.sum()),
               service_radius_miles=int(spec.terms.max_delivery_miles), demand_spread=f"{spec.cv_range[0]:.2f}-{spec.cv_range[1]:.2f}", capacity_widened=widened,
               open_dcs=len(k.get("open_dcs", [])), weekly_cost_usd=round(k.get("weekly_cost", 0)), checks=len(results), passed=sum(r[1] for r in results))
    return row, [(seed,) + r for r in results]


def main(n=10):
    rows, checks = [], []
    for seed in range(1, n + 1):
        t0 = time.time()
        row, res = run_company(seed)
        rows.append(row); checks += res
        failed = [r[1] for r in res if not r[2]]
        print(f"company {seed:>2}: {row['items']} items, {row['plants']} plants, {row['dcs']} DCs, {row['markets']} markets, {row['demand_pallets_week']:,} pallets/week -> "
              f"{row['passed']}/{row['checks']} checks passed ({time.time() - t0:.0f}s)" + (f"  FAILED: {failed}" if failed else ""), flush=True)
    companies = pd.DataFrame(rows)
    detail = pd.DataFrame(checks, columns=["seed", "check", "passed", "detail"])
    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    companies.to_csv(os.path.join(ROOT, "output", "13_robustness_companies.csv"), index=False)
    detail.to_csv(os.path.join(ROOT, "output", "14_robustness_checks.csv"), index=False)
    write_report(companies, detail)
    return companies, detail


def write_report(companies, detail):
    total, passed = len(detail), int(detail.passed.sum())
    by_check = detail.groupby("check").passed.agg(["sum", "count"]).reset_index()
    rows = "\n".join(f"| {r.seed} | {r['items']} | {r.plants} | {r.dcs} | {r.markets} | {r.demand_pallets_week:,} | {r.service_radius_miles:,} | {r.demand_spread} | {r.open_dcs} | ${r.weekly_cost_usd:,.0f} | {r.passed}/{r.checks} |"
                     for _, r in companies.iterrows())
    failures = detail[~detail.passed]
    fail_txt = ("No check failed on any company." if failures.empty else "Failures:\n\n" + "\n".join(f"- company {r.seed}: {r.check} ({r.detail})" for r in failures.itertuples()))
    text = f"""# Robustness: does the project hold up on other data?

Tidewell is one company, so a good result on it could be luck or tuning. To test that, `python -m tidewell.robustness` builds {len(companies)} other fictional American
drinks companies and runs the whole pipeline on each: simulated ERP, WMS and TMS extracts, the ETL, the three models and every check in `tidewell/checks.py`.

Each company differs from Tidewell and from the others in:
- number of items ({companies['items'].min()} to {companies['items'].max()}), plants ({companies.plants.min()} to {companies.plants.max()}), candidate DCs ({companies.dcs.min()} to {companies.dcs.max()}) and markets ({companies.markets.min()} to {companies.markets.max()})
- cities, distances, demand level ({companies.demand_pallets_week.min():,} to {companies.demand_pallets_week.max():,} pallets a week) and how much weekly demand swings
- item costs, shelf lives, plant and DC capacities, which plant can make which item (so some items depend on a single plant)
- freight rate, setup cost, holding rate, service level, delivery radius and the shape of the seasonal curve

Capacities are sized from demand, so each company can serve itself. If a company could not, capacity is widened and the company marked.

## Result

**{passed} of {total} checks passed across {len(companies)} companies.** {fail_txt}

| Company | Items | Plants | DCs | Markets | Pallets/week | Radius (mi) | Demand spread | DCs opened | Weekly cost | Checks passed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{rows}

## What the checks prove on every company

- **The ETL recovers the truth** from messy files: items, plants, DCs, distances, cost terms, seasonal profile, demand mean and spread of every market-item pair, and lead times.
- **The models agree on the true and the recovered company.**
- **The plan is feasible:** demand met exactly, flows balance at every DC, no site above its limit in the peak week, every delivery inside the radius, no plant making an item it cannot make, no production week above plant capacity, no stock older than its shelf-life limit.
- **Production matches textbook Wagner-Whitin** wherever capacity does not bind, and never beats it.
- **Safety stock behaves:** never below the demand-only figure, fill rate at or above the service level, more stock for a higher service level.
- **Brute force agrees:** the model's DC choice has the lowest network cost of every possible set of DCs.
- **Analytics are consistent:** the savings waterfall adds up, losing a single-source plant is reported infeasible, and the demand headroom sits exactly at the edge of feasibility.

## What the test found

The first run of this test found two real problems, both fixed:
- The generator produced DC capacities that were not whole pallets a day, which a WMS cannot report. Capacities are now multiples of 5 pallets a week, so the ETL can recover them exactly.
- A capacity check was tighter than the solver's own numerical accuracy: four of ten companies exceeded plant capacity by 0.00001 of a pallet. The tolerance is now 0.001 pallet, and says so.

A third issue came up while building the generator: a large demand spread could make the simulator draw negative weekly demand. It now redraws, and fails loudly if that is impossible.

## What this does not prove

The companies are generated by the same code family, so this shows the pipeline and models are consistent and robust to size, geography, costs and messiness. It does not show that
the results match any real company. That needs real data (see `docs/DATA_AND_ASSUMPTIONS.md`).

## Per-check results

| Check | Passed |
| --- | --- |
{chr(10).join(f"| {r.check} | {int(r['sum'])}/{int(r['count'])} |" for _, r in by_check.iterrows())}
"""
    with open(os.path.join(ROOT, "docs", "ROBUSTNESS.md"), "w") as fh:
        fh.write(text)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
