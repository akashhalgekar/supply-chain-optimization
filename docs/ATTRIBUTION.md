# Attribution

This project was inspired by the case study in the Supply Science video
["What is Supply Chain Optimisation? A Practical Case Study"](https://youtu.be/ToCsoK914dU)
by Samir Saci. The idea of a beverage company with three levers (network design, production lot sizing, safety stock) joined into one chain is his.

What is original here:
- the company (Tidewell), its numbers and its simulated ERP, WMS and TMS extracts
- the ETL, its control totals and the data quality log
- the model code, written from the standard textbook formulations: a facility-location mixed integer program, the Wagner-Whitin dynamic program with a
  capacity-aware extension, and the two-source safety stock formula
- the peak-week capacity rule, the lead-time-aware safety stock, the fill-rate calculation, the whole-chain DC set comparison, stress tests, input
  sensitivity, cost to serve, the verification suite, the dashboard and the documents

None of the video's code is included. The methods themselves (facility location, Wagner-Whitin 1958, the safety stock formula) are standard and
credited to their authors in any operations research textbook.

The code was written with the help of an AI assistant (Claude).
