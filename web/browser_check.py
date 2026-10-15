"""Browser check for the AI analyst, with Anthropic's API mocked (no key, no cost).

Proves the visitor's key goes only to api.anthropic.com and never to this site, tool results are real calculations,
answers render, errors are plain, and the tool loop is capped.   BASE=http://localhost:7860/ python web/browser_check.py
"""
import json, os, sys
from playwright.sync_api import sync_playwright
KEY = "sk-ant-api03-TESTKEY_abcdefghijklmnopqrstuvwxyz0123456789"
BASE = os.environ.get("BASE", "http://localhost:8000/")
fails = []
def check(n, ok, d=""):
    print(("PASS " if ok else "FAIL ") + n + (f"  ({d})" if d else "")); ok or fails.append(n)

ANSWER = ("You need about **484 units** of safety stock and should reorder at **1,284 units**.\n\n"
          "42% of that buffer exists only because deliveries run late, so supplier reliability is your cheapest lever.\n\n"
          "**What to do next**\n- Ask your supplier for on-time data: halving the lead-time spread cuts safety stock to 342 units.\n"
          "- Set the reorder point at 1,284 units in your system this week.\n- Review the 95% target: 99% would need 684 units.")

def run(mode):
    anth, local = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1366, "height": 900})
        state = {"n": 0}
        def anthropic(route):
            req = route.request
            body = json.loads(req.post_data)
            anth.append({"headers": req.headers, "body": body})
            state["n"] += 1
            if mode == "bad_key":
                return route.fulfill(status=401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
                                     headers={"access-control-allow-origin": "*"})
            if mode == "loop" and not body.get("tool_choice"):
                content = [{"type": "tool_use", "id": f"t{state['n']}_{i}", "name": "lot_sizing",
                            "input": {"demand_per_period": [5, 5], "setup_cost": 1, "holding_cost_per_unit_per_period": 1}} for i in range(3)]
                return route.fulfill(json={"stop_reason": "tool_use", "content": content}, headers={"access-control-allow-origin": "*"})
            if mode == "ok" and state["n"] == 1:
                return route.fulfill(json={"stop_reason": "tool_use", "content": [
                    {"type": "text", "text": "Let me calculate."},
                    {"type": "tool_use", "id": "tu1", "name": "safety_stock", "input": {"average_demand_per_period": 400,
                     "demand_std_dev_per_period": 120, "lead_time_periods": 2, "lead_time_std_dev_periods": 0.6}},
                    {"type": "tool_use", "id": "tu2", "name": "tidewell_scenario", "input": {"rate_per_pallet_mile": 0.15}}]},
                    headers={"access-control-allow-origin": "*"})
            return route.fulfill(json={"stop_reason": "end_turn", "content": [{"type": "text", "text": ANSWER}]}, headers={"access-control-allow-origin": "*"})
        pg.route("https://api.anthropic.com/**", anthropic)
        pg.on("request", lambda r: local.append(r) if r.url.startswith(BASE) else None)
        pg.goto(BASE); pg.wait_for_selector("#askOpen")
        pg.wait_for_timeout(1500)
        pg.click("#askOpen"); pg.wait_for_timeout(400)
        pg.fill("#apiKey", "not-a-key"); pg.click("#setup .go")
        if mode == "ok": check("rejects a malformed key before sending anything", pg.is_visible("#keyErr") and not anth)
        pg.fill("#apiKey", KEY); pg.click("#setup .go")
        check(f"[{mode}] chat opens after a key", pg.is_visible("#askForm"))
        q = "I sell about 400 units a week, give or take 120. Supplier takes 2 weeks, often late. How much safety stock?"
        pg.fill("#askInput", q); pg.press("#askInput", "Enter")
        pg.wait_for_selector(".msg.bot:not(.typing)", timeout=120000)
        pg.wait_for_timeout(300)
        text = pg.inner_text("#thread")
        allbodies = " ".join((r.post_data or "") + json.dumps(r.headers) for r in local)
        check(f"[{mode}] the key never reaches this site", KEY not in allbodies and "x-api-key" not in allbodies.lower())
        check(f"[{mode}] the key input is cleared from the page", pg.input_value("#apiKey") == "")
        if mode == "ok":
            h = anth[0]["headers"]
            check("calls Anthropic with the visitor's key and the browser-access header", h.get("x-api-key") == KEY and h.get("anthropic-dangerous-direct-browser-access") == "true")
            check("sends the system prompt with caching and the four tools", anth[0]["body"]["system"][0]["cache_control"] == {"type": "ephemeral"} and len(anth[0]["body"]["tools"]) == 4)
            second = anth[1]["body"]["messages"][-1]["content"]
            ss = json.loads(second[0]["content"])
            check("tool result sent back to Claude is the real calculation", second[0]["tool_use_id"] == "tu1" and abs(ss["safety_stock_units"] - 483.5) < 0.1, ss["safety_stock_units"])
            tw = json.loads(second[1]["content"])
            check("Tidewell tool result is real", tw["feasible"] and tw["weekly_cost_usd"] > 0, tw["weekly_cost_usd"])
            check("answer rendered with What to do next as a list", "What to do next" in text and pg.locator(".msg.bot ul li").count() == 3)
            check("receipts shown for both calculations", pg.locator(".receipt").count() == 2 and "484 units safety stock" in text, text[-300:])
            check("no contact pitch in the answer", "Akash" not in pg.inner_text(".msg.bot .body"))
            check("contact sits quietly in the footer", "Found this useful?" in pg.inner_text(".ask-foot"))
            pg.click(".receipt button"); pg.wait_for_timeout(2500)
            check("'Show this on the dashboard' moves the freight slider", pg.evaluate("state.rate_per_pallet_mile") == 0.15, pg.evaluate("state.rate_per_pallet_mile"))
            # follow-up keeps the conversation as plain text turns
            pg.fill("#askInput", "And at 99%?"); pg.press("#askInput", "Enter")
            pg.wait_for_function("document.querySelectorAll('.msg.bot:not(.typing)').length >= 2", timeout=60000)
            msgs = anth[-1]["body"]["messages"]
            check("follow-up sends earlier turns as text only", [m["role"] for m in msgs] == ["user", "assistant", "user"] and isinstance(msgs[1]["content"], str))
            pg.click("#forget"); check("Forget key returns to the key form", pg.is_visible("#apiKey") and not pg.is_visible("#askForm"))
            pg.set_viewport_size({"width": 390, "height": 844}); pg.click("#askOpen") if not pg.is_visible("#apiKey") else None
            pg.wait_for_timeout(300)
            sw = pg.evaluate("document.querySelector('#drawer').scrollWidth <= window.innerWidth + 1")
            check("drawer fits a phone screen", sw)
        if mode == "bad_key":
            check("a rejected key gets a plain message", "didn't accept that API key" in text)
        if mode == "loop":
            tool_calls = sum(1 for r in local if r.url.endswith("/api/advisor/tool"))
            check("loop: at most 10 calculations per question", tool_calls == 10, tool_calls)
            check("loop: ends with a forced text answer", anth[-1]["body"].get("tool_choice") == {"type": "none"} and len(anth) == 7, len(anth))
            check("loop: still shows an answer", "What to do next" in text)
        b.close()

for m in ("ok", "bad_key", "loop"):
    run(m)
print("FAILED:", fails if fails else "none"); sys.exit(1 if fails else 0)
