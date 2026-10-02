# Data and assumptions: what goes in, where it comes from, how much it matters

A recruiter's first question about any analytics project is "what data is this?". This page answers it for every input.

**Short answer: all company data is simulated, because Tidewell is fictional. The simulated numbers are anchored to real-world benchmarks where benchmarks exist, and every
assumption is listed with how much it moves the answer.** Nothing was taken from a real company.

## Three kinds of input

| Kind | Meaning | Example |
| --- | --- | --- |
| **Simulated data** | Invented for Tidewell, generated as messy ERP, WMS and TMS files, then cleaned by the ETL | sales orders, plant and DC capacities, lead times |
| **Benchmarked assumption** | A policy or market number set from published ranges | freight rate, holding rate, trailer size, road distances |
| **Planning assumption** | A rule a planner chooses, with no single right value | delivery radius, 90% capacity margin, shelf-life cover |

## Simulated data (the files in `data/raw/`)

| File | Rows | What it holds | How it was made | Check |
| --- | --- | --- | --- | --- |
| `erp_sales_orders.csv` | 9,128 | 52 weeks of order lines (Sep 2025 to Aug 2026) in single units, with duplicates, cancelled and broken lines, mixed date formats and city spellings | Weekly demand per market and item drawn so its mean and spread equal the company's true figures exactly, split into 1 to 3 lines a week | The ETL recovers all 84 means and spreads to within 0.05 pallets |
| `erp_item_master.csv` | 6 | units per pallet, weight, cost per pallet, shelf life | Invented, costs from $88 (still water) to $340 (energy drink) | Compared with item type and shelf-life ranges below |
| `erp_work_centres.csv` | 3 | plant capacity (pallets a week), cost index, items each plant can make | Invented. ENER25 can only be made in Columbus | Recovered exactly |
| `erp_customers.csv` | 14 | US metro areas | Real city names, invented relative sizes | Recovered exactly |
| `erp_seasonal_profile.csv` | 12 | the demand planners' weekly index (summer peak) | Invented smooth curve | Recovered exactly |
| `erp_finance_params.csv` | 2 | setup cost per run ($2,400), holding rate (22% a year) | Setup cost invented; holding rate benchmarked | Within the benchmark range |
| `wms_sites.csv` | 6 | DC throughput per day, handling cost, fixed yearly cost | Invented. Fixed cost $0.8M to $1.2M a year | Recovered exactly |
| `wms_goods_receipts.csv` | 240 | order and arrival dates, so lead times | Order processing (5 days) plus driving time at 500 miles a day, plus random spread per DC | Recovered to within 0.03 weeks; a DC farther from the plants waits longer |
| `tms_lanes.csv` | 102 | distance of every plant-to-DC and DC-to-market lane | Straight-line distance times a road factor; a few lanes quoted in km | Distances recovered exactly; road factor fitted to real driving distances |
| `tms_rate_card.csv` | 2 | freight rate and CO2 per pallet-mile | Rate benchmarked | See below |

Why simulate, and why messy? Real company data is confidential, and a clean file would hide the work the ETL does. Messiness is added on purpose so the cleaning rules have something to catch.
Because the true figures are known, `verify.py` can prove the ETL recovers them exactly. That is something real data cannot offer.

## Benchmarked assumptions

| Input | Value used | Benchmark | Source |
| --- | --- | --- | --- |
| Freight rate | $0.10 per pallet-mile (about $2.60 a truckload mile over 26 pallets) | 2026 dry van linehaul about $2.25 to $2.50 a mile before fuel | [Fleet Equipment, July 2026](https://www.fleetequipmentmag.com/july-2026-dry-van-spot-rates/); [Trucking Dive on DAT and U.S. Bank rates](https://www.truckingdive.com/news/trucking-spot-contract-rates-us-bank-dat-2026-spread/816351/) |
| Pallets per truck | 26 | A 53-foot trailer holds 26 standard 48x40 pallets in a straight load, 28 to 30 pinwheeled | [Cowtown Express](https://cowtownexpress.com/blog/how-many-pallets-fit-on-a-53-foot-trailer-and-how-to-optimize-your-dry-van-space) |
| Holding rate | 22% of value a year | Inventory carrying cost is typically 20 to 30% of value, shelf-stable packaged goods near 20 to 25% | [Wikipedia, Carrying cost](https://en.wikipedia.org/wiki/Carrying_cost); [eightx, by vertical](https://eightx.co/blog/average-inventory-carrying-cost-by-vertical) |
| Road distance | straight line times 1.15 | Fitted to 16 known US city pairs: mean error 5.0%, bias +0.5%. The earlier factor of 1.2 overstated by about 5% | `data/reference/road_distances.csv`. Four of the 16 were spot-checked online (Atlanta to Chicago, Los Angeles to Seattle, Dallas to Los Angeles, New York to Chicago): three agree, and Dallas to Los Angeles ranges from 1,230 to 1,440 miles by route. The other 12 are approximate values and not independently checked, so treat the fit as indicative |
| Driving per day | 500 miles | US hours-of-service rules allow 11 hours of driving per shift; 500 miles leaves room for loading and breaks | FMCSA hours-of-service rules |
| Soda and energy drink shelf life | 26 and 30 weeks | Unopened soda and energy drinks last about 6 to 9 months | [Chowhound](https://www.chowhound.com/2205425/average-shelf-life-energy-drinks/) (a weak source; treat as indicative) |

**Not benchmarked, so honestly assumptions:** shelf lives of still water (52 weeks), sparkling water (52), iced tea (20) and juice (12 weeks). Chilled orange juice in a real
supply chain lasts only 2 to 3 weeks, so this item stands for a longer-life, ambient juice.

## Planning assumptions

| Input | Value | Why |
| --- | --- | --- |
| Service level | 95% cycle service level | A common default for packaged goods |
| Capacity margin | no site above 90% of capacity in the peak week | Planners never plan to 100% |
| Delivery radius | 1,100 road miles | Two-day ground delivery |
| Next-day reach | 600 miles | One driving day, with margin |
| Shelf-life cover | stock may sit at most half an item's shelf life | Retailers want about half the life left |
| Weeks a year | 52 | Calendar year |
| Plant capacity unit | pallets a week | Line hours are not modelled |

## How much do the inputs matter?

Each input moved up and down 20% (service level by 2 points), from `output/11_input_sensitivity.csv`:

| Input | Swing in weekly cost |
| --- | --- |
| Demand | 34.0% |
| Transport rate per mile | 11.0% |
| DC fixed cost | 6.0% |
| Production setup cost | 0.5% |
| Holding cost rate | 0.3% |
| Lead times | 0.0% |
| Service level (2 points) | 0.0% |

The planning assumptions were moved across plausible ranges (`output/15_assumption_sensitivity.csv`):

| Assumption | Range tried | Effect on weekly cost | Does the DC choice change? |
| --- | --- | --- | --- |
| Freight rate | $0.085 to $0.115 a pallet-mile | -4.2% to +4.2% | yes: at $0.115 all six DCs are kept |
| Delivery radius | 900 to 1,300 miles | +1.2% to -2.6% | yes: 900 keeps all six, 1,300 closes Atlanta and Seattle |
| Road factor | 1.10 to 1.20 | -2.4% to +1.2% | yes at 1.10: Seattle closes |
| Holding rate | 15% to 30% | -0.2% to +0.2% | no |
| Shelf-life cover share | 40% to 60% | under 0.1% | no |
| Capacity margin | 85% to 95% | none | no |

**What this means.** The size of the cost (about $650,000 a week), the finding that production is 53% of it and that late deliveries drive 57% of safety stock hold across all of these.
The exact set of open DCs does not: it moves with the freight rate, delivery radius and road factor, and the cost gap between the options is small (0.4% between the two best).
That is why the project recommends the service-based choice instead of claiming the cost-optimal set is the single right answer.

## What real data would replace

Sales orders, plant and DC capacities, freight invoices, goods receipts and the item master would come from the company's ERP, WMS and TMS. Only `data/raw/` changes: the ETL, the models
and the checks are written against the clean tables, not the simulation. The first things to calibrate would be the freight rate, lead times and the holding rate.

## Also tested on other synthetic data

`docs/ROBUSTNESS.md`: ten other fictional companies, with different sizes, geographies, costs and messiness, run through the whole pipeline and every check.
