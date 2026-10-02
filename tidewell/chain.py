"""The whole chain in one call: network design, then production plan, then safety stock, then the scorecard."""
from dataclasses import dataclass
from .company import Company, Terms

NEXT_DAY_MILES = 600            # a truck can reach this far in one driving day (hours-of-service limits)
from . import network, lotsizing, safetystock


@dataclass
class ChainResult:
    terms: Terms
    net: network.NetworkPlan
    lots: lotsizing.LotPlan
    stock: safetystock.StockPlan
    kpi: dict


def run(co: Company, terms: Terms = None, dc_set=None, plants_down=()) -> ChainResult:
    terms = terms or co.terms
    net = network.design(co, terms, dc_set=dc_set, plants_down=plants_down)
    if not net.ok:                                   # cannot meet demand: report it, do not plan around a broken network
        return ChainResult(terms, net, None, None, dict(feasible=False))
    lots = lotsizing.plan(co, terms, net.plant_volume)
    stock = safetystock.size(co, terms, net)
    plan_week = lots.total / len(co.season)
    near = sum(r.pallets for r in net.flows_out.itertuples() if co.mi_out.loc[r.dc, r.market] <= NEXT_DAY_MILES)
    weekly = net.cost["total"] + plan_week + stock.holding_week
    kpi = dict(
        feasible=True, open_dcs=net.open_dcs, weekly_cost=weekly, annual_cost=weekly * terms.weeks_per_year,
        cost_per_pallet=weekly / net.demand_pallets, co2_tonnes_year=net.co2_kg_week * terms.weeks_per_year / 1000,
        service_level=terms.service_level, fill_rate=stock.fill_rate,
        network_cost=net.cost["total"], planning_cost=plan_week, stock_cost=stock.holding_week,
        demand_pallets=net.demand_pallets, safety_stock=stock.safety_stock,
        busiest_plant_peak_load=max(net.plant_load.values()) * co.peak,
        safety_stock_cost=stock.safety_holding_week, next_day_share=near / net.demand_pallets)
    return ChainResult(terms, net, lots, stock, kpi)
