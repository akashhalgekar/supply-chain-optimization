"""The end-to-end flowchart: source systems -> ETL -> warehouse -> three models -> decisions.

Numbers on the chart are not typed in. They come from the pipeline run (facts), so the
picture always matches what the code just did.
"""
import textwrap
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

NAVY, RED, GREY, INK = "#002060", "#c00000", "#9aa3b0", "#14213d"
SRC, ETL, WH, MOD, OUT = "#e8eef9", "#fff1d6", "#e6f4ea", "#eadcf8", "#fde2e2"
EDGE = "#c3ccda"


LINE = 2.15


def _box(ax, cx, cy, w, fill, title, lines=(), tcolor=NAVY, fs=11.5, lfs=9.6, h=None):
    """Box centred on (cx, cy); height grows with the text. Returns (left, right, top, bottom)."""
    h = h or (4.6 + LINE * len(lines))
    x, y = cx - w / 2, cy - h / 2
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.1", fc=fill, ec=EDGE, lw=1.4, zorder=2))
    ax.text(cx, y + h - 1.3, title, ha="center", va="top", fontsize=fs, weight="bold", color=tcolor, zorder=3)
    ly = y + h - 4.2
    for ln in lines:
        ax.text(cx, ly, ln, ha="center", va="top", fontsize=lfs, color=INK, zorder=3)
        ly -= LINE
    return x, x + w, y + h, y


def _arrow(ax, a, b, color=NAVY, lw=2.0, style="-|>", rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=18, color=color, lw=lw, zorder=1,
                                 connectionstyle=f"arc3,rad={rad}"))


def _header(ax, cx, n, text):
    ax.text(cx, 98, f"{n}  {text}", ha="center", va="center", fontsize=13, weight="bold", color="white", zorder=4,
            bbox=dict(boxstyle="round,pad=0.45", fc=NAVY, ec="none"))


def _merge(ax, starts, xbus, end, color=NAVY, lw=1.9):
    """Several boxes feeding one: lines from each start (x, y) to a vertical bus, then one arrow to end (x, y)."""
    for x, y in starts:
        ax.plot([x, xbus], [y, y], color=color, lw=lw, zorder=1, solid_capstyle="round")
    ys = [y for _, y in starts] + [end[1]]
    ax.plot([xbus, xbus], [min(ys), max(ys)], color=color, lw=lw, zorder=1)
    _arrow(ax, (xbus, end[1]), end, color=color, lw=lw)


def _split(ax, start, xbus, ends, color=NAVY, lw=1.9):
    """One box feeding several: one line to a vertical bus, then an arrow to each end (x, y)."""
    ax.plot([start[0], xbus], [start[1], start[1]], color=color, lw=lw, zorder=1, solid_capstyle="round")
    ys = [y for _, y in ends] + [start[1]]
    ax.plot([xbus, xbus], [min(ys), max(ys)], color=color, lw=lw, zorder=1)
    for x, y in ends:
        _arrow(ax, (xbus, y), (x, y), color=color, lw=lw)


def draw(facts, path):
    f = facts
    fig, ax = plt.subplots(figsize=(22, 12), dpi=110)
    ax.set_xlim(0, 160); ax.set_ylim(0, 108); ax.axis("off")
    ax.text(80, 107.5, "Tidewell: from company systems to supply chain decisions", ha="center", va="top",
            fontsize=21, weight="bold", color=NAVY)
    C1, C2, C3, C4, C5 = 14.5, 49, 82, 118, 150.5
    W1, W2, W3, W4, W5 = 27, 27, 26, 34, 18
    R3 = (80, 54, 28)                        # row centres for 3-box columns
    R4 = (84, 63, 41, 19)                    # row centres for the 4 ETL steps

    # 1 source systems
    _header(ax, C1, "1", "Company systems")
    src = [("ERP", ["what we sell and make", f"{f['orders_in']:,} sales order lines", "item master (units per pallet)", "plant capacity and cost", "setup and holding cost"]),
           ("WMS (warehouse system)", ["what each warehouse can handle", "DC throughput per day", "handling and fixed cost", f"{f['receipts']:,} goods receipts (lead times)"]),
           ("TMS (transport system)", ["what it costs to move a pallet", f"{f['lanes']} lanes with distances", "carrier rate per pallet-mile", "CO2 factor per pallet-mile"])]
    for (t, ls), y in zip(src, R3):
        _box(ax, C1, y, W1, SRC, t, ls)
    ax.text(C1, 8, "raw files: mixed units, spellings and\ndate formats, duplicates, cancelled orders", ha="center", va="top", fontsize=9.6, color=RED, style="italic")

    # 2 ETL
    _header(ax, C2, "2", "ETL: clean the data")
    etl = [("Extract", ["read each raw file", "exactly as delivered"]),
           ("Clean", [f"drop {f['dups']:,} duplicate lines", f"drop {f['cancelled']:,} cancelled lines", f"quarantine {f['broken']} broken lines", "one spelling per city, one date format"]),
           ("Transform", ["units -> pallets", "km -> miles, per day -> per week", f"{f['clean_lines']:,} lines -> weekly demand", f"-> {f['profiles']} demand profiles (mean, spread)"]),
           ("Load", ["write clean tables to the store", "plus a data quality log"])]
    edges = [_box(ax, C2, y, W2, ETL, t, ls) for (t, ls), y in zip(etl, R4)]
    for a, b in zip(edges, edges[1:]):
        _arrow(ax, (C2, a[3] - 0.6), (C2, b[2] + 0.6), color=GREY, lw=1.8)
    _merge(ax, [(C1 + W1 / 2 + 0.6, y) for y in R3], (C1 + W1 / 2 + C2 - W2 / 2) / 2, (C2 - W2 / 2 - 1.2, R4[0]))

    # 3 clean data store
    _header(ax, C3, "3", "Clean data store")
    wh = [("Facts (measurements)", ["weekly demand per market x item", "demand mean and spread", f"observed lead time ({f['lead_days']:.1f} days)"]),
          ("Descriptions", ["products and units per pallet", "plants and capacity", "DCs: capacity and costs", "markets, distances in miles"]),
          ("Cost parameters", [f"setup ${f['setup']:,.0f} per run", f"holding {f['hold']:.0%} of value a year", f"transport ${f['rate']:.3f} per pallet-mile"])]
    for (t, ls), y in zip(wh, R3):
        _box(ax, C3, y, W3, WH, t, ls, lfs=9.2)
    _split(ax, (C2 + W2 / 2 + 0.6, R4[3]), (C2 + W2 / 2 + C3 - W3 / 2) / 2, [(C3 - W3 / 2 - 1.2, y) for y in R3])

    # 4 models (Model 1 in the middle: it feeds both of the others)
    _header(ax, C4, "4", "Three models")
    m1 = ("Model 1: Network design", ["Which DCs to keep, and which plant", "ships what to which DC and market", "Method: mixed integer linear program", *textwrap.wrap(f"Answer: keep {f['n_open']} of {f['n_dc']} DCs ({f['open']})", 40)])
    m2 = ("Model 2: Production planning", ["When and how much each plant makes", "Method: Wagner-Whitin, capacity-aware", "Trade-off: setup cost vs holding cost", f"Answer: {f['runs_base']} weekly runs become {f['runs_opt']}"])
    m3 = ("Model 3: Inventory", ["How much safety stock each DC holds", "Method: safety stock formula", "z x sqrt(demand risk + late-delivery risk)", f"Answer: {f['ss']:,} pallets at {f['csl']:.0%} service"])
    e2 = _box(ax, C4, R3[0], W4, MOD, *m2, tcolor="#4b2a7b")
    e1 = _box(ax, C4, R3[1], W4, MOD, *m1, tcolor="#4b2a7b")
    e3 = _box(ax, C4, R3[2], W4, MOD, *m3, tcolor="#4b2a7b")
    _split(ax, (C3 + W3 / 2 + 0.6, R3[1]), (C3 + W3 / 2 + C4 - W4 / 2) / 2, [(C4 - W4 / 2 - 1.2, y) for y in R3])
    _arrow(ax, (C4, e1[2] + 0.6), (C4, e2[3] - 0.6), color=RED, lw=2.6)
    _arrow(ax, (C4, e1[3] - 0.6), (C4, e3[2] + 0.6), color=RED, lw=2.6)
    ax.text(C4 + 1.8, (e1[2] + e2[3]) / 2, "volume each plant must make", fontsize=8.8, color=RED, va="center", style="italic")
    ax.text(C4 + 1.8, (e1[3] + e3[2]) / 2, "which DC serves which market", fontsize=8.8, color=RED, va="center", style="italic")

    # 5 decisions
    _header(ax, C5, "5", "Decisions")
    _box(ax, C5, R3[1], W5, OUT, "Scorecard", [f"${f['weekly']:,.0f} a week", f"${f['per_pallet']:.0f} per pallet", f"{f['co2']:,.0f} t CO2 a year", f"{f['csl']:.0%} service level",
                                                "", "Actions", "close the DCs not needed", "batch production runs", "set reorder points", "and safety stock", "", "Also computed", "savings vs reference case", "stress tests, cost to serve", "", "Dashboard", "sliders re-run the", "whole chain live"],
         lfs=9.2)
    _merge(ax, [(C4 + W4 / 2 + 0.6, y) for y in R3], (C4 + W4 / 2 + C5 - W5 / 2) / 2, (C5 - W5 / 2 - 1.2, R3[1]))

    ax.text(80, 2.5, "Every number on this page comes from the run that produced it. The data is simulated (fictional company); "
            "the flow is the one a real ERP / WMS / TMS integration follows.", ha="center", fontsize=10, color=GREY, style="italic")
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.3, **({"format": "png"} if hasattr(path, "write") else {}))
    plt.close(fig)


def facts_from(co, tables, base):
    """The numbers the flowchart quotes, read from a finished run."""
    log = tables["data_quality_log"].set_index("step")
    k, t = base.kpi, base.terms
    return dict(
        orders_in=int(log.loc["remove duplicate order lines", "rows_in"]), receipts=int(log.loc["remove impossible lead times", "rows_in"]),
        lanes=int(log.loc["convert km to miles", "rows_in"]), dups=int(log.loc["remove duplicate order lines", "rows_affected"]),
        cancelled=int(log.loc["keep shipped lines only", "rows_affected"]), broken=int(log.loc["quarantine incomplete lines", "rows_affected"]),
        clean_lines=int(log.loc["match item to item master", "rows_out"]), profiles=len(co.demand),
        lead_days=float(tables["fact_lead_time"]["mean_days"].iloc[0]), setup=t.setup_cost, hold=t.holding_rate_year, rate=t.rate_per_pallet_mile,
        n_open=len(k["open_dcs"]), n_dc=len(co.dcs), open=", ".join(co.city(d) for d in k["open_dcs"]),
        runs_base=base.lots.weekly_runs_baseline, runs_opt=base.lots.runs, ss=k["safety_stock"], csl=k["service_level"],
        weekly=k["weekly_cost"], per_pallet=k["cost_per_pallet"], co2=k["co2_tonnes_year"])
