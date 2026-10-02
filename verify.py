"""Checks that the data pipeline and the models hold together.   python verify.py"""
import os, shutil, sys, tempfile
import numpy as np
import pandas as pd
from tidewell import store, etl, chain, lotsizing, safetystock, analytics, network
from tidewell.checks import company_checks
from tidewell.company import ground_truth

ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


truth = ground_truth()
co, tables = store.build(regenerate=True)
print("1-6. Checks that hold for any company (shared with the robustness test)")
base = company_checks(truth, co, tables, check)
t = co.terms
stock, lots, net, b = base.stock, base.lots, base.net, base
h = analytics.demand_headroom(co, t)

print("6b. Tidewell only: the whole chain costed for every DC set")
sets = analytics.dc_set_comparison(co, t)
chosen = ", ".join(co.city(d) for d in net.open_dcs)
gap = sets[sets.open_dcs == chosen].total_usd_week.iloc[0] - sets.total_usd_week.min()
check("choosing on network cost alone costs under 0.5% on the whole chain", gap / sets.total_usd_week.min() < 0.005, f"${gap:,.0f} a week")
wf = analytics.savings_waterfall(co, b)
ww_total = 0.0
for plant, grp in net.plant_volume.groupby("plant"):
    series = {r.sku: [r.pallets * s for s in co.season] for r in grp.itertuples() if r.pallets > 1e-6}
    ww_total += sum(lotsizing.wagner_whitin(v, t.setup_cost, co.hold_week(s, t), co.max_cover_weeks(s, t))["total"] for s, v in series.items())

print("6c. Inputs checked against outside references")
ref = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "reference", "road_distances.csv"))
from tidewell.company import miles_between
est = np.array([miles_between(a, c) for a, c in zip(ref.city_a, ref.city_b)])
err = (est - ref.driving_miles.to_numpy()) / ref.driving_miles.to_numpy()
check("estimated road miles fit 16 known driving distances (mean error under 8%, bias under 3%)", np.abs(err).mean() < 0.08 and abs(err.mean()) < 0.03,
      f"mean error {np.abs(err).mean():.1%}, bias {err.mean():+.1%}, worst {np.abs(err).max():.1%}")
check("freight rate is inside the 2026 truckload range ($2.25-2.50 linehaul plus fuel, 26 pallets a trailer)", 2.25 / 26 <= t.rate_per_pallet_mile <= 3.2 / 26, f"${t.rate_per_pallet_mile:.3f} a pallet-mile = ${t.rate_per_pallet_mile * 26:.2f} a truckload mile")
check("holding rate is inside the 20-30% a year range for packaged consumer goods", 0.20 <= t.holding_rate_year <= 0.30, f"{t.holding_rate_year:.0%}")
check("every item's shelf-life cover limit is at least one week", all(co.max_cover_weeks(s, t) >= 1 for s in co.codes("skus")))

print("6d. The checks have teeth: they must FAIL on deliberately broken inputs")
tmp = tempfile.mkdtemp()
shutil.copytree(os.path.join(store.DATA_DIR, "raw"), os.path.join(tmp, "raw"))
lanes_f = os.path.join(tmp, "raw", "tms_lanes.csv")
lanes = pd.read_csv(lanes_f)
lanes["distance_unit"] = "mi"                                    # kilometre quotes mislabelled as miles
lanes.to_csv(lanes_f, index=False)
etl.run(os.path.join(tmp, "raw"), os.path.join(tmp, "wh"))
co_bad = store.load_company(os.path.join(tmp, "wh"))
shutil.rmtree(tmp)
check("a mislabelled distance unit is caught by the distance check", not (truth.mi_in.values == co_bad.mi_in.values).all() or not (truth.mi_out.values == co_bad.mi_out.values).all())
tight = t.with_(max_delivery_miles=600)
wide_plan = network.design(co, t)
check("a delivery plan that ignores a tighter radius is caught by the radius check", any(co.mi_out.loc[r.dc, r.market] > tight.max_delivery_miles for r in wide_plan.flows_out.itertuples()))
low_cap = co.plants.copy(); low_cap["capacity"] = low_cap["capacity"] * 0.5
check("a plan checked against halved plant capacity is caught by the capacity check", any(r.produce > low_cap.set_index("code").capacity[r.plant] for r in base.lots.weekly.groupby(["plant", "week"]).produce.sum().reset_index().itertuples()))

print("6e. The dashboard opens on the same numbers as the documents")
from tidewell import api
dials = api.Dials()
check("dashboard default dials equal the company's terms", all(abs(getattr(dials, n) - getattr(t, n)) < 1e-12 for n in ("demand_scale", "service_level", "rate_per_pallet_mile", "dc_fixed_scale", "setup_cost", "lead_time_scale")))
shown = api.run(dials)
check("dashboard default run reproduces the headline weekly cost", shown["feasible"] and abs(shown["kpi"]["weekly_cost"] - b.kpi["weekly_cost"]) < 0.01, f"${shown['kpi']['weekly_cost']:,.0f} vs ${b.kpi['weekly_cost']:,.0f}")
check("dashboard default run reproduces the open DCs", shown["open_dcs"] == [co.city(d) for d in b.kpi["open_dcs"]])

print("7. ETL safeguards")
check("control total recorded", tables["data_quality_log"].step.str.startswith("control total").any())
tmp = tempfile.mkdtemp()
shutil.copytree(os.path.join(store.DATA_DIR, "raw"), os.path.join(tmp, "raw"))
f = os.path.join(tmp, "raw", "erp_sales_orders.csv")
orders = pd.read_csv(f)
pd.concat([orders, orders.sample(frac=0.30, random_state=1)]).to_csv(f, index=False)
try:
    etl.run(os.path.join(tmp, "raw"), os.path.join(tmp, "wh")); stopped = False
except ValueError:
    stopped = True
shutil.rmtree(tmp)
check("ETL refuses an extract with 30% duplicate order lines", stopped)

print("8. The documents quote this run's numbers")
ROOT = os.path.dirname(os.path.abspath(__file__))
read = lambda *p: open(os.path.join(ROOT, *p)).read()
for need in ("11_input_sensitivity.csv", "12_cost_to_serve_by_market.csv"):
    check(f"output/{need} exists (run `python -m tidewell.run` first)", os.path.exists(os.path.join(ROOT, "output", need)))
sens = pd.read_csv(os.path.join(ROOT, "output", "11_input_sensitivity.csv")).set_index("input")
cts = pd.read_csv(os.path.join(ROOT, "output", "12_cost_to_serve_by_market.csv"))
k = b.kpi
sq = wf.eur_per_week.iloc[0] if "eur_per_week" in wf else wf.usd_per_week.iloc[0]
saved = wf.share_of_reference.iloc[-1]
six = sets[sets.n_open == len(co.dcs)].iloc[0]
cheap = sets.iloc[0]
extra = six.total_usd_week / cheap.total_usd_week - 1
late = 1 - stock.safety_demand_only / stock.safety_stock
tok = dict(
    
    weekly=f"${k['weekly_cost']:,.0f}", annual=f"${k['annual_cost'] / 1e6:.1f}M", per_pallet=f"${k['cost_per_pallet']:.0f} a pallet", co2=f"{k['co2_tonnes_year']:,.0f} t",
    saved=f"{saved:.1%}", saved_week=f"${sq - k['weekly_cost']:,.0f}", runs_before=str(lots.weekly_runs_baseline), runs_after=str(lots.runs),
    ss=f"{stock.safety_stock:,}", ss_demand=f"{stock.safety_demand_only:,}", late=f"{late:.0%}", fill=f"{stock.fill_rate:.1%}", headroom=f"{h - 1:.0%}",
    near=f"{cheap.next_day_share:.0%}", near6=f"{six.next_day_share:.0%}", extra=f"{extra:.1%}",
    textbook=f"${ww_total:,.0f}", solver=f"${lots.total:,.0f}",
    demand=f"{sens.loc['Demand', 'swing_share_of_cost']:.0%}", demand1=f"{sens.loc['Demand', 'swing_share_of_cost']:.1%}", transport=f"{sens.loc['Transport rate per mile', 'swing_share_of_cost']:.1%}",
    dcfixed=f"{sens.loc['DC fixed cost', 'swing_share_of_cost']:.1%}", low=f"${cts.logistics_usd_per_pallet.min():.0f}", high=f"${cts.logistics_usd_per_pallet.max():.0f}")
late_df = pd.read_csv(os.path.join(ROOT, "output", "16_late_delivery_sensitivity.csv")).set_index("delivery_spread_multiplier")["share_from_late_deliveries"]
tok["late_half"], tok["late_double"] = f"{late_df.loc[0.5]:.0%}", f"{late_df.loc[2.0]:.0%}"
wanted = {
    "README.md": ["weekly", "saved", "runs_before", "runs_after", "late", "late_half", "late_double", "headroom", "extra"],
    "docs/PROJECT_STORY.md": ["weekly", "annual", "per_pallet", "saved", "saved_week", "runs_before", "runs_after", "ss", "ss_demand", "late", "late_half", "late_double", "fill", "headroom", "near", "near6", "extra", "demand", "transport", "dcfixed", "low", "high"],
    "docs/HOW_IT_WORKS.md": ["weekly", "annual", "per_pallet", "co2", "saved", "runs_before", "runs_after", "ss", "ss_demand", "late", "late_half", "late_double", "headroom", "near", "near6", "extra", "textbook", "solver", "low", "high"],
    "docs/INTERVIEW_QA.md": ["saved", "ss_demand", "late", "late_half", "late_double", "fill", "headroom", "near", "near6", "extra", "demand", "transport", "dcfixed"],
    "docs/AUDIT.md": ["late", "fill"],
    "docs/ONE_PAGE_SUMMARY.md": ["weekly", "annual", "per_pallet", "saved", "saved_week", "runs_before", "runs_after", "ss", "late", "late_half", "late_double", "near", "near6", "extra", "headroom"],
    "docs/DATA_AND_ASSUMPTIONS.md": ["demand1", "transport", "dcfixed", "late", "late_half", "late_double"],
    "docs/IDEA_LOG.md": ["saved", "late", "fill", "extra", "demand", "transport", "dcfixed"],
}
for doc, keys in wanted.items():
    text = read(*doc.split("/"))
    missing = [f"{key}={tok[key]}" for key in keys if tok[key] not in text]
    check(f"{doc} quotes the current numbers", not missing, "; ".join(missing))
rob = os.path.join(ROOT, "output", "14_robustness_checks.csv")
check("output/14_robustness_checks.csv exists (run `python -m tidewell.robustness` first)", os.path.exists(rob))
if os.path.exists(rob):
    rd = pd.read_csv(rob)
    n_rob = f"All {len(rd)} checks passed"
    check("robustness run: every check passed on every company", bool(rd.passed.all()), f"{int(rd.passed.sum())} of {len(rd)}")
    for doc in ("docs/PROJECT_STORY.md", "docs/INTERVIEW_QA.md"):
        check(f"{doc} quotes the robustness result", n_rob in read(*doc.split("/")), n_rob)
    check("docs/ROBUSTNESS.md quotes the robustness result", f"{int(rd.passed.sum())} of {len(rd)} checks passed" in read("docs", "ROBUSTNESS.md"))
stale = ("EUR", "status quo", "Status quo", "euro", "Lisbon", "Poznan", "Rotterdam", "605,328")
for doc in list(wanted) + ["docs/EXECUTIVE_SUMMARY.md"]:
    text = read(*doc.split("/"))
    found = [w for w in stale if w in text]
    check(f"{doc} has no stale wording", not found, ", ".join(found))
exec_text = read("docs", "EXECUTIVE_SUMMARY.md")
check("executive summary matches this run", tok["weekly"] in exec_text and tok["saved"] in exec_text and tok["ss"] in exec_text)

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
