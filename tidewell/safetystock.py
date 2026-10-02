"""Safety stock and reorder points for every open DC and item.

Stock held at a DC protects against two things while it waits for a delivery:
  1. demand running higher than average
  2. the delivery arriving later than average

    safety stock = z * sqrt( LT * sigma_D^2  +  D^2 * sigma_LT^2 )
    reorder point = D * LT + safety stock

D and sigma_D are the weekly demand mean and spread the DC serves, LT and sigma_LT the lead time mean and spread
in weeks for deliveries into that DC (measured from its goods receipts, so a DC far from the plants waits longer), z the normal quantile of the target cycle service level. Demand that reaches a DC from several markets
is pooled: means add, variances add (markets are assumed independent).

Fill rate (share of demand served straight from stock) is reported next to the service level. It uses the standard
normal loss function and assumes one week of demand is ordered per replenishment cycle. That order size is an
assumption, not a measurement.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.stats import norm
from .company import Company, Terms
from .network import NetworkPlan


@dataclass
class StockPlan:
    detail: pd.DataFrame        # dc, sku, mu, sigma, sd_lt, safety_stock, safety_demand_only, reorder_point, avg_stock, holding_week
    safety_stock: int
    safety_demand_only: int
    holding_week: float         # carrying cost of all DC stock: safety stock plus average cycle stock
    safety_holding_week: float  # carrying cost of the safety stock part alone
    holding_year: float
    fill_rate: float
    z: float


def size(co: Company, terms: Terms, net: NetworkPlan) -> StockPlan:
    z = float(norm.ppf(terms.service_level))
    sig = {(r.market, r.sku): r.sigma * terms.demand_scale for r in co.demand.itertuples()}
    mu_ms = {(r.market, r.sku): r.mu * terms.demand_scale for r in co.demand.itertuples()}
    rows, shortage = [], 0.0
    for (dc, sku), g in net.flows_out.groupby(["dc", "sku"]):
        mu = float(g.pallets.sum())
        # a market split across DCs sends each DC its share of that market's demand and spread
        var = sum((f.pallets / mu_ms[f.market, sku] * sig[f.market, sku]) ** 2 for f in g.itertuples())
        sigma = float(np.sqrt(var))
        lt, sd_lt = terms.lead_time(dc)
        sd_lt = 0.0 if terms.ignore_lead_time_risk else sd_lt
        spread = float(np.sqrt(lt * sigma ** 2 + mu ** 2 * sd_lt ** 2))
        ss = z * spread
        zk = z
        loss = spread * (norm.pdf(zk) - zk * (1 - norm.cdf(zk)))                # expected pallets short per cycle
        shortage += loss
        h = co.hold_week(sku, terms)
        rows.append((dc, sku, mu, sigma, lt, sd_lt, ss, z * sigma * np.sqrt(lt), mu * lt + ss, ss + mu / 2.0, ss * h, (ss + mu / 2.0) * h, mu))
    detail = pd.DataFrame(rows, columns=["dc", "sku", "mu", "sigma", "lead_time_weeks", "sd_lt", "safety_stock", "safety_demand_only",
                                         "reorder_point", "avg_stock", "safety_holding_week", "holding_week", "_mu"])
    fill = 1.0 - shortage / detail["_mu"].sum()
    detail = detail.drop(columns="_mu")
    hold = float(detail.holding_week.sum())
    return StockPlan(detail, int(round(detail.safety_stock.sum())), int(round(detail.safety_demand_only.sum())),
                     hold, float(detail.safety_holding_week.sum()), hold * terms.weeks_per_year, float(fill), z)
