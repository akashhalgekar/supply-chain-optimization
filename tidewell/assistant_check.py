"""Checks for the Ask Tidewell assistant. No API key needed: a scripted stand-in plays Claude's part, so this runs in CI.

What it proves: the tool runs the real chain, every number handed to the model matches a direct chain.run, bad inputs are
refused instead of crashing, the tool loop is capped, visitors are rate limited, and the dashboard works with the
assistant switched off.   python -m tidewell.assistant_check
"""
import json, sys
from types import SimpleNamespace as NS
from . import store, chain, assistant

FAILED = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILED.append(name)


class FakeClaude:
    """Plays a scripted conversation. Each step is a function(messages) -> response."""

    def __init__(self, steps):
        self.steps, self.calls = list(steps), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        step = self.steps.pop(0) if self.steps else self.steps_default
        return step(kw["messages"])

    steps_default = None


def tool_use(args, id_="t1"):
    return lambda msgs: NS(stop_reason="tool_use", content=[NS(type="text", text="Running the model."),
                                                             NS(type="tool_use", id=id_, name="run_scenario", input=args)])


def last_results(msgs):
    return [b for b in msgs[-1]["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


def quote_result(msgs):
    res = last_results(msgs)[0]
    if res.get("is_error"):
        return NS(stop_reason="end_turn", content=[NS(type="text", text="ERROR SEEN: " + res["content"])])
    d = json.loads(res["content"])
    text = f"cost={d.get('weekly_cost_usd')} open={','.join(d.get('open_warehouses', []))} feasible={d['feasible']}"
    return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])


def main():
    co, _ = store.build()
    t = co.terms
    print("Ask Tidewell assistant checks")

    # 1. tool schema matches the dashboard limits
    a = assistant.Assistant(co, client=FakeClaude([]))
    props = a.tools[0]["input_schema"]["properties"]
    check("TOOL: every dial has a minimum and maximum", all("minimum" in props[k] and "maximum" in props[k] for k in assistant.DIALS))
    check("TOOL: warehouse and plant names come from the company", props["open_warehouses"]["items"]["enum"] == [co.city(c) for c in co.codes("dcs")]
          and props["plant_down"]["enum"] == [co.city(p) for p in co.codes("plants")])

    # 2. base plan: the number the model sees equals a direct run
    direct = chain.run(co, t)
    fake = FakeClaude([tool_use({}), quote_result])
    out = assistant.Assistant(co, client=fake).ask("What is the base plan?")
    check("BASE: answer quotes the real weekly cost", f"cost={round(direct.kpi['weekly_cost'])}" in out["answer"], out["answer"][:60])
    check("BASE: system prompt is sent with caching", fake.calls[0]["system"][0].get("cache_control") == {"type": "ephemeral"})
    check("BASE: receipt records the scenario", len(out["scenarios"]) == 1 and out["scenarios"][0]["dials"] == {})

    # 3. freight doubles: same as running the chain by hand
    direct = chain.run(co, t.with_(rate_per_pallet_mile=0.2))
    fake = FakeClaude([tool_use({"rate_per_pallet_mile": 0.2}), quote_result])
    out = assistant.Assistant(co, client=fake).ask("What if freight doubles?")
    sent = json.loads(last_results(fake.calls[1]["messages"])[0]["content"])
    check("WHAT-IF: freight x2 cost matches a direct run", sent["weekly_cost_usd"] == round(direct.kpi["weekly_cost"]), f"${sent['weekly_cost_usd']:,}")
    check("WHAT-IF: freight x2 keeps Chicago open, as the stress test says", "Chicago" in sent["open_warehouses"])
    check("WHAT-IF: change against base is included", sent["change_vs_base_plan"]["weekly_cost_usd"] > 0)

    # 4. forcing all six warehouses reproduces the DC set comparison
    direct = chain.run(co, t, dc_set=co.codes("dcs"))
    fake = FakeClaude([tool_use({"open_warehouses": [co.city(c) for c in co.codes("dcs")]}), quote_result])
    assistant.Assistant(co, client=fake).ask("What if we keep all six?")
    sent = json.loads(last_results(fake.calls[1]["messages"])[0]["content"])
    check("WAREHOUSES: keep-all-six cost matches a direct run", sent["weekly_cost_usd"] == round(direct.kpi["weekly_cost"]), f"${sent['weekly_cost_usd']:,}")

    # 5. a plant outage that breaks the network is reported, not hidden
    fake = FakeClaude([tool_use({"plant_down": "Columbus"}), quote_result])
    out = assistant.Assistant(co, client=fake).ask("What if Columbus goes down?")
    check("OUTAGE: losing Columbus is reported as infeasible", out["scenarios"][0]["feasible"] is False and "feasible=False" in out["answer"])

    # 6. bad inputs are refused with a message the model can read
    for bad in ({"service_level": 1.0}, {"demand_scale": -1}, {"open_warehouses": ["Miami"]}, {"made_up": 3}):
        fake = FakeClaude([tool_use(bad), quote_result])
        out = assistant.Assistant(co, client=fake).ask("Try this")
        res = last_results(fake.calls[1]["messages"])[0]
        check(f"INPUTS: refuses {json.dumps(bad)}", res.get("is_error") is True and out["answer"].startswith("ERROR SEEN"))

    # 7. the tool loop cannot run forever
    fake = FakeClaude([])
    fake.steps_default = tool_use({})
    out = assistant.Assistant(co, client=fake).ask("Loop forever")
    check("LOOP: stops after the round limit", len(fake.calls) == assistant.MAX_TOOL_ROUNDS + 1, f"{len(fake.calls)} calls")
    check("LOOP: still returns a readable answer", bool(out["answer"]))

    # 8. an API failure becomes a plain message
    def boom(msgs):
        raise RuntimeError("network down")
    try:
        assistant.Assistant(co, client=FakeClaude([boom])).ask("Hello")
        check("ERRORS: API failure raises a visitor-safe error", False)
    except assistant.AssistantError as e:
        check("ERRORS: API failure raises a visitor-safe error", "try again" in str(e))

    # 9. rate limits
    now = [0.0]
    lim = assistant.Limiter(per_hour=3, per_day=5, clock=lambda: now[0])
    first = [lim.allow("a")[0] for _ in range(4)]
    check("LIMITS: a visitor is stopped after the hourly limit", first == [True, True, True, False])
    now[0] = 3601
    check("LIMITS: the hourly limit resets", lim.allow("a")[0])
    check("LIMITS: the site-wide daily cap holds", lim.allow("b")[0] and not lim.allow("c")[0])

    # 10. the web API, switched off and switched on
    from fastapi.testclient import TestClient
    from . import api
    client = TestClient(api.app)
    api.ASSISTANT = None
    check("API: status says off without a key", client.get("/api/ask/status").json() == {"enabled": False})
    check("API: asking while off returns a clear 503", client.post("/api/ask", json={"question": "hi"}).status_code == 503)
    check("API: an overlong question is rejected", client.post("/api/ask", json={"question": "x" * 501}).status_code == 422)
    api.ASSISTANT = assistant.Assistant(api.CO, client=FakeClaude([tool_use({}), quote_result]))
    api.LIMITER = assistant.Limiter(per_hour=1, per_day=10)
    r = client.post("/api/ask", json={"question": "Base plan?", "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]})
    check("API: a question gets an answer and receipts", r.status_code == 200 and r.json()["scenarios"], str(r.status_code))
    check("API: the second question in the hour is limited", client.post("/api/ask", json={"question": "Again"}).status_code == 429)
    check("API: the dashboard still runs", client.post("/api/run", json={}).json().get("feasible") is True)

    print(f"\n{'ALL ASSISTANT CHECKS PASSED' if not FAILED else f'{len(FAILED)} ASSISTANT CHECKS FAILED'}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
