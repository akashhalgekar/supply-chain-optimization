# Audit: mistakes a supply chain manager would laugh at, and what was done

The project was read the way an experienced supply chain manager would read it. Each finding below was real, and each was fixed and checked.

| # | The mistake | Why a manager would laugh | The fix | Check in `verify.py` |
| --- | --- | --- | --- | --- |
| 1 | Holding cost was a flat $3.50 per pallet-week for every item | For a $88 pallet of water that is about 200% of its value a year. Real holding rates are 15 to 30%. | Holding cost is now 22% a year of each item's value | the lot-sizing and safety stock tests use per-item holding cost; a sensitivity run on the rate now moves cost |
| 2 | No shelf life | The plan would hold orange juice for ten weeks | Each item has a shelf life; stock may not outlive half of it | "no stock sits longer than the shelf-life limit" |
| 3 | Any DC could serve any market (Seattle from Atlanta, for example) | A truck cannot deliver across the country inside a service promise | A 1,100-mile delivery radius (two-day ground), with next-day coverage (600 miles) reported | "every delivery is within the service radius" |
| 4 | Every DC had the same 2-week lead time | A DC next to the plant waits as long as one 2,000 miles away | Lead times measured per DC from goods receipts: order processing plus driving time | "a DC farther from the plants waits longer" |
| 5 | Capacity checked on the average week | A network that is full on average cannot make summer peak | Capacity checked against the peak week with a 90% margin | "no plant above the planning limit in the peak week" |
| 6 | Safety stock counted demand swings only | Late trucks empty a DC just as surely as a demand spike | The late-delivery term is included; it is 57% of the stock | "never below demand-only" |
| 7 | "95% service" reported as if it were the share of units delivered | Cycle service level and fill rate are different numbers | Both reported; fill rate is 99.3% | "fill rate at or above the service level" |
| 8 | A savings figure with no yardstick | "Savings against what?" | A stated reference case (all DCs open, every item made weekly), flagged as a yardstick, not a measured state | "savings waterfall adds up" |
| 9 | Seasonal curve built into the code | The planners' forecast does not come from a constant | The profile now arrives through the ERP extract like any other input | "seasonal profile from the demand planners" |
| 10 | Inventory cost counted only safety stock | Cycle stock costs money too | DC stock cost includes average cycle stock | stock cost reconciles in the scorecard |
| 11 | European geography, kilometres and a non-US currency | The audience is American | US cities, road miles, dollars | distances recovered exactly by the ETL |
| 12 | A scenario changed the holding rate and cost did not move | A silent bug: the plan used the company's holding rate, not the scenario's | Scenario settings now flow into every calculation | the holding-rate sensitivity is no longer zero |
| 13 | The plan quietly closed a big market's DC | Closing Chicago while it is a top market deserves a flag, not a footnote | The summary names every market that loses its own DC, shows next-day coverage beside cost, and recommends the service option when it costs under 1% more | text generated in the executive summary |
| 14 | Freight at $0.07 a pallet-mile ($1.80 a truck-mile) | Well below the 2026 market of $2.25 to $2.50 a mile before fuel | $0.10 a pallet-mile, with sources in `DATA_AND_ASSUMPTIONS.md` | "freight rate is inside the 2026 truckload range" |
| 15 | Road distance was straight line times 1.2 | Overstated real driving distance by about 5% | Fitted to 16 known driving distances: factor 1.15, mean error 5% | "estimated road miles fit 16 known driving distances" |
| 16 | Order history ran past today's date | A recruiter sees orders dated in the future | History now ends in August 2026 | dates recovered by the ETL |
| 17 | A tolerance in the capacity check was tighter than the solver's own accuracy | Found by the robustness test: 4 of 10 other companies tripped it by 0.00001 of a pallet | Tolerance set to 0.001 pallet and stated | the robustness run |

## Still open (stated, not hidden)

- The data is simulated, so there is no real service history, forecast error or freight bill to calibrate against.
- Freight is linear in pallet-miles. A real model rounds to truckloads and uses lane rates.
- Plant capacity is in pallets per week, not line hours, and every changeover costs the same.
- One service level for every item; no differentiation by volume or margin.
- Demand across markets is assumed independent when pooled.
