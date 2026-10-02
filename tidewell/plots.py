"""All charts. Each function saves one PNG and returns its path."""
from math import cos, radians
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from .company import CITY

# a rough outline of the lower 48 states (longitude, latitude), only to give the map some context
US_OUTLINE = [(-124.7, 48.4), (-122.8, 49.0), (-95.2, 49.0), (-89.6, 48.0), (-84.8, 46.5), (-82.5, 43.0), (-79.0, 43.3), (-76.5, 44.0), (-75.0, 45.0),
              (-71.5, 45.0), (-69.2, 47.4), (-67.8, 47.0), (-67.0, 44.8), (-70.0, 43.6), (-70.7, 42.5), (-70.0, 41.7), (-72.0, 41.2), (-74.0, 40.5),
              (-74.0, 39.5), (-75.5, 38.0), (-76.0, 36.9), (-75.5, 35.2), (-77.0, 34.5), (-79.0, 33.5), (-81.0, 31.9), (-81.4, 30.2), (-80.0, 26.8),
              (-80.4, 25.2), (-81.8, 26.0), (-82.8, 28.0), (-84.0, 30.0), (-85.5, 29.8), (-88.0, 30.4), (-89.5, 30.1), (-90.2, 29.1), (-92.0, 29.6),
              (-94.0, 29.6), (-97.0, 27.8), (-97.4, 26.0), (-99.0, 26.5), (-100.5, 28.7), (-102.5, 29.8), (-104.5, 29.7), (-106.5, 31.8),
              (-108.2, 31.8), (-111.0, 31.3), (-114.8, 32.5), (-117.1, 32.5), (-118.5, 34.0), (-120.6, 34.6), (-121.9, 36.6), (-123.0, 38.0),
              (-124.2, 40.3), (-124.4, 42.8), (-124.0, 46.2)]

NAVY, RED, GREY, GREEN, AMBER, INK = "#0b2a4a", "#c0392b", "#9aa5b1", "#1f8f7a", "#d4900a", "#14213d"


def _tidy(ax, bottom=True):
    for s in ("top", "right") + (() if bottom else ("bottom",)):
        ax.spines[s].set_visible(False)


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def network_map(co, net, path):
    """Plants, DCs (open and closed), markets and flows on a plain latitude/longitude plane."""
    fig, ax = plt.subplots(figsize=(11, 6.6), dpi=130)
    ax.fill(*zip(*US_OUTLINE), facecolor="#eef1f5", edgecolor="#c9d1db", lw=1, zorder=0)
    xy = lambda city: (CITY[city][1], CITY[city][0])
    volume = co.demand.groupby("market").mu.sum()
    out = net.flows_out.groupby(["dc", "market"], as_index=False).pallets.sum()
    top = out.pallets.max()
    for r in out.itertuples():
        (x1, y1), (x2, y2) = xy(co.city(r.dc)), xy(co.city(r.market))
        ax.plot([x1, x2], [y1, y2], color=NAVY, alpha=0.15 + 0.5 * r.pallets / top, lw=0.9, zorder=2)
    for r in net.flows_in.groupby(["plant", "dc"], as_index=False).pallets.sum().itertuples():
        (x1, y1), (x2, y2) = xy(co.city(r.plant)), xy(co.city(r.dc))
        ax.plot([x1, x2], [y1, y2], color=GREY, alpha=0.55, lw=1.0, ls="--", zorder=2)
    for r in co.markets.itertuples():
        x, y = xy(r.city)
        ax.scatter(x, y, s=30 + 120 * volume[r.code] / volume.max(), color=RED, alpha=0.85, edgecolor="white", zorder=4)
        ax.annotate(r.city, (x, y), fontsize=7.5, color="#555", xytext=(4, -9), textcoords="offset points")
    for r in co.dcs.itertuples():
        x, y = xy(r.city)
        if r.code in net.open_dcs:
            ax.scatter(x, y, s=330, color=NAVY, edgecolor="white", lw=2, zorder=6)
            ax.annotate(r.city, (x, y), fontsize=11, weight="bold", color=NAVY, xytext=(9, 7), textcoords="offset points")
        else:
            ax.scatter(x, y, s=230, facecolor="white", edgecolor=GREY, lw=2, zorder=5)
            ax.annotate(f"{r.city} (closed)", (x, y), fontsize=8.5, color=GREY, xytext=(9, 6), textcoords="offset points")
    for r in co.plants.itertuples():
        x, y = xy(r.city)
        used = net.plant_load[r.code]
        ax.scatter(x, y, s=260, marker="s", color=GREEN if used > 0 else "white", edgecolor=GREEN, lw=2, zorder=6)
        ax.annotate(f"{r.city} plant" + ("" if used > 0 else " (idle)"), (x, y), fontsize=9, color=GREEN, xytext=(8, -15), textcoords="offset points")
    ax.set_aspect(1 / cos(radians(38)))
    ax.set_xlim(-127, -66); ax.set_ylim(23.5, 50.5)
    ax.set_xticks([]); ax.set_yticks([]); _tidy(ax); ax.spines["left"].set_visible(False); ax.spines["bottom"].set_visible(False)
    ax.set_title(f"Network design: {len(net.open_dcs)} of {len(co.dcs)} candidate DCs stay open", fontsize=13, color=NAVY, weight="bold")
    return _save(fig, path)


def production_plan(lots, plant_city, plant, sku, path):
    d = lots.weekly[(lots.weekly.plant == plant) & (lots.weekly.sku == sku)].sort_values("week")
    runs = int((d.produce > 0.05).sum())
    fig, ax = plt.subplots(figsize=(11, 4.8), dpi=130)
    w, bw = d.week.to_numpy(), 0.27
    ax.bar(w - bw, d.produce, bw, color="#1f4e9c", label="produced that week")
    ax.bar(w, d.stock, bw, color=AMBER, label="stock at end of week")
    ax.bar(w + bw, d.demand, bw, color="#222", label="demand")
    ax.set_xticks(w); ax.set_xlabel("week"); ax.set_ylabel("pallets"); ax.legend(frameon=False)
    ax.set_title(f"{plant_city} / {sku}: {runs} production runs in 12 weeks instead of 12", fontsize=12, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def waterfall(df, path):
    v = df.usd_per_week.tolist()
    fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=130)
    ax.bar(0, v[0], color=GREY); ax.bar(1, v[1], bottom=v[0], color=GREEN); ax.bar(2, v[2], bottom=v[0] + v[1], color=GREEN); ax.bar(3, v[3], color=NAVY)
    for x, y, t in ((0, v[0], f"${v[0]:,.0f}"), (1, v[0], f"{v[1]:,.0f}"), (2, v[0] + v[1], f"{v[2]:,.0f}"), (3, v[3], f"${v[3]:,.0f}")):
        ax.text(x, y, t, ha="center", va="bottom", fontsize=9.5, color=NAVY)
    ax.set_xticks(range(4)); ax.set_xticklabels(["Reference case\n(all DCs, weekly runs)", "Close\nunneeded DCs", "Batch\nproduction", "Recommended"], fontsize=9.5)
    ax.set_ylim(min(v[3], v[0]) * 0.96, v[0] * 1.015); ax.set_ylabel("USD per week (axis starts above zero)")
    ax.set_title(f"Savings versus reference case: {df.share_of_reference.iloc[-1]:.1%} of weekly cost", fontsize=11.5, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def dc_sets(df, path, top=10):
    t = df.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(10.5, 5), dpi=130)
    gap = t.total_usd_week - t.total_usd_week.min()
    ax.barh(t.open_dcs, gap, color=[NAVY if i == len(t) - 1 else GREY for i in range(len(t))])
    for i, r in enumerate(t.itertuples()):
        ax.text(gap.iloc[i], i, f"  ${r.total_usd_week:,.0f}  (network-only rank {r.rank_network_only})", va="center", fontsize=8.5, color=NAVY)
    ax.set_xlim(0, gap.max() * 1.75); ax.set_xlabel("USD per week above the cheapest set")
    ax.set_title(f"Which DCs to keep: the {top} cheapest of {len(df)} workable sets, costed on the whole chain", fontsize=11, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def stress(df, path):
    d = df[df.scenario != "Base case"].copy()
    d["x"] = d.change_vs_base.fillna(0) * 100
    d = d.sort_values("x")
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=130)
    colors = [GREY if s != "feasible" else (RED if x > 5 else NAVY) for s, x in zip(d.status, d.x)]
    ax.barh(d.scenario, d.x, color=colors)
    for i, r in enumerate(d.itertuples()):
        txt = "  CANNOT MEET DEMAND" if r.status != "feasible" else f"  {r.change_vs_base:+.1%}  ({r.open_dcs})"
        ax.text(max(r.x, 0), i, txt, va="center", fontsize=8.5, color=RED if r.status != "feasible" else INK, weight="bold" if r.status != "feasible" else "normal")
    ax.set_xlim(0, max(d.x.max(), 5) * 1.9); ax.set_xlabel("change in weekly cost versus base case (%)")
    ax.set_title("What breaks the plan: each stress test", fontsize=11, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def tornado(df, path):
    t = df.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10.5, 4.6), dpi=130)
    ax.barh(t.input, t.swing_share_of_cost * 100, color=NAVY)
    for i, r in enumerate(t.itertuples()):
        ax.text(r.swing_share_of_cost * 100, i, f"  ${r.swing_usd_week:,.0f} a week ({r.swing_share_of_cost:.1%})", va="center", fontsize=8.5, color=NAVY)
    ax.set_xlim(0, t.swing_share_of_cost.max() * 100 * 1.5); ax.set_xlabel("swing in total weekly cost, % (inputs moved +/- 20%; service level +/- 2 points)")
    ax.set_title("Which input moves total cost the most", fontsize=11, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def cost_to_serve(df, path):
    c = df.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10.5, 5.6), dpi=130)
    left = np.zeros(len(c))
    for col, color, lab in (("inbound", GREY, "inbound (plant to DC)"), ("handling", "#4a5a8a", "DC handling"), ("dc_fixed", AMBER, "DC fixed cost"), ("outbound", NAVY, "outbound (DC to market)")):
        ax.barh(c.city, c[col], left=left, color=color, label=lab)
        left += c[col].to_numpy()
    for i, t in enumerate(c.logistics_usd_per_pallet):
        ax.text(t, i, f"  ${t:,.0f}", va="center", fontsize=8.5, color=NAVY)
    ax.set_xlim(0, c.logistics_usd_per_pallet.max() * 1.15); ax.set_xlabel("logistics cost per pallet delivered (USD)"); ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    ax.set_title("Cost to serve each market (production cost left out so markets compare fairly)", fontsize=11, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)


def setup_tradeoff(rows, path):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), dpi=130)
    axs[0].plot(rows.setup_cost, rows.runs, marker="o", color=NAVY); axs[0].set_xlabel("cost of one setup (USD)"); axs[0].set_ylabel("production runs in 12 weeks")
    axs[0].set_title("Higher setup cost: fewer, bigger batches", fontsize=11, color=NAVY, weight="bold")
    axs[1].plot(rows.setup_cost, rows.avg_stock, marker="o", color=AMBER); axs[1].set_xlabel("cost of one setup (USD)"); axs[1].set_ylabel("average pallets in stock")
    axs[1].set_title("...but more stock sits in the warehouse", fontsize=11, color=NAVY, weight="bold")
    for a in axs:
        _tidy(a)
    return _save(fig, path)


def stock_curves(rows, path):
    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=130)
    for lt, color in zip(sorted(rows.lead_time_scale.unique()), (GREY, NAVY, RED)):
        d = rows[rows.lead_time_scale == lt]
        ax.plot(d.service_level * 100, d.safety_stock, marker="o", color=color, label=f"lead times x{lt:g}")
    ax.set_xlabel("target service level (%)"); ax.set_ylabel("safety stock (pallets)"); ax.legend(frameon=False)
    ax.set_title("Safety stock rises with service level, faster with longer lead time", fontsize=11, color=NAVY, weight="bold")
    _tidy(ax)
    return _save(fig, path)
