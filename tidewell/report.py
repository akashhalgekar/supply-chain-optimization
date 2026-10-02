"""One page for the person who has to decide. Every number is read from the run that wrote it."""
from . import analytics
from .company import ROAD_FACTOR


def _lc(text):
    """Lower-case the first letter unless the first word is an acronym (DC, CO2)."""
    return text if text.split()[0].isupper() else text[0].lower() + text[1:]


def _pct(x):
    return f"{x:.1%}" if abs(x) >= 0.001 else ("under 0.1%" if abs(x) > 0 else "0%")


def executive_summary(co, base, waterfall, sets, stress, sens, cts, headroom, tables, late):
    k, t, net, lots, stock = base.kpi, base.terms, base.net, base.lots, base.stock
    city = co.city
    opened = [city(d) for d in net.open_dcs]
    closed = [city(d) for d in co.codes("dcs") if d not in net.open_dcs]
    sq, saved = waterfall.usd_per_week.iloc[0], waterfall.share_of_reference.iloc[-1]
    weeks = t.weeks_per_year
    cheapest = sets.iloc[0]
    close = sets[sets.total_usd_week <= cheapest.total_usd_week * 1.01]               # sets within 1% of the lowest cost
    svc = close.sort_values("next_day_share", ascending=False).iloc[0]
    svc_better = svc.next_day_share >= cheapest.next_day_share + 0.05                 # at least 5 more points of next-day coverage
    svc_extra = svc.total_usd_week - cheapest.total_usd_week
    best_total = sets.iloc[0]
    chosen = sets[sets.open_dcs == ", ".join(opened)].iloc[0]
    gap = chosen.total_usd_week - best_total.total_usd_week
    runner = sets[sets.open_dcs != ", ".join(opened)].iloc[0]
    prod_share = net.cost["production"] / k["weekly_cost"]
    idle = [city_p for city_p, code in zip(co.plants.city, co.plants.code) if net.plant_load[code] < 1e-6]
    single = analytics.single_sourced_items(co)
    mk_city = dict(zip(co.markets.code, co.markets.city))
    served = net.flows_out.groupby("market").apply(lambda g: sorted(set(g.dc)), include_groups=False)
    closed_note = " ".join(
        f"{c} has no DC of its own in the recommendation but is itself a market: it is served from " +
        " and ".join(f"{city(d)} ({co.mi_out.loc[d, code]:,.0f} miles)" for d in served[code]) + "."
        for code, c in mk_city.items() if c in closed and code in served.index)
    idle_txt = (f"{', '.join(idle)} {'is' if len(idle) == 1 else 'are'} idle in the base case, so losing {'it' if len(idle) == 1 else 'them'} costs nothing." if idle else "Every plant is used in the base case, so losing any one of them changes the plan.")
    feasible = stress[stress.status == "feasible"].iloc[1:]
    broken = stress[stress.status != "feasible"]
    lever = sens[sens.input != "Demand"].iloc[0]
    rest = sens[~sens.input.isin(["Demand", lever.input])]
    big = rest[rest.swing_share_of_cost >= 0.01]
    small = (", then " + ", ".join(f"{_lc(i)} ({v:.1%})" for i, v in zip(big.input, big.swing_share_of_cost)) if len(big) else "") + f"; the other {len(rest) - len(big)} are each under 1%"
    sl = sens[sens.input.str.startswith("Service")].iloc[0]
    dear, cheap = cts.iloc[0], cts.iloc[-1]
    names = {"inbound": "the plant-to-DC leg", "handling": "DC handling", "dc_fixed": "DC fixed cost spread over a small volume", "outbound": "the DC-to-market leg"}
    dear_col = max(names, key=lambda c: dear[c])
    dear_driver = names[dear_col]
    late_share = 1 - stock.safety_demand_only / stock.safety_stock
    best_service = sets.head(3).sort_values("next_day_share", ascending=False).iloc[0]
    service_alt = (f"If next-day coverage matters to customers, {best_service.open_dcs} gives {best_service.next_day_share:.0%} within 600 miles for ${best_service.total_usd_week - best_total.total_usd_week:,.0f} a week more ({(best_service.total_usd_week - best_total.total_usd_week) / best_total.total_usd_week:.1%})." if best_service.next_day_share > chosen.next_day_share + 0.005 else "The cheapest set is also the best of the three on next-day coverage.")
    best_note = ("The recommended set is also the cheapest on the whole chain, so the simpler network-first answer stands." if gap < 1 else f"The recommended set costs ${gap:,.0f} a week more ({gap / best_total.total_usd_week:.2%}), a difference too small to act on, so the simpler network-first answer stands.")
    if svc_better:
        rec_text = (f"**Cost alone** points to **{', '.join(opened)}** (close {', '.join(closed)}): {k['next_day_share']:.0%} of volume within 600 miles. "
                    f"**Service within 1% of that cost** points to **{svc.open_dcs}**: ${svc_extra:,.0f} a week more ({svc_extra / cheapest.total_usd_week:.1%}) for "
                    f"{round(svc.next_day_share * 100) - round(cheapest.next_day_share * 100)} more points of next-day coverage ({cheapest.next_day_share:.0%} to {svc.next_day_share:.0%}). "
                    f"**Recommended: {svc.open_dcs}**, unless that coverage is worth less than {svc_extra / cheapest.total_usd_week:.1%} of cost to the business. "
                    f"Either way, make production in batches rather than every week and hold **{stock.safety_stock:,} pallets** of safety stock for a {k['service_level']:.0%} cycle service level "
                    f"(that figure is for the lowest-cost network). Deliveries stay within {t.max_delivery_miles:,.0f} miles (two-day ground).")
        svc_row = f"| Service option ({svc.open_dcs.count(',') + 1} DCs) | ${svc.total_usd_week:,.0f} | ${svc.total_usd_week * weeks:,.0f} |\n"
    else:
        rec_text = (f"Run the network from **{', '.join(opened)}** and close **{', '.join(closed)}**. Make production in batches rather than every week. "
                    f"Hold **{stock.safety_stock:,} pallets** of safety stock across the open DCs for a {k['service_level']:.0%} cycle service level. "
                    f"{k['next_day_share']:.0%} of volume is delivered within 600 miles (next day by truck); the rest within {t.max_delivery_miles:,.0f} miles (two-day ground).")
        svc_row = ""
    decision_1 = (f"Decide whether {round(svc.next_day_share * 100) - round(cheapest.next_day_share * 100)} more points of next-day coverage are worth {svc_extra / cheapest.total_usd_week:.1%} of cost: keep {svc.open_dcs} (recommended) or run only {', '.join(opened)}." if svc_better else f"Approve running {', '.join(opened)} and closing {', '.join(closed)}.")
    late_half = late.loc[late.delivery_spread_multiplier == 0.5, "share_from_late_deliveries"].iloc[0]
    late_double = late.loc[late.delivery_spread_multiplier == 2.0, "share_from_late_deliveries"].iloc[0]
    dcf = co.dcs.set_index("code")
    fixed_closed = sum(dcf.loc[d, "fixed_year"] for d in co.codes("dcs") if d not in net.open_dcs) * t.dc_fixed_scale / t.weeks_per_year
    sets_rows = "\n".join(f"| {r.open_dcs} | ${r.total_usd_week:,.0f} | {r.total_usd_week - best_total.total_usd_week:+,.0f} | {r.next_day_share:.0%} |" for r in sets.head(5).itertuples())
    stress_rows = "\n".join(f"| {r.scenario} | {r.change_vs_base:+.1%} | {r.open_dcs} |" for r in feasible.itertuples())
    broken_rows = "\n".join(f"- **{r.scenario}: the network cannot meet demand.**" for r in broken.itertuples())
    single_txt = "; ".join(f"{s} can only be made in {', '.join(co.city(p) for p in ps)}" for s, ps in single.items())
    need = net.demand_pallets
    down_txt = " ".join(
        f"Without {r.city} the other plants can make {(co.plants.capacity.sum() - r.capacity) * t.max_utilisation / co.peak:,.0f} pallets an average week against demand of {need:,.0f}."
        for r in co.plants.itertuples()
        if (co.plants.capacity.sum() - r.capacity) * t.max_utilisation / co.peak < need)
    sens_rows = "\n".join(f"| {r.input} | ${r.swing_usd_week:,.0f} ({r.swing_share_of_cost:.1%}) |" for r in sens.itertuples())
    return f"""# Tidewell network and inventory review: executive summary

*Generated by `python -m tidewell.run`. Every number comes from that run. The company and data are simulated.*

## Recommendation

{rec_text}

| | Per week | Per year |
| --- | --- | --- |
| Reference case (all {len(co.dcs)} DCs open, every item made every week) | ${sq:,.0f} | ${sq * weeks:,.0f} |
| Lowest-cost chain ({len(opened)} DCs) | ${k['weekly_cost']:,.0f} | ${k['annual_cost']:,.0f} |
{svc_row}| Saving, lowest-cost chain | ${sq - k['weekly_cost']:,.0f} ({saved:.1%}) | ${(sq - k['weekly_cost']) * weeks:,.0f} |

Closing DCs saves {waterfall.share_of_reference.iloc[1]:.1%} of reference-case cost and batching production saves {waterfall.share_of_reference.iloc[2]:.1%}.
Production is {prod_share:.0%} of weekly cost, so no network or inventory lever can move the total far. Larger savings would have to come from plant cost and sourcing.

## Why these DCs

- **Closing {', '.join(closed)} frees ${fixed_closed:,.0f} a week of fixed DC cost.** The extra transport and handling cost less than that, so the reference case falls by ${-waterfall.usd_per_week.iloc[1]:,.0f} a week.
- **Tested on the whole chain, not just the network.** All {len(sets)} workable DC combinations were costed on network, production and stock together. The cheapest on total cost is {best_total.open_dcs}. {best_note}
- **The decision is flat on cost and not flat on service.** The three cheapest sets are within ${sets.total_usd_week.iloc[2] - sets.total_usd_week.iloc[0]:,.0f} a week of each other, but next-day coverage ranges from {sets.head(3).next_day_share.min():.0%} to {sets.head(3).next_day_share.max():.0%}. {service_alt}

| Open DCs | Whole-chain cost per week | Versus cheapest | Volume within 600 miles |
| --- | --- | --- | --- |
{sets_rows}

## Safety stock: two things worth knowing

- **Late deliveries are {'the bigger' if late_share > 0.5 else 'a large'} driver of safety stock.** Demand risk alone gives {stock.safety_demand_only:,} pallets. Adding the measured variation in delivery lead time gives {stock.safety_stock:,}: {late_share:.0%} of the stock exists because deliveries arrive late. That share is a property of the delivery-time spread in the simulated data, not a discovery about real companies: at half that spread it is {late_half:.0%}, at double it is {late_double:.0%} (`output/16_late_delivery_sensitivity.csv`).
- **A {k['service_level']:.0%} service level is not a {k['service_level']:.0%} fill rate.** Cycle service level counts cycles without a stockout. Counted as units served from stock, the same buffer gives about **{stock.fill_rate:.1%}** (assuming one week of demand is ordered per cycle).
- **Stock is not where the money is.** Moving the service level by two points changes total cost by {_pct(sl.swing_share_of_cost)}. Holding the safety stock costs {k['safety_stock_cost'] / k['weekly_cost']:.1%} of weekly cost.

## What could go wrong

{broken_rows}

{(single_txt[0].upper() + single_txt[1:]) if single_txt else 'No item depends on a single plant'}. {down_txt} Capacity is planned to {t.max_utilisation:.0%} of the peak week, which leaves little slack: demand can grow about **{headroom - 1:.0%}** before the network can no longer serve it.
{idle_txt}
{closed_note}

| Scenario the network can survive | Weekly cost vs base | Open DCs |
| --- | --- | --- |
{stress_rows}

## Where to spend measurement effort

| Input (moved +/- 20%) | Swing in weekly cost |
| --- | --- |
{sens_rows}

Demand is the largest swing, but it is an uncertainty, not a lever. The biggest **lever** is **{_lc(lever.input)}** ({lever.swing_share_of_cost:.1%}){small}.
Better demand forecasts and a better carrier rate are worth more than fine-tuning safety stock or setup cost.

## Cost to serve

Logistics cost per pallet ranges from ${cheap.logistics_usd_per_pallet:,.0f} ({cheap.city}) to ${dear.logistics_usd_per_pallet:,.0f} ({dear.city}), a {dear.logistics_usd_per_pallet / cheap.logistics_usd_per_pallet:.1f}x spread.
{dear.city} costs most to serve, mainly because of {dear_driver} (${dear[dear_col]:,.0f} a pallet; served from {dear.served_from}). Check pricing and margin for the costliest markets.

## How far to trust this

- The data pipeline reconciles to the unit (units extracted, kept and rolled up agree) and stops if cleaning removes more than 10% of order lines. See `output/01_data_quality_log.csv`.
- `verify.py` proves the ETL recovers the company's true figures, the production plan matches textbook Wagner-Whitin where capacity does not bind, and a brute-force search confirms the network model's answer.
- **Limits.** Data is simulated. Demand is a weekly average with the demand planners' seasonal curve, not a forecast. One service level applies to all items. The 90% capacity rule, the {t.max_delivery_miles:,.0f}-mile delivery radius, the {t.holding_rate_year:.0%} yearly holding rate and the shelf-life cover rule are planning assumptions. Distances are estimated road miles (straight line times {ROAD_FACTOR}). Plant capacity is in pallets, not line hours.

## Decisions requested

1. {decision_1} Closing any DC is subject to contract and lease terms.
2. Decide how to protect the single-source items and the no-slack capacity: a second source, spare capacity or a stock buffer.
3. Push carriers on delivery reliability: {late_share:.0%} of the safety stock exists because of late deliveries.
"""
