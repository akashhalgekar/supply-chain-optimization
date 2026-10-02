"""Run the whole project once: data -> ETL -> models -> analytics. Writes output/ (CSV), charts/ (PNG) and docs/EXECUTIVE_SUMMARY.md.

    python -m tidewell.run
"""
import os
import pandas as pd
from . import store, chain, analytics, plots, flow, report, lotsizing, safetystock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT, CH, DOCS = (os.path.join(ROOT, d) for d in ("output", "charts", "docs"))


def main():
    for d in (OUT, CH, DOCS):
        os.makedirs(d, exist_ok=True)
    co, tables = store.build(regenerate=True)
    terms = co.terms
    base = chain.run(co, terms)
    net, lots, stock, k = base.net, base.lots, base.stock, base.kpi
    city = co.city

    tables["data_quality_log"].to_csv(f"{OUT}/01_data_quality_log.csv", index=False)
    pd.DataFrame([dict(open_dcs=", ".join(city(d) for d in net.open_dcs), **{f"{a}_usd_week": round(v) for a, v in net.cost.items()}, co2_kg_week=round(net.co2_kg_week))]).to_csv(f"{OUT}/02_network_summary.csv", index=False)
    pd.DataFrame([(city(d), d in net.open_dcs) for d in co.codes("dcs")], columns=["dc", "open"]).to_csv(f"{OUT}/02_dc_open_closed.csv", index=False)
    net.plant_volume.assign(plant=lambda d: d.plant.map(city), pallets=lambda d: d.pallets.round(1)).to_csv(f"{OUT}/02_plant_volumes.csv", index=False)
    net.flows_out.assign(dc=lambda d: d.dc.map(city), market=lambda d: d.market.map(city), pallets=lambda d: d.pallets.round(1)).to_csv(f"{OUT}/02_dc_to_market_flows.csv", index=False)
    lots.weekly.assign(plant=lambda d: d.plant.map(city)).round(1).to_csv(f"{OUT}/03_production_plan.csv", index=False)
    lots.by_plant.assign(plant=lambda d: d.plant.map(city)).round(0).to_csv(f"{OUT}/03_production_cost_by_plant.csv", index=False)
    stock.detail.assign(dc=lambda d: d.dc.map(city)).round(1).to_csv(f"{OUT}/04_safety_stock_by_dc_item.csv", index=False)
    pd.DataFrame([dict(weekly_cost_usd=round(k["weekly_cost"]), annual_cost_usd=round(k["annual_cost"]), cost_per_pallet_usd=round(k["cost_per_pallet"], 1),
                       co2_tonnes_year=round(float(k["co2_tonnes_year"]), 1), service_level=k["service_level"], fill_rate=round(k["fill_rate"], 4),
                       network_usd_week=round(k["network_cost"]), planning_usd_week=round(k["planning_cost"]), stock_usd_week=round(k["stock_cost"]))]).to_csv(f"{OUT}/05_scorecard.csv", index=False)

    # sensitivities for the charts
    rows = []
    for sc in (800, 1600, 2400, 4000, 6000, 9000):
        lp = lotsizing.plan(co, terms.with_(setup_cost=sc), net.plant_volume)
        rows.append((sc, lp.runs, lp.setup_cost, lp.holding_cost, lp.total, lp.avg_stock))
    setup = pd.DataFrame(rows, columns=["setup_cost", "runs", "setup_total", "holding_total", "planning_cost", "avg_stock"]).round(1)
    setup.to_csv(f"{OUT}/06_sensitivity_setup_cost.csv", index=False)
    rows = []
    for csl in (0.90, 0.95, 0.98, 0.99):
        for lt in (0.5, 1.0, 2.0):
            s = safetystock.size(co, terms.with_(service_level=csl, lead_time_scale=lt), net)
            rows.append((csl, lt, s.safety_stock, round(s.holding_year), round(s.fill_rate, 4)))
    curves = pd.DataFrame(rows, columns=["service_level", "lead_time_scale", "safety_stock", "holding_usd_year", "fill_rate"])
    curves.to_csv(f"{OUT}/07_sensitivity_service_and_lead_time.csv", index=False)

    # decision analytics
    wf = analytics.savings_waterfall(co, base); wf.round(4).to_csv(f"{OUT}/08_savings_vs_reference.csv", index=False)
    sets = analytics.dc_set_comparison(co, terms); sets.round(0).to_csv(f"{OUT}/09_dc_set_comparison.csv", index=False)
    stress = analytics.stress_tests(co, terms); stress.round(4).to_csv(f"{OUT}/10_stress_tests.csv", index=False)
    sens = analytics.input_sensitivity(co, terms); sens.round(4).to_csv(f"{OUT}/11_input_sensitivity.csv", index=False)
    cts = analytics.cost_to_serve(co, base); cts.round(2).to_csv(f"{OUT}/12_cost_to_serve_by_market.csv", index=False)
    headroom = analytics.demand_headroom(co, terms)
    late = analytics.late_delivery_sensitivity(co, terms, base); late.round(4).to_csv(f"{OUT}/16_late_delivery_sensitivity.csv", index=False)
    assum = analytics.assumption_sensitivity(co, terms); assum.round(4).to_csv(f"{OUT}/15_assumption_sensitivity.csv", index=False)

    # charts
    flow.draw(flow.facts_from(co, tables, base), f"{CH}/01_end_to_end_flowchart.png")
    plots.network_map(co, net, f"{CH}/02_network_map.png")
    g = lots.weekly.groupby(["plant", "sku"]).agg(avg=("stock", "mean"), tot=("produce", "sum")).reset_index()
    pick = g[g.tot > 1e-6].sort_values("avg", ascending=False).iloc[0]
    plots.production_plan(lots, city(pick.plant), pick.plant, pick.sku, f"{CH}/03_production_plan.png")
    plots.setup_tradeoff(setup, f"{CH}/04_setup_cost_tradeoff.png")
    plots.stock_curves(curves, f"{CH}/05_safety_stock_vs_service_level.png")
    plots.waterfall(wf, f"{CH}/06_savings_waterfall.png")
    plots.dc_sets(sets, f"{CH}/07_dc_set_comparison.png")
    plots.stress(stress, f"{CH}/08_stress_tests.png")
    plots.tornado(sens, f"{CH}/09_input_sensitivity.png")
    plots.cost_to_serve(cts, f"{CH}/10_cost_to_serve.png")

    with open(f"{DOCS}/EXECUTIVE_SUMMARY.md", "w") as fh:
        fh.write(report.executive_summary(co, base, wf, sets, stress, sens, cts, headroom, tables, late))

    print(f"Open DCs: {', '.join(city(d) for d in net.open_dcs)}  |  weekly cost ${k['weekly_cost']:,.0f}  |  saving vs reference case {wf.share_of_reference.iloc[-1]:.1%}")
    print(f"Production runs {lots.weekly_runs_baseline} -> {lots.runs}  |  safety stock {stock.safety_stock:,} pallets  |  fill rate {stock.fill_rate:.1%}  |  demand headroom {headroom - 1:.0%}")
    print("Wrote output/, charts/ and docs/EXECUTIVE_SUMMARY.md")


if __name__ == "__main__":
    main()
