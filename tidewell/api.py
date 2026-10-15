"""Small web API and dashboard.   uvicorn tidewell.api:app --port 8000   then open http://localhost:8000"""
import base64, io, os
from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from . import store, chain, plots, flow, assistant

app = FastAPI(title="Tidewell supply chain optimiser", version="1.0")
CO, TABLES = store.build()
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
_cache = {}
TOOLBOX = assistant.Toolbox(CO)       # the AI analyst's tools; Claude itself runs in the visitor's browser on their own key
LIMITER = assistant.Limiter()


def _default(name, **bounds):
    """Dial defaults come from the company's own terms, so the dashboard opens on the same numbers as the documents.
    Bounds reject impossible inputs (a 100% service level, negative demand) with a clear 422 instead of a crash."""
    return Field(default_factory=lambda: getattr(CO.terms, name), **bounds)


class Dials(BaseModel):
    demand_scale: float = _default("demand_scale", gt=0, le=5)
    service_level: float = _default("service_level", ge=0.5, lt=1)
    rate_per_pallet_mile: float = _default("rate_per_pallet_mile", gt=0, le=5)
    dc_fixed_scale: float = _default("dc_fixed_scale", ge=0, le=10)
    setup_cost: float = _default("setup_cost", ge=0, le=1_000_000)
    lead_time_scale: float = _default("lead_time_scale", gt=0, le=10)


def _png(draw):
    buf = io.BytesIO()
    draw(buf)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@app.get("/")
def home():
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/api/defaults")
def defaults():
    return Dials().model_dump()


@app.post("/api/run")
def run(d: Dials):
    key = tuple(d.model_dump().values())
    if key in _cache:
        return _cache[key]
    r = chain.run(CO, CO.terms.with_(**d.model_dump()))
    if not r.kpi["feasible"]:
        out = {"feasible": False, "message": "These settings need more plant or DC capacity than the company has in its peak week."}
    else:
        k, net, city = r.kpi, r.net, CO.city
        cap = CO.plants.set_index("code").capacity
        busiest = (r.lots.weekly.groupby(["plant", "week"]).produce.sum().groupby("plant").max() / cap).to_dict()
        out = {
            "feasible": True,
            "kpi": {x: (round(float(v), 6) if not isinstance(v, (list, bool)) else v) for x, v in k.items() if x != "open_dcs"},
            "open_dcs": [city(c) for c in k["open_dcs"]], "closed_dcs": [city(c) for c in CO.codes("dcs") if c not in k["open_dcs"]],
            "cost_breakdown": [{"label": "Production", "value": round(net.cost["production"])},
                               {"label": "Transport", "value": round(net.cost["inbound"] + net.cost["outbound"])},
                               {"label": "DC fixed + handling", "value": round(net.cost["dc_fixed"] + net.cost["handling"])},
                               {"label": "Production planning", "value": round(k["planning_cost"])},
                               {"label": "DC stock holding", "value": round(k["stock_cost"])}],
            "plants": [{"plant": city(p), "average_week_load": round(v, 3), "peak_week_load": round(v * CO.peak, 3),
                        "busiest_production_week": round(float(busiest.get(p, 0.0)), 3)} for p, v in net.plant_load.items()],
            "planning_limit": CO.terms.max_utilisation,
            "production": {"runs": r.lots.runs, "runs_if_weekly": r.lots.weekly_runs_baseline, "saved_vs_weekly": round(r.lots.saved)},
            "stock": {"safety_stock": r.stock.safety_stock, "if_demand_only": r.stock.safety_demand_only, "fill_rate": round(r.stock.fill_rate, 6),
                      "by_dc": [{"dc": city(dc), "pallets": round(v)} for dc, v in r.stock.detail.groupby("dc").safety_stock.sum().items()]},
            "map": _png(lambda b: plots.network_map(CO, net, b)),
        }
    _cache[key] = out
    return out


@app.get("/api/lineage")
def lineage():
    if "lineage" not in _cache:
        base = chain.run(CO, CO.terms)
        _cache["lineage"] = {"flowchart": _png(lambda b: flow.draw(flow.facts_from(CO, TABLES, base), b)),
                             "quality_log": TABLES["data_quality_log"][["source", "step", "rows_affected", "note"]].to_dict(orient="records")}
    return _cache["lineage"]


class ToolCall(BaseModel):
    name: str = Field(max_length=64)
    input: Dict[str, Any] = Field(default_factory=dict)


@app.get("/api/advisor")
def advisor():
    """What the browser needs to talk to Claude: the system prompt, the tools, model choices and limits.
    No key lives here. The visitor's browser sends their own key straight to Anthropic."""
    return {"system": assistant.SYSTEM, "tools": TOOLBOX.tools, "models": [{"id": m, "label": l} for m, l in assistant.MODELS],
            "limits": assistant.LIMITS, "contact": assistant.CONTACT}


@app.post("/api/advisor/tool")
def advisor_tool(call: ToolCall, request: Request):
    """Run one tool call that Claude asked for. Pure computation: no API key, no tokens, nothing stored."""
    # The first X-Forwarded-For entry is the visitor as the host's proxy reports it. A visitor can fake it, so the
    # site-wide hourly cap is what actually bounds the CPU.
    forwarded = request.headers.get("x-forwarded-for", "")
    who = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    ok, message = LIMITER.allow(who)
    if not ok:
        return JSONResponse(status_code=429, content={"error": message})
    try:
        out, receipt = TOOLBOX.call(call.name, call.input)
        return {"content": assistant.as_text(out), "is_error": False, "receipt": receipt}
    except ValueError as e:
        return {"content": str(e), "is_error": True, "receipt": None}
    except Exception:                                        # solver or data failure: tell the model, keep the server up
        return {"content": "The calculation could not run with these inputs. Try different settings.", "is_error": True, "receipt": None}
