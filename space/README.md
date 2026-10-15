---
title: Tidewell Supply Chain Optimiser
emoji: 🚚
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Network design, production planning and safety stock in one chain
---

# Tidewell supply chain optimiser

A live version of [akashhalgekar/supply-chain-optimization](https://github.com/akashhalgekar/supply-chain-optimization):
a simulated US drinks company where one chain decides which warehouses to run, when each plant produces and how much
safety stock each warehouse holds.

- Move the dials or pick a scenario: the whole chain re-solves on every change.
- **Ask the analyst**: describe a stock, batching or warehouse problem from your own business (or a Tidewell what-if) and Claude works it out with the same models, so the numbers are calculated, not guessed. Uses your own Anthropic API key, which stays in your browser.

This Space is deployed automatically from the GitHub repo. The data is simulated; see the repo for the method, the
checks and the limits.
