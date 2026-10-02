"""Warehouse -> models. Reads the clean tables the ETL loaded and builds the Company the models use.
The models never read a raw ERP, WMS or TMS file."""
import os
import pandas as pd
from .company import Company, Terms
from . import sources, etl

DATA_DIR = os.environ.get("TIDEWELL_DATA") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def load_company(wh_dir):
    rd = lambda n: pd.read_csv(os.path.join(wh_dir, f"{n}.csv"))
    t = rd("terms").set_index("parameter")["value"]
    lt = rd("fact_lead_time_by_dc").sort_values("dc")
    terms = Terms(setup_cost=float(t["setup_cost"]), holding_rate_year=float(t["holding_rate_year"]),
                  rate_per_pallet_mile=float(t["rate_per_pallet_mile"]), co2_per_pallet_mile=float(t["co2_per_pallet_mile"]),
                  lead_time_by_dc=tuple((r.dc, float(r.mean_weeks), float(r.sd_weeks)) for r in lt.itertuples()))
    season = rd("fact_season").sort_values("week")["index"].to_numpy()
    mi_in, mi_out = rd("lane_plant_dc").set_index("origin_code"), rd("lane_dc_market").set_index("origin_code")
    mi_in.index.name = mi_out.index.name = None
    return Company(rd("dim_sku"), rd("dim_plant"), rd("dim_dc"), rd("dim_market"), rd("fact_demand_stats"),
                   mi_in, mi_out, terms, season / season.mean())


def build(data_dir=None, regenerate=False, truth=None):
    """Source systems -> ETL -> warehouse -> Company. Returns (company, tables). `truth` simulates a different company."""
    data_dir = data_dir or DATA_DIR
    raw, wh = os.path.join(data_dir, "raw"), os.path.join(data_dir, "warehouse")
    if regenerate or not os.path.exists(os.path.join(raw, "erp_sales_orders.csv")):
        sources.generate(raw, truth)
    tables = etl.run(raw, wh)
    return load_company(wh), tables


if __name__ == "__main__":
    co, tables = build(regenerate=True)
    print(tables["data_quality_log"].to_string(index=False))
