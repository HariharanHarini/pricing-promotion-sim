# Validation summary

76/76 checks passed.

| Result | Check | Detail |
|---|---|---|
| PASS | columns match data dictionary: product |  |
| PASS | PK unique: product | pk=['sku'], rows=5,000 |
| PASS | columns match data dictionary: cost_record |  |
| PASS | PK unique: cost_record | pk=['cost_id'], rows=30,000 |
| PASS | columns match data dictionary: price_history |  |
| PASS | PK unique: price_history | pk=['price_id'], rows=900,000 |
| PASS | columns match data dictionary: competitor_observation |  |
| PASS | PK unique: competitor_observation | pk=['obs_id'], rows=509,802 |
| PASS | columns match data dictionary: inventory_snapshot |  |
| PASS | PK unique: inventory_snapshot | pk=['snapshot_id'], rows=900,000 |
| PASS | columns match data dictionary: promotion |  |
| PASS | PK unique: promotion | pk=['promo_id'], rows=2,000 |
| PASS | columns match data dictionary: promotion_rule |  |
| PASS | PK unique: promotion_rule | pk=['rule_id'], rows=10,000 |
| PASS | columns match data dictionary: promotion_sku |  |
| PASS | PK unique: promotion_sku | pk=['promo_id', 'sku'], rows=181,837 |
| PASS | columns match data dictionary: promotion_event |  |
| PASS | PK unique: promotion_event | pk=['event_id'], rows=7,796 |
| PASS | columns match data dictionary: product_status_event |  |
| PASS | PK unique: product_status_event | pk=['event_id'], rows=5,100 |
| PASS | columns match data dictionary: orders |  |
| PASS | PK unique: orders | pk=['order_id'], rows=530,453 |
| PASS | columns match data dictionary: order_promotion |  |
| PASS | PK unique: order_promotion | pk=['order_id', 'promo_id'], rows=381,752 |
| PASS | columns match data dictionary: price_decision |  |
| PASS | PK unique: price_decision | pk=['decision_id'], rows=129,441 |
| PASS | required fields non-null and enum values valid (all tables) |  |
| PASS | FK integrity (19 relationships) |  |
| PASS | volume: price_history = SKUs x days | 900,000 = 5,000 x 180 |
| PASS | volume: inventory_snapshot = SKUs x days |  |
| PASS | volume: promotions | 2,000 |
| PASS | ID conventions (SKU-000001, COST-<sku>-2026-01, PRC-<sku>-20260101, PROMO-2026-000001, DEC-2026-000001) | [] |
| PASS | ID embeds match their row (cost_id/price_id/snapshot_id contain sku and date) |  |
| PASS | cost_record: effective_from <= effective_to |  |
| PASS | cost_record: contiguous, no gaps/overlaps |  |
| PASS | cost_record: exactly one ACTIVE row per SKU |  |
| PASS | cost_record: change_pct = unit_cost/prev - 1; reason iff changed |  |
| PASS | promotion: created < start <= end |  |
| PASS | promotion_event: allowed lifecycle transitions + chronological |  |
| PASS | promotion.status = last promotion_event.to_state |  |
| PASS | promotion: cancelled_date set iff CANCELLED |  |
| PASS | event from_state chain consistent (from_state = previous to_state) |  |
| PASS | product.lifecycle_state = last product_status_event |  |
| PASS | competitor_observation: observed_at <= ingested_at; lag reconciles |  |
| PASS | competitor_observation: no duplicate (sku, competitor, ingested_at) |  |
| PASS | price_history: daily contiguous per SKU |  |
| PASS | price_history: prev_list_price = previous day list_price |  |
| PASS | price_history: is_price_change consistent |  |
| PASS | price_history.cost_id is the cost in force (join + date within effective window) |  |
| PASS | price_history.price_floor = ceil(cost / (1 - min_margin)) |  |
| PASS | price <= ceiling everywhere |  |
| PASS | guardrail: every below-floor price traces to a decision that itself is below floor (no silent breaches) | 3,474 below-floor price-days from 513 decisions |
| PASS | explainability: every price change has decision_id + change_reason, except manual overrides | 303 unexplained changes (scored below vs ground truth) |
| PASS | price_history <-> decision: same SKU, same date, price = final_price, reason = reason_code |  |
| PASS | every APPLIED decision appears in price_history |  |
| PASS | decision arithmetic: price_change_pct, margin_pct_at_final, status |  |
| PASS | FLOOR guardrail rows end at the floor | 464 rows |
| PASS | inventory: closing = opening - sold |  |
| PASS | inventory: opening = previous closing + received |  |
| PASS | inventory: stockout_flag = (closing == 0); no negative stock |  |
| PASS | reconciliation: inventory.units_sold = SUM(orders.quantity) per SKU/day | 661,788 units |
| PASS | orders join price_history/cost_record: same list price, unit cost, date |  |
| PASS | orders: gross = qty x list; cogs = qty x cost; net = gross - discount; margin amount = net - cogs |  |
| PASS | orders.discount_amount = SUM(order_promotion lines); promo_count = rows |  |
| PASS | order_promotion: apply_seq 1..n without gaps |  |
| PASS | no duplicate orders (all columns except id) | 0 duplicates |
| PASS | data/ has no ground-truth columns (no leakage) |  |
| PASS | promotion eligibility reproducible: independent re-implementation matches applied promos | 4,000 sampled orders, 0 mismatches |
| PASS | promo margin guard: every order under product min margin is explained (CLEARANCE 5% rule, stack violation, or below-floor list price) | {'total': 46510, 'clearance_5pct_rule': 42662, 'stack_violation': 727, 'list_price_below_floor': 3495, 'unexplained': 0} |
| PASS | detector PRICE_BELOW_FLOOR: precision/recall vs ground truth | {'injected': 513, 'detected': 513, 'true_pos': 513, 'false_pos': 0, 'false_neg': 0, 'precision': 1.0, 'recall': 1.0} |
| PASS | detector PROMOTION_STACK_VIOLATION: precision/recall vs ground truth | {'injected': 1632, 'detected': 1632, 'true_pos': 1632, 'false_pos': 0, 'false_neg': 0, 'precision': 1.0, 'recall': 1.0} |
| PASS | detector STALE_OBSERVATION_AS_CURRENT: precision/recall vs ground truth | {'injected': 1328, 'detected': 1328, 'true_pos': 1328, 'false_pos': 0, 'false_neg': 0, 'precision': 1.0, 'recall': 1.0} |
| PASS | detector MARGIN_BEFORE_DISCOUNT: precision/recall vs ground truth | {'injected': 5435, 'detected': 5435, 'true_pos': 5435, 'false_pos': 0, 'false_neg': 0, 'precision': 1.0, 'recall': 1.0} |
| PASS | detector PRICE_CHANGE_LACKS_REASON: precision/recall vs ground truth | {'injected': 303, 'detected': 303, 'true_pos': 303, 'false_pos': 0, 'false_neg': 0, 'precision': 1.0, 'recall': 1.0} |
| PASS | every required edge case is present in ground truth |  |
| PASS | anomalies are labelled, not silent: baseline rows violate no rule beyond ground truth |  |
