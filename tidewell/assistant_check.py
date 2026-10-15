"""Checks for the AI analyst's tools, the website endpoints and the MCP server. No API key needed, so this runs in CI.

What it proves: each calculator gives the textbook answer (by hand or by brute force), the Tidewell tool returns exactly
what a direct chain.run gives, bad input is refused with a readable message instead of a crash, the server never holds
or reads an Anthropic key, and the MCP server serves the same tools with the same numbers.
    python -m tidewell.assistant_check
"""
import json, os, sys
from itertools import product
from math import sqrt
import numpy as np
import pandas as pd
from scipy.stats import norm
from . import store, chain, assistant, calculators

FAILED = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(name)


def refuses(fn, args):
    try:
        fn(args)
        return False
    except ValueError as e:
        return bool(str(e))


def main():
    co, _ = store.build()
    t = co.terms
    box = assistant.Toolbox(co)
    print("AI analyst checks")

    # 1. safety stock: textbook formula by hand
    d, sd, lt, sdlt = 400, 120, 2, 0.6
    out = calculators.safety_stock({"average_demand_per_period": d, "demand_std_dev_per_period": sd, "lead_time_periods": lt,
                                    "lead_time_std_dev_periods": sdlt, "unit_cost": 30, "holding_rate_per_year": 0.22})
    z = norm.ppf(0.95)
    hand = z * sqrt(lt * sd ** 2 + d ** 2 * sdlt ** 2)
    check("SAFETY STOCK: matches z x sqrt(LT sd^2 + D^2 sdLT^2) by hand", abs(out["safety_stock_units"] - hand) < 0.06, f"{out['safety_stock_units']} vs {hand:.1f}")
    check("SAFETY STOCK: reorder point = D x LT + SS", abs(out["reorder_point_units"] - (d * lt + hand)) < 0.06)
    check("SAFETY STOCK: lead-time share = 1 - demand-only / total", abs(out["share_of_safety_stock_caused_by_lead_time_variability"] - (1 - z * sd * sqrt(lt) / hand)) < 1e-3)
    check("SAFETY STOCK: 99% needs more than 95%, 90% less", out["safety_stock_at_other_service_levels"]["99%"] > out["safety_stock_units"] > out["safety_stock_at_other_service_levels"]["90%"])
    check("SAFETY STOCK: prices the stock (units x cost x rate)", abs(out["safety_stock_holding_cost_per_year"] - round(hand * 30 * 0.22)) <= 1)
    check("SAFETY STOCK: fill rate sits above the cycle service level", out["fill_rate"] > 0.95)
    flat = calculators.safety_stock({"average_demand_per_period": 100, "demand_std_dev_per_period": 30, "lead_time_periods": 1})
    check("SAFETY STOCK: no lead-time spread means no lead-time share", flat["share_of_safety_stock_caused_by_lead_time_variability"] == 0.0)
    for bad in ({}, {"average_demand_per_period": -1, "demand_std_dev_per_period": 1, "lead_time_periods": 1},
                {"average_demand_per_period": 10, "demand_std_dev_per_period": 1, "lead_time_periods": 1, "service_level": 1.0},
                {"average_demand_per_period": "lots", "demand_std_dev_per_period": 1, "lead_time_periods": 1},
                {"average_demand_per_period": 10, "demand_std_dev_per_period": 1, "lead_time_periods": 1, "colour": "red"},
                {"average_demand_per_period": 10, "demand_std_dev_per_period": 1, "lead_time_periods": 1, "period": "year"},
                {"average_demand_per_period": True, "demand_std_dev_per_period": 1, "lead_time_periods": 1}, []):
        check(f"SAFETY STOCK: refuses {json.dumps(bad)[:70]}", refuses(calculators.safety_stock, bad))

    # 2. lot sizing: Wagner-Whitin equals brute force over every run pattern
    dem = [100, 0, 250, 300, 80, 120, 400, 90]
    s, h = 500, 1.2
    out = calculators.lot_sizing({"demand_per_period": dem, "setup_cost": s, "holding_cost_per_unit_per_period": h})
    best = float("inf")
    for runs in product([0, 1], repeat=len(dem) - 1):
        cost, made_in = 0.0, 0                          # each period's demand is made in the latest run at or before it
        for i, r in enumerate((1,) + runs):
            if r:
                cost += s
                made_in = i
            cost += h * dem[i] * (i - made_in)
        best = min(best, cost)
    check("LOT SIZING: Wagner-Whitin equals brute force over all 128 plans", abs(out["total_cost"] - best) < 1, f"${out['total_cost']:,.0f} vs ${best:,.0f}")
    check("LOT SIZING: plan meets every period's demand", all(p["ending_stock"] >= -1e-6 for p in out["plan"]) and abs(sum(p["produce"] for p in out["plan"]) - sum(dem)) < 1e-6)
    check("LOT SIZING: beats or equals lot-for-lot", out["total_cost"] <= out["lot_for_lot"]["total_cost"])
    check("LOT SIZING: EOQ = sqrt(2DS/h)", abs(out["eoq_units"] - sqrt(2 * np.mean(dem) * s / h)) < 0.06)
    capped = calculators.lot_sizing({"demand_per_period": dem, "setup_cost": s, "holding_cost_per_unit_per_period": h, "max_periods_per_batch": 1})
    check("LOT SIZING: a one-period batch cap forces lot-for-lot", capped["runs"] == sum(1 for x in dem if x > 0))
    for bad in ({"demand_per_period": [5], "setup_cost": 1, "holding_cost_per_unit_per_period": 1},
                {"demand_per_period": [5, -1], "setup_cost": 1, "holding_cost_per_unit_per_period": 1},
                {"demand_per_period": [5, 5], "setup_cost": 1, "holding_cost_per_unit_per_period": 0},
                {"demand_per_period": "5,5", "setup_cost": 1, "holding_cost_per_unit_per_period": 1},
                {"demand_per_period": [1] * 105, "setup_cost": 1, "holding_cost_per_unit_per_period": 1}):
        check(f"LOT SIZING: refuses {json.dumps(bad)[:70]}", refuses(calculators.lot_sizing, bad))

    # 3. network design: the MIP picks the same set as brute force over every subset
    W = {"A": 900, "B": 1200, "C": 700, "D": 1500}
    cap = {"A": 500, "B": None, "C": 300, "D": None}
    rng = np.random.default_rng(7)
    C = {f"c{i}": float(rng.integers(40, 160)) for i in range(9)}
    cost = {(w, c): float(rng.uniform(0.5, 6.0)) for w in W for c in C}
    lanes = [{"warehouse": w, "customer": c, "cost_per_unit": v} for (w, c), v in cost.items()]
    args = {"warehouses": [{"name": w, "fixed_cost_per_period": f, **({"capacity_per_period": cap[w]} if cap[w] else {})} for w, f in W.items()],
            "customers": [{"name": c, "demand_per_period": q} for c, q in C.items()], "lanes": lanes}
    out = calculators.network_design(args)
    bf = calculators.brute_force_network(list(W), list(C), cost, W, cap, C)
    check("NETWORK: MIP cost equals brute force over all 15 warehouse sets", abs(out["total_cost_per_period"] - bf["total"]) < 1, f"{out['open_warehouses']} vs {bf['open']}")
    served = {c: sum(a["units"] for a in out["assignments"][c]) for c in C}
    check("NETWORK: every customer's demand is met", all(abs(served[c] - C[c]) < 0.2 for c in C))
    check("NETWORK: capacity respected", all(v["units"] <= cap[w] + 1e-6 for w, v in out["warehouse_load"].items() if cap[w]))
    check("NETWORK: reports what each decision is worth", len(out["cost_of_changing_one_decision"]) == len(W)
          and all(v == "infeasible" or v["change_vs_best"] >= -1 for v in out["cost_of_changing_one_decision"].values()))
    forced = calculators.network_design({**args, "must_close": out["open_warehouses"][:1]})
    check("NETWORK: must_close is obeyed", out["open_warehouses"][0] not in forced.get("open_warehouses", []))
    tiny = calculators.network_design({**args, "warehouses": [{"name": "A", "fixed_cost_per_period": 1, "capacity_per_period": 10}],
                                       "lanes": [ln for ln in lanes if ln["warehouse"] == "A"]})
    check("NETWORK: too little capacity is reported as infeasible", tiny["feasible"] is False)
    geo = calculators.network_design({"warehouses": [{"name": "Reno", "fixed_cost_per_period": 20000, "lat": 39.53, "lon": -119.81},
                                                     {"name": "Columbus", "fixed_cost_per_period": 22000, "lat": 39.96, "lon": -83.0}],
                                      "customers": [{"name": "Los Angeles", "demand_per_period": 3000, "lat": 34.05, "lon": -118.24},
                                                    {"name": "New York", "demand_per_period": 4000, "lat": 40.71, "lon": -74.0}],
                                      "cost_per_unit_mile": 0.01, "max_miles": 800})
    check("NETWORK: lat/lon mode with a mileage limit opens both coasts", sorted(geo["open_warehouses"]) == ["Columbus", "Reno"],
          f"{geo.get('average_miles_per_unit')} mi a unit")
    check("NETWORK: road miles use the Tidewell 1.15 road factor", abs(calculators._road_miles((34.05, -118.24), (40.71, -74.0)) / 1.15 - 2445) < 15)
    for bad in ({"warehouses": [], "customers": [{"name": "x", "demand_per_period": 1}]},
                {**args, "lanes": [{"warehouse": "Z", "customer": "c0", "cost_per_unit": 1}]},
                {**args, "lanes": None},
                {**args, "must_open": ["A"], "must_close": ["A"]},
                {"warehouses": [{"name": "A", "fixed_cost_per_period": 1}, {"name": "A", "fixed_cost_per_period": 2}],
                 "customers": [{"name": "x", "demand_per_period": 1}], "lanes": [{"warehouse": "A", "customer": "x", "cost_per_unit": 1}]},
                {**args, "max_miles": 100}):
        check(f"NETWORK: refuses {json.dumps(bad)[:70]}", refuses(calculators.network_design, bad))

    # 4. Tidewell tool: numbers equal a direct run
    cheap = chain.run(co, t)
    out, receipt = box.call("tidewell_scenario", {})
    check("TIDEWELL: base plan cost matches a direct run", out["weekly_cost_usd"] == round(cheap.kpi["weekly_cost"]), f"${out['weekly_cost_usd']:,}")
    direct = chain.run(co, t.with_(rate_per_pallet_mile=0.2))
    out, _ = box.call("tidewell_scenario", {"rate_per_pallet_mile": 0.2})
    check("TIDEWELL: freight x2 matches a direct run and keeps Chicago", out["weekly_cost_usd"] == round(direct.kpi["weekly_cost"]) and "Chicago" in out["open_warehouses"])
    six = chain.run(co, t, dc_set=co.codes("dcs"))
    out, _ = box.call("tidewell_scenario", {"open_warehouses": [co.city(c) for c in co.codes("dcs")]})
    check("TIDEWELL: keep-all-six matches a direct run", out["weekly_cost_usd"] == round(six.kpi["weekly_cost"]))
    out, receipt = box.call("tidewell_scenario", {"plant_down": "Columbus"})
    check("TIDEWELL: losing Columbus is reported as infeasible", out["feasible"] is False and receipt["feasible"] is False)
    for bad in ({"service_level": 1.0}, {"demand_scale": -1}, {"open_warehouses": ["Miami"]}, {"made_up": 3},
                {"demand_scale": None}, {"plant_down": ["Dallas"]}, {"open_warehouses": 5}, {"demand_scale": True}):
        check(f"TIDEWELL: refuses {json.dumps(bad)}", refuses(lambda a: box.call("tidewell_scenario", a), bad))
    check("TOOLS: an unknown tool is refused", refuses(lambda a: box.call("delete_everything", a), {}))

    # 5. tool definitions follow one pattern and match the calculators
    props = {tl["name"]: tl for tl in box.tools}
    check("TOOLS: four tools", sorted(props) == ["lot_sizing", "network_design", "safety_stock", "tidewell_scenario"])
    check("TOOLS: every description has context, inputs, outputs, how to read, typical uses",
          all(all(k in tl["description"] for k in ("CONTEXT:", "INPUTS:", "OUTPUTS:", "HOW TO READ:", "TYPICAL USES:")) for tl in box.tools))
    tp = props["tidewell_scenario"]["input_schema"]["properties"]
    check("TOOLS: every Tidewell dial has a minimum and maximum", all("minimum" in tp[k] and "maximum" in tp[k] for k in assistant.DIALS))
    check("TOOLS: schemas name exactly the inputs each calculator accepts",
          set(props["safety_stock"]["input_schema"]["properties"]) == set(calculators.SAFETY_STOCK_INPUTS)
          and set(props["lot_sizing"]["input_schema"]["properties"]) == set(calculators.LOT_SIZING_INPUTS)
          and set(props["network_design"]["input_schema"]["properties"]) == set(calculators.NETWORK_INPUTS))

    # 6. the system prompt: facts match this run, answers end with actions, no pushy contact line
    facts = {"keep-six extra cost": f"{six.kpi['weekly_cost'] / cheap.kpi['weekly_cost'] - 1:.1%}",
             "next-day, cheapest": f"{cheap.kpi['next_day_share']:.0%}", "next-day, all six": f"{six.kpi['next_day_share']:.0%}"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    late = os.path.join(root, "output", "16_late_delivery_sensitivity.csv")
    if os.path.exists(late):
        ld = pd.read_csv(late).set_index("delivery_spread_multiplier")["share_from_late_deliveries"]
        facts["late share at half spread"], facts["late share at double"] = f"{ld.loc[0.5]:.0%}", f"{ld.loc[2.0]:.0%}"
    rob = os.path.join(root, "output", "14_robustness_checks.csv")
    if os.path.exists(rob):
        rd = pd.read_csv(rob)
        facts["robustness"] = f"{int(rd.passed.sum())} of {len(rd)}"
    stale = [f"{k}={v}" for k, v in facts.items() if v not in assistant.SYSTEM]
    check("PROMPT: Tidewell facts match this run", not stale, "; ".join(stale) or f"{len(facts)} facts")
    check("PROMPT: every answer ends with What to do next", "End every answer with a short section headed **What to do next**" in assistant.SYSTEM)
    check("PROMPT: Akash is mentioned only when asked", "Do not promote anyone. Mention Akash only if" in assistant.SYSTEM)

    # 7. the web API: no key anywhere, tools run, bad calls are contained, limits hold
    from fastapi.testclient import TestClient
    from . import api
    client = TestClient(api.app)
    cfg = client.get("/api/advisor").json()
    check("API: config has prompt, four tools, models and limits", cfg["system"] == assistant.SYSTEM and len(cfg["tools"]) == 4
          and cfg["models"] and cfg["limits"]["max_tool_calls"] > 0)
    src = "".join(open(os.path.join(root, "tidewell", f)).read() for f in ("api.py", "assistant.py", "calculators.py", "mcp_server.py"))
    check("API: the server never reads an Anthropic key or imports the SDK", "ANTHROPIC_API_KEY" not in src and "import anthropic" not in src)
    r = client.post("/api/advisor/tool", json={"name": "safety_stock", "input": {"average_demand_per_period": 400, "demand_std_dev_per_period": 120, "lead_time_periods": 2}})
    check("API: a tool call returns the result and a receipt", r.status_code == 200 and not r.json()["is_error"]
          and json.loads(r.json()["content"])["safety_stock_units"] > 0 and r.json()["receipt"]["tool"] == "safety_stock")
    r = client.post("/api/advisor/tool", json={"name": "safety_stock", "input": {"average_demand_per_period": -5}})
    check("API: bad tool input comes back as a readable tool error", r.status_code == 200 and r.json()["is_error"] and "at least" in r.json()["content"])
    r = client.post("/api/advisor/tool", json={"name": "tidewell_scenario", "input": {}})
    check("API: the Tidewell tool runs over HTTP", json.loads(r.json()["content"])["weekly_cost_usd"] == round(cheap.kpi["weekly_cost"]))
    check("API: a non-object input is rejected", client.post("/api/advisor/tool", json={"name": "lot_sizing", "input": [1, 2]}).status_code == 422)
    real = calculators.lot_sizing
    def broken(a):
        raise RuntimeError("solver crashed")
    calculators.lot_sizing = broken
    try:
        r = client.post("/api/advisor/tool", json={"name": "lot_sizing", "input": {}})
        check("API: a crash inside a tool becomes a tool error, not a 500", r.status_code == 200 and r.json()["is_error"])
    finally:
        calculators.lot_sizing = real
    api.LIMITER = assistant.Limiter(per_hour=2, site_per_hour=100)
    codes = [client.post("/api/advisor/tool", json={"name": "lot_sizing", "input": {}}).status_code for _ in range(3)]
    check("API: a visitor is limited after the hourly cap", codes == [200, 200, 429], str(codes))
    api.LIMITER = assistant.Limiter()
    check("API: the dashboard still runs", client.post("/api/run", json={}).json().get("feasible") is True)
    now = [0.0]
    lim = assistant.Limiter(per_hour=5, site_per_hour=3, clock=lambda: now[0])
    got = [lim.allow(f"v{i}")[0] for i in range(4)]
    now[0] = 3601
    check("LIMITS: the site-wide cap stops many 'different' visitors, then resets", got == [True, True, True, False] and lim.allow("v9")[0])

    # 8. the MCP server serves the same tools with the same numbers
    try:
        import anyio
        from mcp.client import Client
        from . import mcp_server
        server, _ = mcp_server.build(co)

        async def talk():
            async with Client(server) as c:
                return (await c.list_tools(), await c.call_tool("tidewell_scenario", {}),
                        await c.call_tool("lot_sizing", {"demand_per_period": [1]}), await c.get_prompt("supply_chain_analyst"))
        tools, ok, bad, prompt = anyio.run(talk)
        check("MCP: lists the same four tools with the same schemas and descriptions",
              [x.name for x in tools.tools] == [x["name"] for x in box.tools]
              and all(x.input_schema == y["input_schema"] and x.description == y["description"] for x, y in zip(tools.tools, box.tools)))
        check("MCP: Tidewell numbers match the website", not ok.is_error and json.loads(ok.content[0].text)["weekly_cost_usd"] == round(cheap.kpi["weekly_cost"]))
        check("MCP: bad input is a tool error, not a crash", bad.is_error and "list" in bad.content[0].text)
        check("MCP: offers the analyst prompt", prompt.messages[0].content.text == assistant.SYSTEM)
    except ImportError as e:
        check("MCP: the mcp package is installed", False, str(e))

    print(f"\n{'ALL ANALYST CHECKS PASSED' if not FAILED else f'{len(FAILED)} ANALYST CHECKS FAILED'}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
