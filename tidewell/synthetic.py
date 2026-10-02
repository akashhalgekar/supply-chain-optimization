"""Other fictional companies, to test that the pipeline and models hold up beyond Tidewell.

random_spec(seed) builds a different American drinks company each time: a different number of items, plants, DCs and markets, different
cities, costs, shelf lives, seasonal curve, demand variability and cost terms. Capacities are sized from demand, and the company is made
feasible before it is returned, so any failure in the robustness test points at the code, not at an impossible company.

Nothing here touches the Tidewell numbers: it only produces WorldSpec objects.
"""
import numpy as np
from dataclasses import replace
from .company import WorldSpec, Terms, ground_truth, miles_between, CITY
from . import network

# name, category, units per pallet, kg per unit, cost per pallet, popularity, shelf life in weeks (each a (low, high) range)
ITEM_POOL = [
    ("Still water", "Water", (600, 760), (1.4, 1.7), (80, 100), (1.0, 1.5), (40, 60)),
    ("Sparkling water", "Water", (800, 880), (1.0, 1.2), (95, 115), (0.6, 1.0), (40, 60)),
    ("Cola", "Soda", (2000, 2400), (0.33, 0.40), (160, 190), (1.2, 1.7), (22, 30)),
    ("Lemon-lime soda", "Soda", (2000, 2400), (0.33, 0.40), (150, 180), (0.7, 1.1), (22, 30)),
    ("Iced tea", "Tea", (1000, 1200), (0.50, 0.60), (195, 225), (0.6, 1.0), (16, 24)),
    ("Orange juice", "Juice", (650, 750), (1.0, 1.1), (235, 275), (0.5, 0.8), (8, 16)),
    ("Energy drink", "Energy", (2600, 3000), (0.25, 0.30), (320, 360), (0.3, 0.6), (24, 36)),
    ("Sports drink", "Sports", (1800, 2200), (0.50, 0.60), (170, 200), (0.5, 0.9), (20, 30)),
    ("Coconut water", "Water", (900, 1100), (0.50, 0.60), (280, 320), (0.3, 0.5), (20, 30)),
]
PLANT_CITIES = ["Columbus", "Dallas", "Sacramento", "Charlotte", "Indianapolis", "Kansas City", "Memphis", "Salt Lake City", "Atlanta",
                "Chicago", "Portland", "Nashville", "Pittsburgh", "Phoenix", "Houston"]
DC_CITIES = ["Atlanta", "Chicago", "Newark", "Dallas", "Los Angeles", "Seattle", "Denver", "Memphis", "Kansas City", "Indianapolis", "Columbus",
             "Houston", "Phoenix", "Salt Lake City", "Charlotte", "Nashville", "Baltimore", "Orlando", "Portland", "Las Vegas"]


def _split(rng, total, n, floor=0.15):
    """Split a total into n unequal parts, none smaller than floor / n of the total."""
    w = rng.dirichlet(np.ones(n)) * (1 - floor) + floor / n
    return total * w


def random_spec(seed):
    rng = np.random.default_rng(seed)
    n_items, n_plants, n_dcs, n_markets = int(rng.integers(4, 10)), int(rng.integers(2, 5)), int(rng.integers(4, 8)), int(rng.integers(10, 21))
    season = 1 + rng.uniform(0.05, 0.30) * np.sin(2 * np.pi * np.arange(12) / 12 + rng.uniform(0, 2 * np.pi)) + rng.normal(0, 0.02, 12)
    peak = float(np.max(season / season.mean()))
    terms = Terms(rate_per_pallet_mile=float(rng.uniform(0.08, 0.13)), setup_cost=float(rng.integers(1500, 5001)),
                  holding_rate_year=float(rng.uniform(0.15, 0.30)), service_level=float(rng.choice([0.90, 0.95, 0.98])),
                  max_delivery_miles=float(rng.choice([900, 1100, 1300])))

    pool = rng.choice(len(ITEM_POOL), size=n_items, replace=False)
    skus = []
    for i, j in enumerate(sorted(pool)):
        name, cat, upp, kg, cost, pop, shelf = ITEM_POOL[j]
        skus.append((f"{name[:3].upper()}{i:02d}", name, cat, int(rng.integers(upp[0], upp[1] + 1)), round(float(rng.uniform(*kg)), 2),
                     round(float(rng.uniform(*cost)), 2), round(float(rng.uniform(*pop)), 2), int(rng.integers(shelf[0], shelf[1] + 1))))

    dc_cities = list(rng.choice(DC_CITIES, size=n_dcs, replace=False))
    markets_pool = [c for c in CITY if c not in ("Phoenix Valley",)]
    covered = [c for c in markets_pool if min(miles_between(d, c) for d in dc_cities) <= terms.max_delivery_miles]
    n_markets = min(n_markets, len(covered))
    market_cities = list(rng.choice(covered, size=n_markets, replace=False))
    weights = np.round(rng.uniform(0.4, 1.6, n_markets), 2)
    base = float(rng.uniform(1500, 4500)) / (weights.sum() * sum(s[6] for s in skus))
    demand_total = base * weights.sum() * sum(s[6] for s in skus)

    plant_cities = list(rng.choice(PLANT_CITIES, size=n_plants, replace=False))
    plant_cap = _split(rng, demand_total * peak / terms.max_utilisation * rng.uniform(1.4, 2.2), n_plants)
    codes = [s[0] for s in skus]
    plants = []
    for p, city in enumerate(plant_cities):
        items = [c for c in codes if rng.random() < 0.75]
        plants.append([f"PL-{p:02d}", city, int(plant_cap[p]), round(float(rng.uniform(0.9, 1.1)), 2), items])
    for c in codes:                                           # every item must be makeable somewhere
        if not any(c in p[4] for p in plants):
            plants[int(rng.integers(0, n_plants))][4].append(c)
    plants = [(c, city, cap, idx, items) for c, city, cap, idx, items in plants]

    dc_cap = _split(rng, demand_total * peak / terms.max_utilisation * rng.uniform(1.8, 3.0), n_dcs)
    dc_cap = [max(5, int(c) // 5 * 5) for c in dc_cap]        # the WMS reports whole pallets per working day, so weekly capacity is a multiple of 5
    dcs = [(f"DC-{d:02d}", city, int(cap * rng.uniform(500, 800)), cap, round(float(rng.uniform(7, 11)), 1)) for d, (city, cap) in enumerate(zip(dc_cities, dc_cap))]
    markets = [(f"MK-{m:02d}", city, float(w)) for m, (city, w) in enumerate(zip(market_cities, weights))]
    cv = (0.10, 0.25) if rng.random() < 0.5 else (0.15, 0.30)
    return WorldSpec(skus, plants, dcs, markets, season, seed=seed, base_weekly_pallets=base, cv_range=cv, terms=terms)


def feasible_company(seed, attempts=6):
    """A random company that can serve its own demand. Capacity is widened a little each attempt if it cannot."""
    spec = random_spec(seed)
    for k in range(attempts):
        truth = ground_truth(spec)
        if network.design(truth, truth.terms).ok:
            return spec, truth, k
        spec = replace(spec, plants=[(c, city, int(cap * 1.3), idx, items) for c, city, cap, idx, items in spec.plants],
                       dcs=[(c, city, fx, int(cap * 1.3) // 5 * 5, h) for c, city, fx, cap, h in spec.dcs])
    raise RuntimeError(f"could not build a feasible company for seed {seed}")
