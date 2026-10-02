# The story of this project

*How to tell it to a recruiter, a hiring manager or an interviewer. Adapt the wording so it is true to you, and read `INTERVIEW_QA.md` so you can back up every sentence.*

## The 20-second version

> AI can write a supply chain model in an afternoon. It cannot tell you whether the model is believable. I built an end-to-end US beverage supply chain
> project with an AI assistant, then used supply chain judgement to audit it as a manager would, checked every input against real benchmarks, and tested the whole
> pipeline on ten other synthetic companies. The result is a decision recommendation, not just a model.

## Why this project exists

Recruiters keep hearing "I can use AI". Most candidates show a chatbot or a dashboard. This project shows something harder to fake: using AI to build a
real analytical pipeline, and knowing enough supply chain to catch where the AI's first answer was wrong.

The evidence is in the repo, not in a claim: `docs/AUDIT.md` lists what was wrong and how it was found, `docs/DATA_AND_ASSUMPTIONS.md` classes every input, `docs/ROBUSTNESS.md` shows the
pipeline holding up on other data, and `verify.py` runs the checks that prove the fixes hold.

## The business story

**Tidewell Beverages** (fictional) sells six drinks across 14 US metro areas. It makes them in three plants (Columbus, Dallas, Sacramento) and can run up to
six distribution centres (Atlanta, Chicago, Newark, Dallas, Los Angeles, Seattle). Freight, warehouses and production all cost money, and every choice affects the others.

The question: **which DCs should Tidewell run, when should each plant produce, and how much safety stock should each DC hold, so cost is lowest at a 95% service level?**

## How the project answers it (five stages)

![flowchart](../charts/01_end_to_end_flowchart.png)

1. **Company systems.** Orders and costs come from an ERP, warehouse data from a WMS, lanes and freight rates from a TMS. (Simulated, deliberately messy.)
2. **ETL.** Cleans duplicates, cancelled orders, mixed units and date formats, and refuses to load if the arithmetic does not reconcile.
3. **Clean data store.** The only thing the models read.
4. **Three models.** Network design (which DCs, which flows), production planning with Wagner-Whitin (when and how much to make), safety stock (how much buffer, counting late deliveries as well as demand swings).
5. **Decisions.** A scorecard, then savings against a reference case, stress tests, input sensitivity and cost to serve by market.

## What it found

| Finding | Number |
| --- | --- |
| Cost of the lowest-cost network (Atlanta, Newark, Dallas, Los Angeles, Seattle) | $650,458 a week, $33.8M a year, $311 a pallet |
| Saving against a reference case (all DCs open, weekly production) | 3.7%: $25,272 a week, $1.31M a year |
| Production runs over 12 weeks | 168 become 39 |
| Safety stock | 1,088 pallets; 464 if late deliveries were ignored, so 57% of the stock exists because trucks arrive late |
| Service level versus fill rate | 95% cycle service level is about 99.3% of units served from stock |
| The real decision | Closing Chicago is cheapest, but keeping all six DCs costs only 0.4% more and raises next-day coverage from 68% to 80%. The project recommends keeping all six |
| Resilience | Demand can grow 40% before the network breaks. Losing Columbus (the only plant for ENER25) or Dallas leaves demand unmet |
| Where effort pays | Demand (34% swing) is an uncertainty. The biggest lever is the carrier rate (11.0%), then DC fixed cost (6.0%). Service level and lead times move cost under 1% |
| Cost to serve | $68 a pallet in Houston to $262 in Seattle |

The honest headline is a modest one. A good analyst reports 3.7%, explains why it is not bigger (production is 53% of cost and the model cannot change plant costs) and says what would be needed to find more.

## The inputs, in one minute

All company data is simulated, because Tidewell is fictional. The key inputs are anchored to benchmarks: freight at $0.10 a pallet-mile against 2026 truckload rates of $2.25 to $2.50 a mile before fuel,
holding cost at 22% of value against the 20 to 30% industry range, 26 pallets a trailer, and road distances fitted to 16 known driving distances (mean error 5%). Everything else is a labelled planning assumption.

Most important, the project tests how much those assumptions matter. The size of the cost and the main findings hold across all of them. The exact set of open DCs does not: a higher freight rate or a shorter delivery radius
keeps all six. That is why the recommendation rests on service, not on a claim that one DC set is the single right answer.

## Does it hold up on other data?

Yes. The same pipeline and checks were run on ten other synthetic companies with different sizes (2 to 4 plants, 4 to 7 candidate DCs, 12 to 20 markets, 1,674 to 4,307 pallets a week), geographies, costs and messiness.
All 343 checks passed. The first run also found two real problems, fixed and logged in the audit. The limits of this test are stated in `docs/ROBUSTNESS.md`: synthetic companies show consistency, not real-world accuracy.

## How I used AI, step by step

| Step | What I decided | What the AI did | How it was checked |
| --- | --- | --- | --- |
| Framing | The question, the three levers, US geography and dollars | Proposed a structure and wrote the code | I read the flowchart and the plain-language explanation |
| Realism | That a manager must not laugh at the numbers | Audited its own work from a supply chain manager's point of view and found 16 problems | Each problem has a fix and a check |
| Inputs | That every input must have a source or be called an assumption | Looked up 2026 freight rates, holding-cost ranges and trailer size, and fitted road distances | `docs/DATA_AND_ASSUMPTIONS.md`, with links |
| Robustness | That one company is not proof | Built a generator of other companies and ran all checks on ten | `docs/ROBUSTNESS.md` |
| Honesty | That a small saving must be reported as small, and a fragile choice as fragile | Generated the executive summary from the run so numbers cannot drift | A docs check fails if a number in the docs differs from the run |
| Ownership | That the project must be publishable and credited | Rewrote the models from textbook methods in a fresh repo, with attribution to the video that inspired the case | `docs/ATTRIBUTION.md` |

### The best example of judgement

The first version used a holding cost of $3.50 per pallet-week for every product. The AI did not flag it. A supply chain review did: for a $88 pallet of water that is
about 200% of its value every year, when real holding rates are 20 to 30%. The fix was to charge 22% of each item's value, so energy drinks cost more to hold than water.
A further check then caught a bug where a "what if the holding rate changes" test returned exactly $0. Later, checking the freight rate against 2026 market data found it was too low, and the
corrected rate changed the numbers.

That is the story to tell: **the AI is fast, the supply chain knowledge is what makes the answer trustworthy.**

## What this shows about you (only say what you can explain)

- You can frame a supply chain problem across network design, production and inventory.
- You understand safety stock, fill rate, lot sizing, service radius, shelf life and peak-week capacity.
- You can supervise AI output critically, and test whether it holds up on other data.
- You report results with their limits.

## Limits (say them before they ask)

- The data is simulated, so there is no real forecast error, freight bill or service history.
- Freight is linear in pallet-miles; a real model rounds to truckloads.
- Plant capacity is in pallets, not line hours.
- One service level for every item.
- Several inputs are assumptions: the 90% capacity margin, the 1,100-mile radius, shelf lives of water, tea and juice, and DC fixed costs.
- The exact DC set depends on the freight rate, delivery radius and road factor.

## Three ways to present it

**30 seconds.** Use the 20-second version, then: "The headline is that the chain can be run about 4% cheaper, but the real decision is whether to close Chicago, because it trades 0.4% of cost for next-day coverage that rises from 68% to 80%."

**2 minutes.** Business question, the five-stage flowchart, three findings (3.7%, late deliveries drive 57% of safety stock, the Chicago trade-off), the audit story, then robustness.

**5 minutes, screen share.** Open in this order: the flowchart, `docs/EXECUTIVE_SUMMARY.md`, the network map (`charts/02_network_map.png`), the dashboard (move the demand dial until it breaks), `docs/DATA_AND_ASSUMPTIONS.md`, then `docs/AUDIT.md`.

## Drafts you can adapt

**CV bullet.**
- Built an end-to-end US beverage supply chain optimisation (ERP/WMS/TMS data pipeline, network design, Wagner-Whitin production planning, lead-time-aware safety stock) with an AI assistant; audited it against 16 supply chain realism gaps, benchmarked its inputs, and validated it with automated checks on Tidewell and on ten other synthetic companies.

**LinkedIn post.**
> I built a supply chain optimisation project with AI, then spent as long auditing it as building it. The first draft charged 200% a year to hold a pallet of water. I checked every input against 2026 benchmarks, tested the whole pipeline on ten other synthetic companies, and wrote down which assumptions change the answer. The result: a network recommendation, a 3.7% saving, and an honest note that the real decision is Chicago versus next-day delivery. Repo and write-up in comments.

## Credit

The case structure was inspired by Supply Science's video "What is Supply Chain Optimisation? A Practical Case Study". The company, data, code and analysis in this repo are independent. See `docs/ATTRIBUTION.md`.
