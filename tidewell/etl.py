"""ETL: Extract the raw ERP / WMS / TMS files, Transform them into clean tables, Load them into the warehouse folder.

  Extract    read every raw file exactly as the source system delivered it
  Transform  one spelling per city, one date format; drop duplicate, cancelled and broken lines; units -> pallets,
             km -> miles, per day -> per week; roll order lines up to weekly demand and a mean and spread per market and item
  Load       write dimension tables (what things are) and fact tables (measurements), plus a data quality log

Every cleaning rule is counted in the log. Two safeguards stop a bad extract from loading quietly:
  * a control total: units extracted - units removed must equal units rolled up into weekly demand
  * a drop limit: if cleaning removes more than 10% of the order lines, the load stops
"""
import os
import pandas as pd

MILES_PER_KM = 0.621371
WORKING_DAYS = 5
MAX_DROP_SHARE = 0.10
RAW = ["erp_item_master", "erp_seasonal_profile", "erp_work_centres", "erp_customers", "erp_finance_params", "erp_sales_orders",
       "wms_sites", "wms_goods_receipts", "tms_lanes", "tms_rate_card"]


class Log:
    def __init__(self):
        self.rows = []

    def add(self, source, step, n_in, n_out, note):
        self.rows.append(dict(source=source, step=step, rows_in=int(n_in), rows_out=int(n_out), rows_affected=int(n_in - n_out), note=note))

    def frame(self):
        return pd.DataFrame(self.rows)


def extract(raw_dir):
    return {n: pd.read_csv(os.path.join(raw_dir, f"{n}.csv")) for n in RAW}


def _dates(s):
    s = s.astype(str)
    is_iso = s.str.match(r"^\d{4}-")
    return pd.to_datetime(s.where(is_iso), format="%Y-%m-%d", errors="coerce").fillna(
        pd.to_datetime(s.where(~is_iso), format="%d/%m/%Y", errors="coerce"))


def _units(df):
    return float(df["qty_units"].fillna(0).sum())


def _orders(raw, skus, customers, log):
    o, n0, units_in = raw.copy(), len(raw), _units(raw)
    n = len(o); o = o.drop_duplicates("order_line_id")
    log.add("ERP orders", "remove duplicate order lines", n, len(o), "same order_line_id twice")
    n = len(o); o = o[o["status"].str.upper() == "SHIPPED"]
    log.add("ERP orders", "keep shipped lines only", n, len(o), "cancelled orders were never served")
    n = len(o); o = o.dropna(subset=["item_code", "qty_units"]); o = o[o["qty_units"] > 0]
    log.add("ERP orders", "quarantine incomplete lines", n, len(o), "missing item code, or missing or zero quantity")
    o = o.assign(order_date=_dates(o["order_date"]))
    n = len(o); o = o.dropna(subset=["order_date"])
    log.add("ERP orders", "read mixed date formats", n, len(o), "YYYY-MM-DD and DD/MM/YYYY both converted")
    key = customers.assign(k=customers["city"].str.strip().str.lower()).set_index("k")["customer_code"]
    o["market"] = o["ship_to_city"].str.strip().str.lower().map(key)
    n = len(o); o = o.dropna(subset=["market"])
    log.add("ERP orders", "match city to customer", n, len(o), "Chicago, CHICAGO and ' chicago' all become MK-CHI")
    n = len(o); o = o[o["item_code"].isin(skus["code"])]
    log.add("ERP orders", "match item to item master", n, len(o), "unknown items dropped")
    if n0 - len(o) > MAX_DROP_SHARE * n0:
        raise ValueError(f"ETL stopped: cleaning removed {n0 - len(o)} of {n0} order lines (limit {MAX_DROP_SHARE:.0%}). Check the ERP extract.")
    kept = _units(o)
    log.add("ERP orders", "control total: units extracted vs kept", n0, len(o),
            f"{units_in:,.0f} units extracted, {kept:,.0f} kept, {units_in - kept:,.0f} removed as duplicates, cancelled or broken")
    o["pallets"] = o["qty_units"] / o["item_code"].map(skus.set_index("code")["units_pallet"])
    start = o["order_date"].min().normalize()
    start -= pd.Timedelta(days=start.weekday())
    o["week"] = (o["order_date"] - start).dt.days // 7 + 1
    return o.rename(columns={"item_code": "sku"})[["market", "sku", "week", "pallets"]], kept


def transform(raw):
    log = Log()
    skus = raw["erp_item_master"].rename(columns={"item_code": "code", "description": "name", "units_per_pallet": "units_pallet",
                                                  "unit_weight_kg": "kg_unit", "std_cost_usd_per_pallet": "cost_pallet"})
    skus["shelf_life_weeks"] = skus["shelf_life_weeks"].astype(int)
    plants = raw["erp_work_centres"].rename(columns={"plant_code": "code", "weekly_capacity_pallets": "capacity", "item_codes_allowed": "items"})
    markets = raw["erp_customers"].rename(columns={"customer_code": "code"})
    sites = raw["wms_sites"]
    dcs = pd.DataFrame({"code": sites.site_code, "city": sites.city, "fixed_year": sites.annual_fixed_cost_usd,
                        "capacity": sites.throughput_pallets_per_day * WORKING_DAYS, "handling": sites.handling_cost_usd_per_pallet})
    log.add("WMS sites", "convert pallets per day to per week", len(sites), len(dcs), f"x {WORKING_DAYS} working days")

    orders, kept_units = _orders(raw["erp_sales_orders"], skus, raw["erp_customers"], log)
    weeks = range(1, int(orders.week.max()) + 1)
    grid = pd.MultiIndex.from_product([list(markets.code), list(skus.code), weeks], names=["market", "sku", "week"]).to_frame(index=False)
    weekly = grid.merge(orders.groupby(["market", "sku", "week"], as_index=False).pallets.sum(), how="left", on=["market", "sku", "week"])
    empty = int(weekly.pallets.isna().sum())
    weekly["pallets"] = weekly.pallets.fillna(0.0)
    rolled = float((weekly.pallets * weekly.sku.map(skus.set_index("code")["units_pallet"])).sum())
    if abs(rolled - kept_units) > 1.0:
        raise ValueError(f"ETL stopped: weekly demand ({rolled:,.1f} units) does not reconcile to cleaned orders ({kept_units:,.1f} units).")
    log.add("ERP orders", "roll up to weekly demand", len(orders), len(weekly), f"order lines grouped by market, item, week; {empty} empty weeks set to zero")
    g = weekly.groupby(["market", "sku"]).pallets
    stats = pd.DataFrame({"mu": g.mean().round(1), "sigma": g.std(ddof=1).round(1)}).reset_index()
    log.add("ERP orders", "weekly mean and spread", len(weekly), len(stats), "the two numbers that drive network flows and safety stock")
    share = stats.groupby("market").mu.sum()
    markets = markets.assign(weight=markets.code.map(share / share.mean()).round(2))

    lanes = raw["tms_lanes"].copy()
    in_km = lanes.distance_unit.str.lower() == "km"
    lanes["miles"] = lanes.distance.where(~in_km, lanes.distance * MILES_PER_KM).round(0).astype(int)
    log.add("TMS lanes", "convert km to miles", len(lanes), len(lanes), f"{int(in_km.sum())} lanes were quoted in kilometres")
    mi_in = lanes[lanes.lane_type == "INBOUND"].pivot(index="origin_code", columns="dest_code", values="miles").loc[list(plants.code), list(dcs.code)]
    mi_out = lanes[lanes.lane_type == "OUTBOUND"].pivot(index="origin_code", columns="dest_code", values="miles").loc[list(dcs.code), list(markets.code)]

    gr = raw["wms_goods_receipts"].copy()
    gr["days"] = (pd.to_datetime(gr.receipt_date) - pd.to_datetime(gr.ship_date)).dt.days
    n = len(gr); gr = gr[gr.days >= 0]
    log.add("WMS receipts", "remove impossible lead times", n, len(gr), "receipt dated before shipment")
    by_dc = gr.groupby("dc_code").days.agg(["count", "mean", "std"]).reset_index().rename(columns={"dc_code": "dc", "count": "receipts", "mean": "mean_days", "std": "sd_days"})
    by_dc["mean_weeks"] = (by_dc.mean_days / 7).round(3)
    by_dc["sd_weeks"] = (by_dc.sd_days / 7).round(3)
    overall = pd.DataFrame([dict(mean_days=gr.days.mean(), sd_days=gr.days.std(ddof=1), receipts=len(gr))])

    fin = raw["erp_finance_params"].set_index("parameter")["value"]
    rate = raw["tms_rate_card"].set_index("parameter")["value"]
    terms = pd.DataFrame([("setup_cost", fin["setup_cost_per_run"]), ("holding_rate_year", fin["holding_cost_rate_per_year"]),
                          ("rate_per_pallet_mile", rate["cost_per_pallet_mile"]), ("co2_per_pallet_mile", rate["co2_per_pallet_mile"])],
                         columns=["parameter", "value"])
    season = raw["erp_seasonal_profile"][["planning_week", "demand_index"]].rename(columns={"planning_week": "week", "demand_index": "index"})
    return dict(dim_sku=skus[["code", "name", "category", "units_pallet", "kg_unit", "cost_pallet", "shelf_life_weeks"]],
                dim_plant=plants[["code", "city", "capacity", "cost_index", "items"]], dim_dc=dcs, dim_market=markets[["code", "city", "weight"]],
                lane_plant_dc=mi_in.reset_index(), lane_dc_market=mi_out.reset_index(),
                fact_weekly_demand=weekly, fact_demand_stats=stats, fact_lead_time=overall, fact_lead_time_by_dc=by_dc,
                terms=terms, fact_season=season, data_quality_log=log.frame())


def load(tables, wh_dir):
    os.makedirs(wh_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(os.path.join(wh_dir, f"{name}.csv"), index=False)


def run(raw_dir, wh_dir):
    tables = transform(extract(raw_dir))
    load(tables, wh_dir)
    return tables
