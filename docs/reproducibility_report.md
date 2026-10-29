# Reproducibility report

Command: `python generate.py --skus 5000 --days 180 --promos 2000 --seed 20261022` run twice (A, B) plus once with seed 20261023 (C).

| File | Rows | SHA-256 run A | SHA-256 run B | A vs B | A vs C (other seed) |
|---|---|---|---|---|---|
| data/product.csv | 5,000 | e9806be33a54b38b | e9806be33a54b38b | identical | differs |
| data/cost_record.csv | 30,000 | 2ea1423e253cca65 | 2ea1423e253cca65 | identical | differs |
| data/price_history.csv | 900,000 | dd2fbf365fbf3cff | dd2fbf365fbf3cff | identical | differs |
| data/competitor_observation.csv | 509,802 | 8d07e13397d508c0 | 8d07e13397d508c0 | identical | differs |
| data/inventory_snapshot.csv | 900,000 | a953c4e0586bb097 | a953c4e0586bb097 | identical | differs |
| data/promotion.csv | 2,000 | a8d06a46fbecec37 | a8d06a46fbecec37 | identical | differs |
| data/promotion_rule.csv | 10,000 | 4b867cfef86c4351 | 4b867cfef86c4351 | identical | differs |
| data/promotion_sku.csv | 181,837 | d92ef0e145027a4a | d92ef0e145027a4a | identical | differs |
| data/promotion_event.csv | 7,796 | a75e03f6c8b0b8e7 | a75e03f6c8b0b8e7 | identical | differs |
| data/product_status_event.csv | 5,100 | 1ad45adf8fde322b | 1ad45adf8fde322b | identical | differs |
| data/orders.csv | 530,453 | a07bccdf6afee2c7 | a07bccdf6afee2c7 | identical | differs |
| data/order_promotion.csv | 381,752 | 48dc82317bf62f2e | 48dc82317bf62f2e | identical | differs |
| data/price_decision.csv | 129,441 | 94e6f79680c8b16b | 94e6f79680c8b16b | identical | differs |
| ground_truth/ground_truth.csv | 9,211 | 55704f1589dc696d | 55704f1589dc696d | identical | differs |

**Result: REPRODUCIBLE - all files byte-identical**
