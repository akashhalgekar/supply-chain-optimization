# Idea log: what was tried, kept and dropped

The companion list of fixes for realism is in [AUDIT.md](AUDIT.md).

Each idea was tested before being kept. "Kept" means it changed an answer, caught a problem, or gave a decision-maker something a bare
optimisation would not.

## Kept

| Idea | Test | Result |
| --- | --- | --- |
| Check capacity against the **peak** week, with a 90% margin | The first version used average weekly capacity. One plant came out at 99% of capacity on average, which made the 12-week production plan impossible in summer. | Fixed in the network model. Production planning now raises an error if a plant cannot make the plan. |
| Safety stock counts late deliveries as well as demand swings | Lead time and spread measured per DC from WMS receipts. Checked it is never below the demand-only figure. | 57% of the stock exists because of late deliveries. |
| Fill rate next to service level | Checked fill rate is never below the service level. | 95% cycle service is about 99.3% fill rate. |
| Savings against a reference case | Reference case = all DCs open, every item made weekly. Checked the steps add up. | 3.7% saved against the reference case. |
| Cost every DC set on the whole chain, with next-day coverage beside cost | Compared with the network model's own pick. | Same set wins on cost. Keeping all six DCs costs 0.4% more and raises next-day coverage from 68% to 80%, which is the real decision. |
| Stress tests | Nine scenarios. Checked that losing a single-source plant is reported infeasible. | Four scenarios the network cannot survive. |
| Which input moves cost most | Each input moved 20% (service level 2 points). | Demand 34%, transport rate 11.0%, DC fixed cost 6.0%, everything else under 1%. |
| Cost to serve by market | Logistics cost only, so markets compare fairly across product mix. | 3.9x spread, driven by the plant-to-DC leg and small-DC fixed cost. |
| Realism fixes found by audit: holding cost as a share of value, shelf life, delivery radius, lead time by DC, seasonal profile from the ERP | Each one is listed in AUDIT.md with its check. | A manager reading the project no longer finds the obvious mistakes. |
| Fast path for production planning | Textbook Wagner-Whitin when no plant week is overloaded, the capacity-aware solver otherwise. Checked both give the same cost when forced. | Same answer, far faster when capacity is loose. |
| ETL control totals and a 10% stop | Fed it a file with 30% duplicate lines. It refused to load. | Bad extracts cannot load quietly. |

## Dropped

| Idea | Why |
| --- | --- |
| Different service levels per item class (ABC/XYZ) | Needs class thresholds and service levels nobody has given. Making them up would produce a made-up policy. |
| Measuring demand correlation between markets | The simulated order history is independent by construction, so any correlation found would be an artefact. Worth doing with real data. |
| Machine-learning demand forecast | The simulated demand has no pattern to learn beyond the seasonal curve, so any accuracy figure would be fiction. |
| A "legacy policy" safety stock baseline | Needs a legacy policy number that has not been provided. |
| One combined optimisation of DCs and safety stock | Safety stock is not linear in the DC choice. Costing every DC set directly answers the same question with no approximation. |

## Corrections along the way

- A first draft of the executive summary claimed that fewer DCs mean less safety stock. The data did not support it (average stock cost was almost flat), so the claim was removed.
- A sensitivity run showed a holding-cost swing of exactly $0. That exposed a bug where scenario settings were ignored by the production plan. Fixed, and the swing is now non-zero.
- The same draft called late deliveries "as much" as demand swings; they are 65% of the stock, so the wording now follows the number.
