# How Tidewell works, in plain words

![flowchart](../charts/01_end_to_end_flowchart.png)

Tidewell is a fictional American drinks company: 6 products, 3 plants (Columbus, Dallas, Sacramento), 6 possible distribution centres
(DCs: Atlanta, Chicago, Newark, Dallas, Los Angeles, Seattle), 14 metro markets, about 2,089 pallets a week. The question is the one a supply chain
consultant gets asked: **which DCs should we run, when should each plant make each product, and how much safety stock should each DC hold, so total
cost is as low as possible at the service level we promise?**

The answer comes in five stages. Each stage hands a clean result to the next.

## Stage 1. Company systems (ERP, WMS, TMS)

Nobody types the model's inputs in by hand. They come from three systems.

| System | What it is | What the model takes from it |
| --- | --- | --- |
| ERP | the order and finance system | every sales order line, units per pallet, shelf life, plant capacity and cost, the demand planners' seasonal profile, cost of one production setup, the yearly cost of holding stock as a share of its value |
| WMS | the warehouse system | pallets each DC can handle a day, handling cost, fixed yearly cost, goods receipts (when stock was ordered and when it arrived) |
| TMS | the transport system | distance of every lane, carrier price per pallet-mile, CO2 per pallet-mile |

Real extracts are messy, and these are too, on purpose: duplicate order lines, cancelled orders, lines with a missing item or quantity, dates in two formats,
"Chicago" typed four ways, quantities in single units instead of pallets, a few distances quoted in kilometres, DC capacity per day instead of per week.

> The files are simulated, because Tidewell is fictional. `verify.py` proves the ETL recovers the company's true figures from them exactly, so the path from
> messy file to model input is real even though the data is not.

## Stage 2. ETL: Extract, Transform, Load

1. **Extract.** Read each raw file as delivered.
2. **Clean.** Remove 132 duplicate lines, 176 cancelled lines and 6 broken lines out of 9,128. One spelling per city, one date format. Every rule is counted,
   so nothing disappears silently.
3. **Transform.** Units become pallets, kilometres become miles, per-day capacity becomes per-week. 8,814 clean order lines become weekly demand per market and
   item, and from that a **mean** and a **spread** (standard deviation) for each of the 84 market-item pairs. Delivery lead times are measured per DC from goods receipts.
4. **Load.** Write clean tables and a data quality log (`output/01_data_quality_log.csv`).

The load also checks its own arithmetic: units extracted minus units removed must equal units rolled up into weekly demand, and it stops if cleaning
removes more than 10% of order lines.

## Stage 3. The clean data store

**Facts** are measurements (weekly demand, demand mean and spread, lead times, the seasonal profile). **Descriptions** say what things are (items, plants, DCs,
markets, distances, costs). The models read only from here, never a raw file. A real ERP export could replace the simulated one without touching the models.

## Stage 4. Three models and one hand-off

**Model 1, network design** (in the middle of the chart because the others depend on it). Decides which DCs to open and how many pallets of each item flow plant,
then DC, then market. Opening a DC costs a fixed amount a year, so the model trades *the fixed cost of more DCs* against *the transport cost of serving markets from
farther away*. Three rules keep it realistic:
- **Peak week.** Capacity is checked against the busiest week, with a 90% safety margin, so a network cannot look fine on average and be impossible in July.
- **Delivery radius.** A market is served from a DC within 1,100 road miles (two-day ground delivery).
- **Single sourcing.** An item a plant cannot make is never planned there.

It hands on two things: to Model 2 how many pallets each plant must make per item, and to Model 3 which DCs serve which markets.

**Model 2, production planning (Wagner-Whitin).** Takes the volume a plant must make and decides in which weeks to run the line and how much. A run costs a setup.
Making a big batch less often saves setups but leaves stock in the warehouse, and stock costs money: 22% of its value a year (so a pallet of energy drink costs more to hold
than a pallet of water). Beverages also expire, so a batch may only cover as many weeks of demand as half the item's shelf life allows. Wagner-Whitin finds the
cheapest balance for one item. Plants have weekly capacity, so the plan solves all of a plant's items together as an optimisation problem; when capacity does not
bind it matches Wagner-Whitin exactly.

**Model 3, safety stock.** For each DC and item it adds up the demand of the markets the DC serves, and holds enough stock to cover two risks while waiting for a delivery:
demand running high, and the delivery arriving late.
`safety stock = z x square root of (lead time x demand spread squared + average demand squared x lead-time spread squared)`.
Lead time and its spread are measured per DC from goods receipts: a DC far from the plants waits longer. z comes from the service level (95% gives 1.64).

## Stage 5. Where it ends up

The results are added into a **scorecard**: cost a week, cost per pallet, CO2, service level, fill rate and the share of volume delivered within 600 miles (next day by truck).
The dashboard re-runs the whole chain when you move a dial.

## What the base case says

| Question | Answer | What drives it |
| --- | --- | --- |
| Which DCs? | Cost alone says close Chicago. Service says keep all six. | DC fixed cost against transport cost, inside the 1,100-mile delivery radius |
| Production? | 168 weekly runs become 39 | setup cost ($2,400) against holding cost (22% of value a year), shelf life and plant capacity |
| Safety stock? | 1,088 pallets at 95% service (464 if late deliveries were ignored) | delivery reliability and demand swings |
| Total | $650,458 a week ($33.8M a year), $311 a pallet, 9,448 t CO2 a year | production is 53% of it |

Things worth a second look before trusting them:
- **Chicago is a big market and the cheapest network closes its DC.** It is then served from Atlanta (677 miles) and Dallas (925 miles). Keeping all six DCs costs $2,415 a week more
  (0.4%) but raises next-day coverage from 68% to 80%, so the summary recommends keeping all six unless that coverage is worth less than 0.4% of cost.
- **Late deliveries drive most of the safety stock in this simulated company.** 57% of it exists because of them. That share depends on the delivery-time spread assumed for the simulated DCs: 32% at half that spread, 77% at double.
- **The exact DC set depends on assumptions.** A 900-mile radius keeps all six DCs, a 1,300-mile radius closes Atlanta and Seattle, and a higher freight rate keeps all six. The cost gap between the options is small, which is why service, not cost, decides it (`docs/DATA_AND_ASSUMPTIONS.md`).
- **There is little slack.** Demand can grow about 40% before the network cannot serve it. Losing Columbus or Dallas leaves demand unmet, and ENER25 can only be made in Columbus.
- **A next-day promise (600 miles) cannot be met** from these six sites.

## What goes beyond the basic three models

| Question | Answer in this project |
| --- | --- |
| Savings versus what? | 3.7% against a reference case of all DCs open and every item made weekly |
| Did we pick DCs on the right basis? | All 6 workable DC sets were costed on the whole chain, with next-day coverage shown beside the cost |
| What breaks it? | Nine stress tests, four of which the network cannot survive |
| Where to spend measurement effort? | Demand, transport rate and DC fixed cost move cost most. Service level and lead times move it under 1%. |
| How sensitive are the assumptions? | Freight rate, delivery radius and road factor can change which DCs are chosen; capacity margin and shelf-life cover barely move cost (`output/15_assumption_sensitivity.csv`) |
| What does each market cost to serve? | $68 a pallet (Houston) to $262 (Seattle) |

`docs/EXECUTIVE_SUMMARY.md` puts this on one page for a decision-maker. `docs/AUDIT.md` lists the mistakes a supply chain manager would spot and how each was fixed.
`docs/IDEA_LOG.md` records what was tried and why it was kept or dropped.

## How we know it is right (`python verify.py` and `python -m tidewell.robustness`)

1. **The ETL recovers the truth.** Items, plants, DCs, distances, the seasonal profile, the demand mean and spread of all 84 market-item pairs, and the lead time of every DC match.
2. **The models agree on both.** Same DCs and same weekly cost on the recovered data as on the true company.
3. **The plan is feasible.** Every demand is met exactly, flows balance at each DC, every delivery is inside the radius, no site is above its limit in the peak week,
   no production week exceeds plant capacity, and no stock outlives its shelf-life limit.
4. **Production versus textbook.** The capacity-aware plan costs $128,199 against $108,783 for textbook Wagner-Whitin, which would overload Columbus, Dallas and Sacramento
   in several weeks. The difference is the price of a plan the plants can actually run.
5. **Safety stock behaves.** Never below the demand-only figure, fill rate above the service level, more stock for a higher service level.
6. **Brute force agrees.** The network model's DC choice is the best of all workable sets on network cost.
7. **The ETL refuses a corrupted extract** (30% duplicate lines).
8. **The inputs match the outside world.** Road distances are compared with 16 known driving distances (mean error 5%), the freight rate with the 2026 truckload range, and the holding rate with the 20 to 30% range.
9. **The checks have teeth.** A mislabelled distance unit, a delivery plan that ignores a tighter radius and a plan checked against halved capacity must all make the checks fail.
10. **It holds up on other data.** The same checks pass on ten other synthetic companies (`docs/ROBUSTNESS.md`).
11. **The documents match the run.** Every headline number in the README, story, interview notes and this page is compared with the live result, and old wording fails the check.

## Known limits

- The data is simulated. Real ERP, WMS and TMS data would be messier.
- Demand is a weekly average shaped by the planners' seasonal curve, not a forecast.
- One service level applies to every item. The 90% capacity limit, the 1,100-mile radius, the 22% holding rate and the shelf-life rule are planning assumptions.
- Distances are estimated road miles (straight line times 1.15, fitted to 16 known driving distances). Freight is linear in pallet-miles: no truckload rounding.
- Plant capacity is in pallets, not line hours, and every changeover costs the same.
- Fill rate assumes one week of demand is ordered per replenishment cycle. Markets are assumed independent when demand is pooled.
