# Pricing & Promotion Simulation - synthetic dataset

Synthetic data generator, validator and anomaly-detector scorer for a pricing and promotions workflow
(5,000 SKUs, 180 days, 2,000 promotions, fixed seed 20261022).

## Quickstart (about 5 minutes)

Windows PowerShell:
```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Mac/Linux:
```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
No configuration or API keys are needed. Python 3.10+.

Run:
```
python make_docs.py
python generate.py --skus 300 --days 60 --promos 100 --seed 20261022 --out out/starter
python generate.py --skus 5000 --days 180 --promos 2000 --seed 20261022 --out out/full
python validate.py out/full
python export_sql.py out/starter --seed-sql out/starter/sql/seed_starter.sql --sqlite out/starter/pricing_sim.db
python repro_check.py
```

## How to verify key behaviour
| What to check | How | Expected |
|---|---|---|
| Whole test suite | `python -m pytest -q` | 5 passed |
| Data is valid | `python validate.py out/full` | `76/76 checks passed` |
| Reproducible | `python repro_check.py` | `REPRODUCIBLE - all files byte-identical` |
| Guardrails hold | open `out/full/ground_truth/ground_truth.csv`; every below-floor price is labelled | validator check "no silent breaches" |
| Prices explainable | `out/full/data/price_decision.csv` has inputs, candidate, guardrail, reason per decision | every price change joins to a decision |
| Anomalies detectable | `out/full/docs/metrics.json` -> `anomaly_detection` | precision and recall 1.0 per issue type |

Reasoning, assumptions, trade-offs and limits: `docs/DESIGN.md`. AI use: `docs/AI_USAGE.md`, `docs/PROMPT_HISTORY.md`.

---

## Overview
Simulates pricing and promotions from demand, stock, competitor observations and margin constraints.
One generator builds both datasets; only the scale flags differ.

```
python generate.py --skus 5000 --days 180 --promos 2000 --seed 20261022 --out out/full      # full
python generate.py --skus 300  --days 60  --promos 100  --seed 20261022 --out out/starter   # starter
python validate.py out/full          # 76 checks + detector scoring
python repro_check.py                # regenerate twice, compare checksums
```
Needs Python 3.10+, numpy, pandas. Full run takes about 10 seconds.

## How it works
1. `schema.py` is the single source of truth: fields, types, enums, PKs, FKs. `make_docs.py` renders `docs/data_dictionary.md` and `sql/schema.sql` from it.
2. `generate.py` builds master data first (Product, CostRecord, competitor snapshots, Promotion + rules), then runs a day-by-day simulation:
   - Weekly pricing review, plus a decision on any month a cost changes.
   - Candidate price = competitor match (fresh observations only, <= 96h) or stock signal (low/over cover) or cost pass-through.
   - Guardrails in order: max step 10%, then floor `cost / (1 - min_margin)` and fixed ceiling.
   - Promotions resolved per SKU-day: stock and margin eligibility, then stacking.
   - Demand uses price vs market, promo uplift, weekday and noise. Orders are drawn against stock. Stockouts, reorders and supplier delays follow.
3. Every derived value (stock, order totals, margins, statuses) comes from those records, not independent random draws.

## Business rules
- **Margin basis:** `(price - cost) / price`. List rows use list price. Order rows use net price after all discounts.
- **Stacking:** at most one SITEWIDE/CATEGORY promo; a COUPON may stack on it; CLEARANCE is exclusive. Total discount <= 40%. Promo net price must keep the product min margin (CLEARANCE: 5%). Rules are stored in `promotion_rule` and replayed independently in `validate.py`.
- **Freshness:** a competitor observation is current only if decision time minus `observed_at` <= 96h.
- **History:** nothing is overwritten. Costs, prices, inventory, decisions and promotion state changes are all appended rows.

## Labelled edge cases (`ground_truth/`)
Injected inside the simulation as rule bypasses, so downstream rows stay consistent. Not in `data/`.

| Issue | Injected |
|---|---|
| PRICE_BELOW_FLOOR | 513 |
| PROMOTION_STACK_VIOLATION | 1,632 |
| STALE_OBSERVATION_AS_CURRENT | 1,328 |
| MARGIN_BEFORE_DISCOUNT | 5,435 |
| PRICE_CHANGE_LACKS_REASON | 303 |

Rule-based detectors that read only `data/` score precision 1.0 and recall 1.0 on all five.
Orders sold at an anomalous below-floor price are consequences of the labelled decision, not separate labels.

## Full dataset (seed 20261022)
5,000 SKUs; 900,000 price-days and stock-days; 129,441 pricing decisions; 509,802 competitor observations; 2,000 promotions; 530,453 orders (661,788 units).
Gross margin 30.3% of net revenue; average discount 12.1%; 68% of orders carry a promotion; stockout rate 3.3% of SKU-days.
Exceptions exercised: stale competitor ignored (7,187 decisions), stockout hold (4,234), competitors out of stock (1,275), floor guardrail binding (464).
Full metrics: `out/full/docs/metrics.json`.

## Provenance
No external data. Everything is synthetic. See `source_manifest.json`.

## Known limits (honest notes)
- Single currency, one SKU per order line, no returns or cancellations.
- Detectors score 1.0 because injections are clean rule bypasses. Real data would be messier.
- The stack replay checks the best auto promo and best coupon; it samples 4,000 orders, not all.
