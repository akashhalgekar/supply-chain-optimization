# Interview questions, with answers drawn from this project

Read the matching code before an interview. If you cannot explain an answer in your own words, say less rather than bluff.

## About the project

**Q: What does this project do?**
It takes messy simulated ERP, WMS and TMS data, cleans it with an ETL, and runs three models: which DCs to open, when plants should produce, and how much safety stock each DC needs. It then adds a decision layer: savings, stress tests, sensitivity and cost to serve.

**Q: Did you write the code?**
I built it with an AI assistant (Claude). I framed the problem, set the realism requirements, asked for the audit, the input benchmarking and the test on other data, and reviewed the results. The AI wrote the code under that direction. I can explain how each model works. *(Only say this if you have read the code and can.)*

**Q: What data does it use?**
All company data is simulated, because Tidewell is fictional. I did not use any real company's data. The simulated files are deliberately messy, and the key inputs are anchored to benchmarks: freight against 2026 truckload rates, holding cost against the 20 to 30% industry range, 26 pallets a trailer, and road distances fitted to 16 known driving distances. `docs/DATA_AND_ASSUMPTIONS.md` classes every input as simulated, benchmarked or assumed, with its source and its effect on the answer.

**Q: How do you know the model is not just tuned to your one company?**
I built a generator of other synthetic companies, with different numbers of items, plants, DCs and markets, different cities, costs, shelf lives and demand variability, and ran the whole pipeline and all checks on ten of them. All 343 checks passed. The first run found two real problems, which I fixed. It shows consistency, not real-world accuracy, and `docs/ROBUSTNESS.md` says so.

**Q: What did the AI get wrong?**
The first version charged a flat $3.50 a pallet-week to hold stock, about 200% of a water pallet's value a year. It also had no shelf life, no delivery radius, the same lead time for every DC, capacity checked on the average week, and a freight rate below the 2026 market. A review found 16 issues. All are in `docs/AUDIT.md` with a check for each.

**Q: How do you know the answer is right?**
`verify.py` runs the checks. The ETL recovers the company's true figures from the messy files. The models agree on both versions of the data. The production plan matches textbook Wagner-Whitin where capacity does not bind. A brute-force search over every DC set confirms the network choice. The ETL refuses a corrupted file. Deliberately broken inputs make the checks fail, which shows they have teeth.

**Q: Why is the saving only 3.7%?**
Production is 53% of cost and the model treats plant cost as fixed, so network and inventory levers cannot move the total far. Reporting a small number honestly is better than tuning inputs until it looks large.

**Q: How sensitive is the answer to your assumptions?**
The size of the cost and the main findings hold: production dominates, and late deliveries drive 57% of safety stock in this simulated company. The exact set of DCs does not. A freight rate of $0.115 or a 900-mile radius keeps all six, and a 1,300-mile radius closes Atlanta and Seattle. The cost gaps between the options are small, which is why I recommend on service rather than claim one set is the right answer.

**Q: Is the 57% a real finding?**
Not about the real world. It follows from the delivery-time spread I assumed for each simulated DC: at half that spread it is 32%, at double it is 77%. What the project shows is the method: that delivery reliability can drive safety stock as much as demand swings, and how to measure it. With real receipts, the same code would give a real number.

## About the supply chain content

**Q: What is Wagner-Whitin?**
A dynamic programme for lot sizing: given weekly demand, a setup cost and a holding cost, it finds the cheapest weeks to produce in. Too many runs wastes setups, too few builds stock. I also modelled plant capacity and shelf life, which the textbook version ignores, and show where they change the answer.

**Q: How is safety stock calculated?**
`z x square root of (lead time x demand variance + demand squared x lead-time variance)`. It covers demand running high and deliveries arriving late. Here the stock is 1,088 pallets, against 464 if only demand swings were counted, so 57% of it exists because of late deliveries.

**Q: What is the difference between service level and fill rate?**
Cycle service level is the share of replenishment cycles without a stockout. Fill rate is the share of units served from stock. At 95% cycle service level the fill rate here is about 99.3%. People mix them up.

**Q: Why not close Chicago if it is cheapest?**
It is cheapest by $2,698 a week (0.4%), but Chicago is a large market and closing its DC drops next-day coverage from 80% to 68%. I recommend keeping all six unless that coverage is worth less than 0.4% of cost. It is a business trade-off, and the project says so.

**Q: Why check capacity against the peak week?**
A network that is full on average cannot make the summer peak. Capacity is checked against the busiest week with a 90% margin.

**Q: Why 22% holding cost?**
It stands for capital, storage, insurance and obsolescence. Published ranges are 20 to 30% of stock value a year, and packaged shelf-stable goods sit near 20 to 25%. The sensitivity run shows 15% to 30% moves total cost by only about 0.2%.

**Q: What would break the network?**
Losing Columbus (the only plant for ENER25) or Dallas, demand growing more than 40%, or a next-day (600-mile) promise from these sites. Those are in the stress tests.

**Q: Which inputs matter most?**
Demand moves cost most (34% for a 20% swing) but is an uncertainty. Of the levers, the carrier rate (11.0%) and DC fixed cost (6.0%) matter. Service level and lead times move cost under 1%.

## About AI and judgement

**Q: How do you stop AI giving you confident nonsense?**
Ask it to audit as a domain expert, make it write checks that can fail, test those checks against deliberately broken inputs, benchmark inputs against outside sources, and test on other data. Never accept a result you cannot explain.

**Q: What would you do with real data?**
Replace the simulated extracts with real exports (the models only read the clean store), measure real lead times and forecast error, calibrate holding rate and freight to actual invoices, and run the same checks.

**Q: What are the limits?**
Simulated data, linear freight, capacity in pallets not line hours, one service level for all items, assumed independence between markets, and several planning assumptions listed in `docs/DATA_AND_ASSUMPTIONS.md`.

## Be able to explain these yourself

1. The flowchart, stage by stage.
2. Why safety stock has two terms.
3. Why a batch cannot cover more weeks than shelf life allows.
4. Why the textbook plan costs less than the plan the plants can run.
5. What the reference case is and what it is not (it is a yardstick, not a measured current state).
6. Which of your assumptions change the DC choice and which do not.
