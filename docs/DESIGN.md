# Design, assumptions and reasoning

## Problem
Build a synthetic dataset for a pricing and promotions workflow. It must be internally consistent, traceable (every price explainable), reproducible, and contain labelled anomalies kept apart from the input data.

## Key decisions and why
| Decision | Why | Trade-off |
|---|---|---|
| Day-by-day simulation, not independent random tables | Brief says outcomes come from documented rules. Stock, orders, margins and statuses are derived, so joins and totals reconcile by construction | More code than random sampling; harder to tweak one table alone |
| Anomalies injected inside the simulation as rule bypasses, then labelled | Downstream rows (orders, stock) stay consistent; no unrelated rows are corrupted | Consequences (e.g. orders sold at a below-floor price) are not separately labelled |
| Margin basis `(price - cost) / price`; list price for price rows, net-after-discount for orders | Brief requires one consistent basis; this is the usual definition | Differs from markup-on-cost users may expect |
| Price floor = `cost / (1 - min_margin)`, recomputed from the cost in force | Floors move when cost changes, so cost pass-through is testable | Needs cost joins everywhere |
| Stacking: one base promo (sitewide or category), optional coupon, clearance exclusive, 40% cap | Gives conflicting-coupon and exclusion cases from simple rules | Real systems have more promo types |
| Competitor data is current only if age <= 96h at decision time | Makes "stale observation" a precise, testable rule | 96h is an assumption |
| One SKU per order line | Keeps order-to-stock reconciliation exact | No baskets |
| Rules live in `promotion_rule`; validator replays them with separate scalar code | Independent check of eligibility reproducibility | The replay samples 4,000 orders |
| `schema.py` is the single source for dictionary, DDL, enums and column order | Docs and code cannot drift apart | Extra indirection |
| Fixed seed, `SeedSequence.spawn` per component | Adding draws in one component does not shift others; same seed gives byte-identical files | Stream layout is fixed once data is published |

## Assumptions
Single currency; decisions run weekly and on month starts when cost changes; decisions take effect for the whole day; competitor lag and staleness are drawn per source type; supplier delays cause stockouts; no returns or cancellations; no external data (see `source_manifest.json`).

## Testing approach
1. `validate.py`: 76 checks. They cover PK uniqueness, FK integrity, enums, required fields, ID formats, date ordering, lifecycle transitions, arithmetic reconciliation (stock to orders, order totals, margins), guardrails, and duplicates.
2. Rule-based detectors use only `data/` and are scored against `ground_truth/`.
3. `pytest`: same-seed byte identity, different-seed difference, validator passes, ground truth is separate and complete, no unlabelled below-floor decision.
4. `repro_check.py`: regenerates the full dataset twice and compares checksums.

## How I know it works
All 76 checks pass at starter and full scale. Two same-seed runs produce identical SHA-256 per file. The validator caught a real issue during development: orders below product minimum margin looked unexplained until traced to clearance's 5% rule, stack violations, and labelled below-floor prices. That led to an explicit "every low-margin order is explained" check.

## Limitations
- Detector scores of 1.0 reflect clean injected bypasses, not messy real data.
- Demand model is simple (price elasticity, promo uplift, weekday, noise).
- Clearance may go below the product margin floor by design (5% rule).
- The validator needs a few GB of RAM at full scale.

## Walkthrough guide (for the live review)
1. `schema.py` (what the entities are). 2. `generate.py` top to bottom: products, costs, competitors, promotions, then the `for d in range(D)` loop. 3. One row traced across tables: a `price_decision` row to its `price_history` row to `orders` to `order_promotion`. 4. `validate.py` sections 5 to 8. 5. One injected anomaly end to end.
