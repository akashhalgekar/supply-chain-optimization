# Tidewell supply chain optimiser: one page

**What it is.** An end-to-end analytics project for a fictional US drinks company: simulated ERP, WMS and TMS data, an ETL, three optimisation models (network design, Wagner-Whitin production planning, lead-time-aware safety stock), a decision layer, a dashboard and automated checks that run on Tidewell and on ten other synthetic companies. Built with an AI assistant, then audited as a supply chain manager would audit it.

**The question.** Which distribution centres should Tidewell run, when should each plant produce, and how much safety stock should each DC hold, so cost is lowest at a 95% service level?

![flowchart](../charts/01_end_to_end_flowchart.png)

## Results

| | |
| --- | --- |
| Cost of the lowest-cost network | $650,458 a week ($33.8M a year), $311 a pallet |
| Saving against a reference case (all DCs open, weekly production) | 3.7%: $25,272 a week, $1.31M a year |
| Production runs over 12 weeks | 168 become 39 |
| Safety stock | 1,088 pallets; in this simulated company 57% exists because deliveries arrive late (32% at half the assumed delivery-time spread, 77% at double) |
| The real decision | Closing Chicago is cheapest, but keeping all six DCs costs only 0.4% more and lifts next-day coverage from 68% to 80%. Recommendation: keep all six |
| Resilience | Demand can grow 40% before the network breaks; losing Columbus or Dallas leaves demand unmet |

## Why it can be trusted

- **Inputs:** every input is classed as simulated, benchmarked or assumed, with its source and its effect on the answer (`docs/DATA_AND_ASSUMPTIONS.md`). Freight rate, holding rate, trailer size and road distances were checked against 2026 benchmarks and known driving distances.
- **Validation:** the ETL recovers the company's true figures from the messy files exactly; the production plan matches textbook Wagner-Whitin where capacity does not bind; brute force confirms the network choice.
- **Robustness:** the same pipeline and checks pass on 10 other synthetic companies of different size, geography and cost structure (`docs/ROBUSTNESS.md`).
- **Honesty:** the exact DC set moves with the freight rate, delivery radius and road factor, and the docs say so. The saving is modest and the project explains why.

## Models used in the backend

| Question | Model | Where |
| --- | --- | --- |
| Which warehouses to run, and which plant ships what to which market | Mixed integer linear program (facility location), solved with PuLP and the CBC solver | `tidewell/network.py` |
| When each plant should produce | Wagner-Whitin lot sizing (dynamic programming), plus a capacity-aware mixed integer program when plant capacity binds | `tidewell/lotsizing.py` |
| How much safety stock each warehouse holds | Safety stock formula with demand and delivery-time variability (normal distribution), and fill rate from the normal loss function | `tidewell/safetystock.py` |
| Which option is best, and how sure we can be | Brute force over every warehouse combination, scenario reruns and one-at-a-time sensitivity | `tidewell/analytics.py` |

The data side is a pandas ETL, and the dashboard is served by FastAPI. No machine learning or language model runs in the backend: it is classical operations research and statistics.

**Read next:** `docs/PROJECT_STORY.md`, `docs/EXECUTIVE_SUMMARY.md`, `docs/AUDIT.md`.
