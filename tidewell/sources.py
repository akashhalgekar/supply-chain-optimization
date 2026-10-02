"""Simulated source systems: ERP, WMS and TMS extracts for Tidewell.

Tidewell is fictional, so there is no real system to read from. This module plays the part of those systems and writes
the raw CSV files an analyst would be handed: orders and item data from an ERP, warehouse sites and goods receipts from a
WMS, lanes and carrier rates from a TMS.

The files are deliberately messy, as real extracts are: dates in two formats, city names in different cases, order
quantities in single units instead of pallets, some distances in kilometres, DC capacity per day instead of per week,
duplicate lines, cancelled orders and lines with missing fields. The ETL (etl.py) must clean all of it.

The numbers underneath come from company.ground_truth(), so verify.py can prove the ETL recovered them. Deterministic.
"""
import os
import numpy as np
import pandas as pd
from .company import ground_truth

NOISE_SEED = 33
HISTORY_WEEKS = 52
HISTORY_START = pd.Timestamp("2025-09-01")      # a Monday; 52 weeks of history end in late August 2026
KM_PER_MILE = 1.609344
WORKING_DAYS = 5


def _typed_badly(rng, city):
    return str(rng.choice([city, city.upper(), f" {city.lower()}", f"{city} "], p=[0.7, 0.1, 0.1, 0.1]))


def _exact_moments(rng, n, mean, sd):
    """n draws whose sample mean and standard deviation equal the targets exactly."""
    z = rng.standard_normal(n)
    z = (z - z.mean()) / z.std(ddof=1)
    return mean + sd * z


def _sales_orders(co, rng):
    upp = co.skus.set_index("code")["units_pallet"]
    city = co.markets.set_index("code")["city"]
    rows, n = [], 0
    for r in co.demand.itertuples():
        for _ in range(100):                                  # a week of negative demand is impossible: redraw
            weekly = _exact_moments(rng, HISTORY_WEEKS, r.mu, r.sigma)
            if weekly.min() > 0:
                break
        else:
            raise ValueError(f"demand spread too large to simulate for {r.market}/{r.sku}: sigma {r.sigma} against mean {r.mu}")
        for w, pallets in enumerate(weekly):
            units = int(round(pallets * upp[r.sku]))
            k = int(rng.integers(1, 4))                                           # 1 to 3 order lines that week
            cuts = np.sort(rng.integers(0, units + 1, size=k - 1)) if k > 1 else np.array([], dtype=int)
            for part in np.diff(np.concatenate([[0], cuts, [units]])):
                day = HISTORY_START + pd.Timedelta(days=7 * w + int(rng.integers(0, 5)))
                n += 1
                rows.append((f"ORD{n:06d}", day, _typed_badly(rng, city[r.market]), r.sku, int(part), "SHIPPED"))
    df = pd.DataFrame(rows, columns=["order_line_id", "order_date", "ship_to_city", "item_code", "qty_units", "status"])
    iso = df["order_date"].dt.strftime("%Y-%m-%d")
    eu = df["order_date"].dt.strftime("%d/%m/%Y")
    df["order_date"] = np.where(rng.random(len(df)) < 0.35, eu, iso)

    base = len(df)
    dup = df.sample(frac=0.015, random_state=NOISE_SEED)
    cancelled = df.sample(frac=0.02, random_state=NOISE_SEED + 1).copy()
    cancelled["order_line_id"] = [f"ORD{base + i + 1:06d}" for i in range(len(cancelled))]
    cancelled["qty_units"] = (cancelled["qty_units"] * rng.uniform(0.5, 1.5, len(cancelled))).astype(int)
    cancelled["status"] = "CANCELLED"
    broken = df.sample(n=6, random_state=NOISE_SEED + 2).copy()
    broken["order_line_id"] = [f"ORD{base + len(cancelled) + i + 1:06d}" for i in range(6)]
    broken.loc[broken.index[:3], "item_code"] = None
    broken.loc[broken.index[3:], "qty_units"] = None
    return pd.concat([df, dup, cancelled, broken], ignore_index=True).sample(frac=1.0, random_state=NOISE_SEED + 3).reset_index(drop=True)


ORDER_PROCESSING_DAYS = 5          # days between a DC placing an order and the truck leaving
TRUCK_MILES_PER_DAY = 500             # road miles a truck covers in a day under driver hours-of-service rules


def _goods_receipts(co, rng, per_dc=40):
    """Plant -> DC deliveries. Lead time = receipt date minus order date: order processing plus driving time from the plants that
    supply the DC (average distance), so a DC far from the plants waits longer. Each DC also has its own reliability."""
    rows, k = [], 0
    for dc in co.dcs["code"]:
        mean_days = ORDER_PROCESSING_DAYS + float(co.mi_in[dc].mean()) / TRUCK_MILES_PER_DAY
        spread = float(rng.uniform(1.0, 3.0))
        for days in np.rint(_exact_moments(rng, per_dc, mean_days, spread)).astype(int):
            k += 1
            ship = HISTORY_START + pd.Timedelta(days=int(rng.integers(0, 360)))
            rows.append((f"GR{k:05d}", dc, str(rng.choice(co.skus["code"])), ship.strftime("%Y-%m-%d"),
                         (ship + pd.Timedelta(days=int(days))).strftime("%Y-%m-%d")))
    return pd.DataFrame(rows, columns=["receipt_id", "dc_code", "item_code", "ship_date", "receipt_date"])


def _lanes(co, rng):
    rows, k = [], 0
    for p, row in co.mi_in.iterrows():
        for d, mi in row.items():
            k += 1
            rows.append((f"LN{k:04d}", p, d, "INBOUND", float(mi)))
    for d, row in co.mi_out.iterrows():
        for m, mi in row.items():
            k += 1
            rows.append((f"LN{k:04d}", d, m, "OUTBOUND", float(mi)))
    df = pd.DataFrame(rows, columns=["lane_id", "origin_code", "dest_code", "lane_type", "distance"])
    df["distance_unit"] = "mi"
    in_km = rng.random(len(df)) < 1 / 12                                         # a few carrier tools quote in kilometres
    df.loc[in_km, "distance"] = (df.loc[in_km, "distance"] * KM_PER_MILE).round(2)
    df.loc[in_km, "distance_unit"] = "km"
    return df


def generate(raw_dir, truth=None):
    """Write every raw extract to raw_dir. `truth` is the company to simulate (Tidewell by default). Returns {file: rows}."""
    os.makedirs(raw_dir, exist_ok=True)
    co = truth or ground_truth()
    t = co.terms
    rng = np.random.default_rng(NOISE_SEED)
    files = {
        "erp_item_master": pd.DataFrame({"item_code": co.skus.code, "description": co.skus.name, "category": co.skus.category,
                                         "units_per_pallet": co.skus.units_pallet, "unit_weight_kg": co.skus.kg_unit,
                                         "std_cost_usd_per_pallet": co.skus.cost_pallet, "shelf_life_weeks": co.skus.shelf_life_weeks}),
        "erp_seasonal_profile": pd.DataFrame({"planning_week": range(1, len(co.season) + 1), "demand_index": co.season,
                                              "source": "demand planning team (S&OP seasonal profile)"}),
        "erp_work_centres": pd.DataFrame({"plant_code": co.plants.code, "city": co.plants.city, "weekly_capacity_pallets": co.plants.capacity,
                                          "cost_index": co.plants.cost_index, "item_codes_allowed": co.plants["items"]}),
        "erp_customers": pd.DataFrame({"customer_code": co.markets.code, "city": co.markets.city}),
        "erp_finance_params": pd.DataFrame([("setup_cost_per_run", t.setup_cost, "USD", "controlling: cost of one production changeover"),
                                            ("holding_cost_rate_per_year", t.holding_rate_year, "share of value", "controlling: capital, storage, insurance and obsolescence per year")],
                                           columns=["parameter", "value", "unit", "note"]),
        "erp_sales_orders": _sales_orders(co, rng),
        "wms_sites": pd.DataFrame({"site_code": co.dcs.code, "city": co.dcs.city, "site_type": "DC",
                                   "throughput_pallets_per_day": (co.dcs.capacity / WORKING_DAYS).round().astype(int),
                                   "handling_cost_usd_per_pallet": co.dcs.handling, "annual_fixed_cost_usd": co.dcs.fixed_year}),
        "wms_goods_receipts": _goods_receipts(co, rng),
        "tms_lanes": _lanes(co, rng),
        "tms_rate_card": pd.DataFrame([("cost_per_pallet_mile", t.rate_per_pallet_mile, "USD", "carrier contract line-haul rate"),
                                       ("co2_per_pallet_mile", t.co2_per_pallet_mile, "kg", "carrier emission factor")],
                                      columns=["parameter", "value", "unit", "note"]),
    }
    for name, df in files.items():
        df.to_csv(os.path.join(raw_dir, f"{name}.csv"), index=False)
    return {n: len(d) for n, d in files.items()}
