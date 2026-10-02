"""Tidewell Beverages: a fictional American drinks company, and the settings the models read.

Tidewell makes six drinks in three plants, can stock them in six candidate distribution
centres (DCs) and sells to fourteen markets. Everything here is invented for this project.

The figures below are the "ground truth" of the fictional company. The simulated ERP, WMS and
TMS extracts (sources.py) are generated from them, and the ETL (etl.py) has to recover them
from messy files. Nothing downstream reads this module's numbers directly: the models read the
clean warehouse tables.

Units: one pallet is the flow unit, one week the time unit, distances in road miles, money in US dollars.
"""
from dataclasses import dataclass, field, replace
from math import radians, sin, cos, asin, sqrt
import numpy as np
import pandas as pd

SEED = 21
HORIZON = 12                                     # planning weeks for production
CITY = {                                         # (latitude, longitude)
    "Columbus": (39.96, -82.99), "Dallas": (32.78, -96.80), "Sacramento": (38.58, -121.49),
    "Atlanta": (33.75, -84.39), "Chicago": (41.88, -87.63), "Newark": (40.74, -74.17), "Los Angeles": (34.05, -118.24),
    "Seattle": (47.61, -122.33), "New York": (40.71, -74.01), "Houston": (29.76, -95.37), "Phoenix": (33.45, -112.07),
    "Philadelphia": (39.95, -75.17), "Miami": (25.76, -80.19), "Denver": (39.74, -104.99), "Boston": (42.36, -71.06),
    "Minneapolis": (44.98, -93.27), "Detroit": (42.33, -83.05), "San Francisco": (37.77, -122.42),
    # more cities, used only to build other synthetic companies for the robustness test
    "Charlotte": (35.23, -80.84), "Nashville": (36.16, -86.78), "Kansas City": (39.10, -94.58), "St. Louis": (38.63, -90.20),
    "Indianapolis": (39.77, -86.16), "Cincinnati": (39.10, -84.51), "Pittsburgh": (40.44, -79.99), "Cleveland": (41.50, -81.69),
    "Memphis": (35.15, -90.05), "New Orleans": (29.95, -90.07), "Orlando": (28.54, -81.38), "Tampa": (27.95, -82.46),
    "Salt Lake City": (40.76, -111.89), "Portland": (45.52, -122.68), "Las Vegas": (36.17, -115.14), "San Diego": (32.72, -117.16),
    "San Antonio": (29.42, -98.49), "Austin": (30.27, -97.74), "Oklahoma City": (35.47, -97.52), "Omaha": (41.26, -95.93),
    "Milwaukee": (43.04, -87.91), "Baltimore": (39.29, -76.61), "Washington": (38.91, -77.04), "Raleigh": (35.78, -78.64),
    "Louisville": (38.25, -85.76), "Albuquerque": (35.08, -106.65), "Boise": (43.62, -116.20), "Buffalo": (42.89, -78.88),
    "Jacksonville": (30.33, -81.66), "Phoenix Valley": (33.45, -112.07),
}

# code, name, category, units per pallet, kg per unit, production cost USD per pallet, relative popularity, shelf life (weeks)
SKUS = [
    ("STILL15", "Still water 1.5L", "Water", 672, 1.55, 88, 1.25, 52),
    ("SPARK10", "Sparkling water 1L", "Water", 840, 1.10, 104, 0.85, 52),
    ("COLA33", "Cola 33cl can", "Soda", 2200, 0.36, 175, 1.50, 26),
    ("TEA50", "Iced tea 50cl", "Soda", 1100, 0.55, 210, 0.80, 20),
    ("JUICE10", "Orange juice 1L", "Juice", 700, 1.08, 255, 0.65, 12),
    ("ENER25", "Energy drink 25cl", "Energy", 2800, 0.28, 340, 0.45, 30),
]
# code, city, weekly capacity (pallets), cost index, items it can make
PLANTS = [
    ("PL-COL", "Columbus", 1500, 0.95, ["STILL15", "SPARK10", "COLA33", "TEA50", "ENER25"]),
    ("PL-DAL", "Dallas", 1300, 0.92, ["STILL15", "SPARK10", "COLA33", "TEA50", "JUICE10"]),
    ("PL-SAC", "Sacramento", 1100, 1.08, ["STILL15", "SPARK10", "TEA50", "JUICE10"]),
]
# code, city, fixed cost USD per year, weekly throughput (pallets), handling USD per pallet
DCS = [
    ("DC-ATL", "Atlanta", 900_000, 1400, 8.6),
    ("DC-CHI", "Chicago", 980_000, 1500, 9.2),
    ("DC-EWR", "Newark", 1_200_000, 1600, 10.4),
    ("DC-DFW", "Dallas", 800_000, 1200, 7.8),
    ("DC-LAX", "Los Angeles", 1_150_000, 1500, 10.0),
    ("DC-SEA", "Seattle", 850_000, 1000, 9.4),
]
# code, city, relative size (metro areas)
MARKETS = [
    ("MK-NYC", "New York", 1.50), ("MK-LAX", "Los Angeles", 1.40), ("MK-CHI", "Chicago", 1.10), ("MK-HOU", "Houston", 1.00),
    ("MK-PHX", "Phoenix", 0.80), ("MK-PHL", "Philadelphia", 0.80), ("MK-ATL", "Atlanta", 0.90), ("MK-MIA", "Miami", 0.85),
    ("MK-SEA", "Seattle", 0.70), ("MK-DEN", "Denver", 0.65), ("MK-BOS", "Boston", 0.70), ("MK-MSP", "Minneapolis", 0.60),
    ("MK-DTW", "Detroit", 0.60), ("MK-SFO", "San Francisco", 0.80),
]
# weekly demand shape over the 12 planning weeks (a summer peak for soft drinks)
# (the demand planning team's seasonal profile; it reaches the models through the ERP extract, not through this constant)
SEASON = np.array([0.88, 0.90, 0.95, 1.00, 1.08, 1.18, 1.22, 1.15, 1.05, 0.97, 0.92, 0.90])
BASE_WEEKLY_PALLETS = 30.0


ROAD_FACTOR = 1.15      # road miles run about 15% longer than the straight line (fitted to 16 known US city pairs, see docs/DATA_AND_ASSUMPTIONS.md)


def miles_between(a, b):
    """Estimated road miles between two cities: great-circle distance times a road factor, in whole miles."""
    (la1, lo1), (la2, lo2) = CITY[a], CITY[b]
    la1, lo1, la2, lo2 = map(radians, (la1, lo1, la2, lo2))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return round(2 * 3958.8 * asin(sqrt(h)) * ROAD_FACTOR)


@dataclass(frozen=True)
class Terms:
    """Every dial the models react to. Frozen: a scenario is a new Terms made with `with_(...)`."""
    demand_scale: float = 1.0               # multiplies all demand
    service_level: float = 0.95             # target cycle service level, one tailed
    rate_per_pallet_mile: float = 0.100     # USD to move one pallet one mile (about $2.60 a truckload mile over 26 pallets: 2026 linehaul of $2.25-2.50 plus a fuel allowance)
    co2_per_pallet_mile: float = 0.100      # kg CO2 per pallet-mile
    dc_fixed_scale: float = 1.0             # multiplies every DC's yearly fixed cost
    setup_cost: float = 2400.0              # USD per production run
    holding_rate_year: float = 0.22         # yearly cost of holding stock as a share of its value (capital, storage, insurance, obsolescence)
    lead_time_by_dc: tuple = ()             # ((dc code, mean weeks, spread weeks), ...) measured from goods receipts
    lead_time_scale: float = 1.0            # 1.5 = every delivery takes 50% longer than measured
    weeks_per_year: int = 52
    max_utilisation: float = 0.90           # planning rule: no site above this share of capacity in the peak week
    max_delivery_miles: float = 1100.0      # service rule: a market is served from a DC within this distance (two-day ground delivery)
    cover_share_of_shelf_life: float = 0.5  # stock may sit at most this share of an item's shelf life (retailers want half the life left)
    ignore_lead_time_risk: bool = False     # True = size stock on demand variability only

    def with_(self, **changes):
        return replace(self, **changes)

    def lead_time(self, dc):
        """(mean weeks, spread weeks) for deliveries into this DC."""
        mean, sd = {d: (m, v) for d, m, v in self.lead_time_by_dc}[dc]
        return mean * self.lead_time_scale, sd * self.lead_time_scale


@dataclass
class Company:
    skus: pd.DataFrame        # code, name, category, units_pallet, kg_unit, cost_pallet, shelf_life_weeks
    plants: pd.DataFrame      # code, city, capacity, cost_index, items
    dcs: pd.DataFrame         # code, city, fixed_year, capacity, handling
    markets: pd.DataFrame     # code, city, weight
    demand: pd.DataFrame      # market, sku, mu, sigma  (weekly pallets)
    mi_in: pd.DataFrame       # rows plants, columns DCs
    mi_out: pd.DataFrame      # rows DCs, columns markets
    terms: Terms = field(default_factory=Terms)
    season: np.ndarray = field(default_factory=lambda: SEASON / SEASON.mean())   # weekly demand index over the planning weeks, average 1.0

    @property
    def peak(self):
        """The busiest planning week is this many times the average week."""
        return float(self.season.max())

    def hold_week(self, sku, terms=None):
        """Dollars to keep one pallet of this item in stock for a week: yearly holding rate times the item's value.
        Pass the scenario's terms; the company's own terms are only the default."""
        t = terms or self.terms
        return t.holding_rate_year * float(self.skus.set_index("code").loc[sku, "cost_pallet"]) / t.weeks_per_year

    def max_cover_weeks(self, sku, terms=None):
        """Longest stock may sit before it is too old to ship, in whole weeks (at least one)."""
        t = terms or self.terms
        shelf = float(self.skus.set_index("code").loc[sku, "shelf_life_weeks"])
        return max(1, int(shelf * t.cover_share_of_shelf_life))

    def codes(self, which):
        return list(getattr(self, which)["code"])

    def city(self, code):
        for t in (self.plants, self.dcs, self.markets):
            hit = t.loc[t["code"] == code, "city"]
            if len(hit):
                return hit.iloc[0]
        raise KeyError(code)

    def can_make(self, plant):
        return set(self.plants.set_index("code").loc[plant, "items"].split("|"))


@dataclass
class WorldSpec:
    """Everything that defines a fictional company. The default is Tidewell; synthetic.py builds others for the robustness test."""
    skus: list
    plants: list
    dcs: list
    markets: list
    season: np.ndarray
    seed: int = SEED
    base_weekly_pallets: float = BASE_WEEKLY_PALLETS
    cv_range: tuple = (0.15, 0.30)               # weekly demand spread as a share of the mean
    terms: Terms = field(default_factory=Terms)


def default_spec():
    return WorldSpec(SKUS, PLANTS, DCS, MARKETS, SEASON)


def ground_truth(spec=None):
    """The fictional company exactly as its spec defines it. Used to generate the simulated extracts and, in the checks, to prove
    the ETL recovered it."""
    spec = spec or default_spec()
    rng = np.random.default_rng(spec.seed)
    skus = pd.DataFrame(spec.skus, columns=["code", "name", "category", "units_pallet", "kg_unit", "cost_pallet", "popularity", "shelf_life_weeks"])
    plants = pd.DataFrame([(c, city, cap, idx, "|".join(items)) for c, city, cap, idx, items in spec.plants],
                          columns=["code", "city", "capacity", "cost_index", "items"])
    dcs = pd.DataFrame(spec.dcs, columns=["code", "city", "fixed_year", "capacity", "handling"])
    markets = pd.DataFrame(spec.markets, columns=["code", "city", "weight"])
    rows = []
    for m in markets.itertuples():
        for s in skus.itertuples():
            mu = spec.base_weekly_pallets * m.weight * s.popularity * float(rng.uniform(0.85, 1.15))
            rows.append((m.code, s.code, round(mu, 1), round(mu * float(rng.uniform(*spec.cv_range)), 1)))
    demand = pd.DataFrame(rows, columns=["market", "sku", "mu", "sigma"])
    mi_in = pd.DataFrame({d.code: {p.code: miles_between(p.city, d.city) for p in plants.itertuples()} for d in dcs.itertuples()})
    mi_out = pd.DataFrame({m.code: {d.code: miles_between(d.city, m.city) for d in dcs.itertuples()} for m in markets.itertuples()})
    season = np.asarray(spec.season, dtype=float)
    return Company(skus.drop(columns="popularity"), plants, dcs, markets, demand, mi_in, mi_out, spec.terms, season / season.mean())
