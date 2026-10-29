"""Single source of truth for the data dictionary, enums, keys and FKs.

generate.py writes columns in this order, validate.py checks against it,
make_docs.py renders data_dictionary.md + schema.sql from it.
"""

ENUMS = {
    "CATEGORIES": ["Electronics", "Home & Kitchen", "Apparel", "Grocery", "Beauty",
                   "Toys", "Sports", "Office", "Pet", "Garden"],
    "BRANDS": ["Aurora", "Nimbus", "Verdant", "Kestrel", "Lumen", "Orchid",
               "Basalt", "Cobalt", "Meridian", "Solstice", "Tamarind", "Zephyr"],
    "LIFECYCLE": ["ACTIVE", "DISCONTINUED"],
    "COMPETITORS": ["COMP-A", "COMP-B", "COMP-C"],
    "SOURCE_TYPES": ["API_FEED", "SCRAPE", "MANUAL_SHEET"],
    "COST_REASONS": ["SUPPLIER_INCREASE", "FREIGHT_SURCHARGE", "FX_MOVE",
                     "SUPPLIER_DISCOUNT", "VOLUME_REBATE"],
    "COST_STATUS": ["ACTIVE", "SUPERSEDED"],
    "REASON_CODES": ["COMPETITOR_MATCH", "LOW_STOCK_INCREASE", "OVERSTOCK_MARKDOWN",
                     "COST_PASS_THROUGH", "FLOOR_ENFORCEMENT", "STOCKOUT_HOLD",
                     "HOLD_NO_SIGNAL"],
    "PRICE_CHANGE_REASONS": ["COMPETITOR_MATCH", "LOW_STOCK_INCREASE", "OVERSTOCK_MARKDOWN",
                             "COST_PASS_THROUGH", "FLOOR_ENFORCEMENT", "STOCKOUT_HOLD",
                             "HOLD_NO_SIGNAL", "INITIAL_LISTING"],
    "EXCEPTION_CODES": ["STALE_COMPETITOR_IGNORED", "COMPETITOR_OUT_OF_STOCK",
                        "NO_COMPETITOR_DATA", "STOCKOUT_HOLD"],
    "GUARDRAILS": ["NONE", "MAX_STEP", "FLOOR", "CEILING"],
    "DECISION_STATUS": ["APPLIED", "NO_CHANGE"],
    "PROMO_TYPES": ["SITEWIDE", "CATEGORY", "COUPON", "CLEARANCE"],
    "PROMO_STATUS": ["DRAFT", "SCHEDULED", "ACTIVE", "ENDED", "CANCELLED"],
    "DISCOUNT_TYPES": ["PERCENT", "AMOUNT"],
    "SCOPE_TYPES": ["ALL", "CATEGORY_BRAND", "SKU_LIST"],
    "RULE_TYPES": ["MIN_STOCK_UNITS", "MIN_MARGIN_PCT", "MAX_TOTAL_DISCOUNT_PCT",
                   "EXCLUDES_GROUP", "MAX_STACK_COUNT"],
    "CHANNELS": ["WEB", "APP", "STORE"],
    "ISSUE_TYPES": ["PRICE_BELOW_FLOOR", "PROMOTION_STACK_VIOLATION",
                    "STALE_OBSERVATION_AS_CURRENT", "MARGIN_BEFORE_DISCOUNT",
                    "PRICE_CHANGE_LACKS_REASON"],
}

# Allowed promotion state transitions (lifecycle)
PROMO_TRANSITIONS = {
    None: ["DRAFT"],
    "DRAFT": ["SCHEDULED", "CANCELLED"],
    "SCHEDULED": ["ACTIVE", "CANCELLED"],
    "ACTIVE": ["ENDED", "CANCELLED"],
    "ENDED": [], "CANCELLED": [],
}

# field DSL: name|type|R/O|allowed|unit|uniqueness|validation rule
_SPEC = {
"product": ("Master data. One row per sellable SKU.", ["sku"], """
sku|string|R|SKU-######|-|PK|matches ^SKU-\\d{6}$
product_name|string|R|free text|-|no|non-empty
category|string|R|enum:CATEGORIES|-|no|in enum
brand|string|R|enum:BRANDS|-|no|in enum
launch_date|date|R|ISO date|date|no|< simulation start
lifecycle_state|string|R|enum:LIFECYCLE|-|no|equals to_state of the latest product_status_event
min_margin_pct|decimal|R|0.10-0.22|fraction of price|no|0 < x < 0.5; margin basis = (price - cost) / price
initial_list_price|decimal|R|> 0|currency|no|>= cost / (1 - min_margin_pct) at first cost record
price_ceiling|decimal|R|> 0|currency|no|= round(1.5 * initial_list_price, 2); fixed
lead_time_days|int|R|5,7,10,14|days|no|> 0
"""),
"cost_record": ("Monthly cost history. One row per SKU per calendar month; new row each month, old row kept (SUPERSEDED).", ["cost_id"], """
cost_id|string|R|COST-<sku>-YYYY-MM|-|PK|month of effective_from; e.g. COST-SKU-000001-2026-01
sku|string|R|-|-|no|FK product.sku
effective_from|date|R|ISO date|date|no|first day of the month (or simulation start)
effective_to|date|O|ISO date|date|no|null for the ACTIVE row, else next effective_from - 1 day
unit_cost|decimal|R|> 0|currency/unit|no|within 0.80x-1.35x of the SKU's first cost
prev_unit_cost|decimal|O|> 0|currency/unit|no|null for first row; else previous row unit_cost
change_pct|decimal|O|-|fraction|no|= unit_cost / prev_unit_cost - 1 (4 dp); null for first row
change_reason|string|O|enum:COST_REASONS|-|no|required iff change_pct != 0
status|string|R|enum:COST_STATUS|-|no|exactly one ACTIVE row per SKU
"""),
"price_history": ("Daily list price per SKU. Append-only; one row per SKU per day.", ["price_id"], """
price_id|string|R|PRC-<sku>-YYYYMMDD|-|PK|one row per sku and date
sku|string|R|-|-|no|FK product.sku
price_date|date|R|ISO date|date|no|contiguous daily
list_price|decimal|R|> 0|currency|no|price in force for the whole day
prev_list_price|decimal|O|> 0|currency|no|null on first day; else previous day list_price
is_price_change|bool|R|0/1|-|no|1 iff list_price != prev_list_price
change_reason|string|O|enum:PRICE_CHANGE_REASONS|-|no|REQUIRED when is_price_change = 1; INITIAL_LISTING on first day
decision_id|string|O|DEC-2026-######|-|no|FK price_decision; REQUIRED when is_price_change = 1
cost_id|string|R|-|-|no|FK cost_record in force on price_date
unit_cost|decimal|R|> 0|currency/unit|no|= cost_record.unit_cost
price_floor|decimal|R|> 0|currency|no|= ceil_to_cent(unit_cost / (1 - min_margin_pct))
margin_pct|decimal|R|-|fraction|no|= (list_price - unit_cost) / list_price (4 dp); list basis, no promotions
"""),
"competitor_observation": ("Competitor price snapshots with source timestamp (observed_at) and ingestion timestamp.", ["obs_id"], """
obs_id|string|R|OBS-2026-######|-|PK|sequential by ingested_at
sku|string|R|-|-|no|FK product.sku
competitor_id|string|R|enum:COMPETITORS|-|no|in enum
observed_at|timestamp|R|ISO 8601|UTC|no|source timestamp (when the competitor price was true)
ingested_at|timestamp|R|ISO 8601|UTC|no|>= observed_at
competitor_price|decimal|R|> 0|currency|no|price at observed_at
in_stock|bool|R|0/1|-|no|competitor availability at observed_at
source_type|string|R|enum:SOURCE_TYPES|-|no|in enum
source_lag_hours|decimal|R|>= 0|hours|no|= (ingested_at - observed_at) in hours
"""),
"inventory_snapshot": ("Daily stock position per SKU.", ["snapshot_id"], """
snapshot_id|string|R|INV-<sku>-YYYYMMDD|-|PK|one row per sku and date
sku|string|R|-|-|no|FK product.sku
snapshot_date|date|R|ISO date|date|no|contiguous daily
opening_on_hand|int|R|>= 0|units|no|= previous closing_on_hand + units_received
units_received|int|R|>= 0|units|no|PO arrivals that day
units_sold|int|R|>= 0|units|no|= SUM(orders.quantity) for sku/date
units_unfulfilled|int|R|>= 0|units|no|demand that could not be filled (stockout)
closing_on_hand|int|R|>= 0|units|no|= opening_on_hand - units_sold
stockout_flag|bool|R|0/1|-|no|1 iff closing_on_hand = 0
reorder_point|int|R|>= 0|units|no|policy value used that day
days_of_cover|decimal|R|0-999|days|no|= closing_on_hand / max(avg daily sales trailing 28d, 0.02), capped at 999
"""),
"promotion": ("Promotion header. Lifecycle is DRAFT > SCHEDULED > ACTIVE > ENDED, or CANCELLED from any pre-ended state.", ["promo_id"], """
promo_id|string|R|PROMO-2026-######|-|PK|sequential by start_date
promo_name|string|R|free text|-|no|non-empty
promo_type|string|R|enum:PROMO_TYPES|-|no|the stacking group
coupon_code|string|O|CPN######|-|unique|only for COUPON
scope_type|string|R|enum:SCOPE_TYPES|-|no|ALL for SITEWIDE, CATEGORY_BRAND for CATEGORY, SKU_LIST otherwise
scope_category|string|O|enum:CATEGORIES|-|no|only for CATEGORY_BRAND
scope_brand|string|O|enum:BRANDS|-|no|only for CATEGORY_BRAND
discount_type|string|R|enum:DISCOUNT_TYPES|-|no|AMOUNT only for COUPON
discount_value|decimal|R|> 0|fraction (PERCENT) or currency (AMOUNT)|no|PERCENT in (0,0.5]
start_date|date|R|ISO date|date|no|<= end_date
end_date|date|R|ISO date|date|no|planned end, inclusive
priority|int|R|1-5|-|no|tie-breaker, lower wins
created_date|date|R|ISO date|date|no|< start_date
status|string|R|enum:PROMO_STATUS|-|no|as of last simulated day; equals to_state of latest promotion_event
cancelled_date|date|O|ISO date|date|no|set iff status = CANCELLED; promo not active from this date
"""),
"promotion_rule": ("Eligibility / stacking rules attached to each promotion.", ["rule_id"], """
rule_id|string|R|RULE-2026-######-NN|-|PK|promo suffix + rule number
promo_id|string|R|-|-|no|FK promotion.promo_id
rule_type|string|R|enum:RULE_TYPES|-|no|in enum
rule_value|string|R|see README|-|no|MIN_MARGIN_PCT: number or PRODUCT (use product.min_margin_pct); EXCLUDES_GROUP: '|'-joined promo_types
"""),
"promotion_sku": ("Bridge: which SKUs each promotion covers (N:M).", ["promo_id", "sku"], """
promo_id|string|R|-|-|PK part|FK promotion.promo_id
sku|string|R|-|-|PK part|FK product.sku
"""),
"promotion_event": ("Promotion state-change history (append-only).", ["event_id"], """
event_id|string|R|PEV-2026-######|-|PK|sequential by event_date
promo_id|string|R|-|-|no|FK promotion.promo_id
event_date|date|R|ISO date|date|no|<= last simulated day
from_state|string|O|enum:PROMO_STATUS|-|no|null for the first event
to_state|string|R|enum:PROMO_STATUS|-|no|must be an allowed transition
actor|string|R|free text|-|no|user id or SYSTEM
"""),
"product_status_event": ("Product lifecycle history (append-only).", ["event_id"], """
event_id|string|R|PSE-2026-######|-|PK|sequential
sku|string|R|-|-|no|FK product.sku
event_date|date|R|ISO date|date|no|-
from_state|string|O|enum:LIFECYCLE|-|no|null for the first event
to_state|string|R|enum:LIFECYCLE|-|no|ACTIVE then optionally DISCONTINUED
reason|string|R|free text|-|no|-
"""),
"orders": ("Customer order lines (one SKU per row). Named 'orders' because ORDER is a SQL keyword.", ["order_id"], """
order_id|string|R|ORD-2026-######|-|PK|sequential by order_ts
order_ts|timestamp|R|ISO 8601|UTC|no|-
order_date|date|R|ISO date|date|no|= date(order_ts)
customer_id|string|R|CUST-######|-|no|synthetic, no personal data
channel|string|R|enum:CHANNELS|-|no|in enum
sku|string|R|-|-|no|FK product.sku
quantity|int|R|1-3|units|no|> 0; sum per sku/day = inventory units_sold
price_id|string|R|-|-|no|FK price_history (sku + order_date)
cost_id|string|R|-|-|no|FK cost_record in force on order_date
unit_list_price|decimal|R|> 0|currency|no|= price_history.list_price
unit_cost|decimal|R|> 0|currency/unit|no|= cost_record.unit_cost
gross_amount|decimal|R|> 0|currency|no|= quantity * unit_list_price
discount_amount|decimal|R|>= 0|currency|no|= SUM(order_promotion.line_discount_amount)
net_amount|decimal|R|> 0|currency|no|= gross_amount - discount_amount
cogs_amount|decimal|R|> 0|currency|no|= quantity * unit_cost
gross_margin_amount|decimal|R|-|currency|no|= net_amount - cogs_amount
margin_pct|decimal|R|-|fraction|no|= gross_margin_amount / net_amount (4 dp). Basis: AFTER discount
promo_count|int|R|0-3|-|no|= COUNT(order_promotion rows)
"""),
"order_promotion": ("Bridge: promotions applied to an order, in application order (N:M).", ["order_id", "promo_id"], """
order_id|string|R|-|-|PK part|FK orders.order_id
promo_id|string|R|-|-|PK part|FK promotion.promo_id
apply_seq|int|R|1-3|-|no|discounts are applied sequentially in this order
line_discount_amount|decimal|R|>= 0|currency|no|discount this promotion contributed to the order line
"""),
"price_decision": ("One row per pricing evaluation: inputs, candidate, guardrails, outcome. Append-only.", ["decision_id"], """
decision_id|string|R|DEC-2026-######|-|PK|sequential by decision_ts, then sku
sku|string|R|-|-|no|FK product.sku
decision_ts|timestamp|R|ISO 8601|UTC|no|00:30 on decision day; result effective that day
cost_id|string|R|-|-|no|FK cost_record in force
unit_cost|decimal|R|> 0|currency/unit|no|= cost_record.unit_cost
current_list_price|decimal|R|> 0|currency|no|price before the decision
price_floor|decimal|R|> 0|currency|no|= ceil_to_cent(unit_cost / (1 - min_margin_pct))
price_ceiling|decimal|R|> 0|currency|no|= product.price_ceiling
competitor_obs_id|string|O|-|-|no|FK competitor_observation; reference observation (may be unused)
competitor_price|decimal|O|> 0|currency|no|price of the reference observation
competitor_age_hours|decimal|O|-|hours|no|= decision_ts - observed_at
competitor_used|bool|R|0/1|-|no|1 iff the observation fed the candidate price
opening_on_hand|int|R|>= 0|units|no|closing stock of the previous day
avg_daily_sales_28d|decimal|R|>= 0|units/day|no|mean units_sold over trailing 28 days
days_of_cover|decimal|R|0-999|days|no|opening_on_hand / max(avg_daily_sales_28d, 0.02), cap 999
candidate_price|decimal|R|> 0|currency|no|price proposed by the rules before guardrails
guardrail_applied|string|R|enum:GUARDRAILS|-|no|binding guardrail (FLOOR/CEILING beat MAX_STEP)
final_price|decimal|R|> 0|currency|no|>= price_floor and <= price_ceiling
price_change_pct|decimal|R|-|fraction|no|= final_price / current_list_price - 1 (4 dp)
decision_status|string|R|enum:DECISION_STATUS|-|no|APPLIED iff final_price != current_list_price
reason_code|string|R|enum:REASON_CODES|-|no|explains the outcome
exception_code|string|O|enum:EXCEPTION_CODES|-|no|exception path taken, if any
margin_pct_at_final|decimal|R|-|fraction|no|= (final_price - unit_cost) / final_price; list basis
rule_version|string|R|PR-1.0|-|no|version of the documented rule set
"""),
"ground_truth": ("Separate label file for injected anomalies. NEVER used as an input feature.", ["gt_id"], """
gt_id|string|R|GT-######|-|PK|-
record_type|string|R|table name|-|no|table holding the labelled record
record_id|string|R|-|-|no|PK of the labelled record
issue_type|string|R|enum:ISSUE_TYPES|-|no|in enum
description|string|R|free text|-|no|what was injected
expected_outcome|string|R|free text|-|no|what a correct system should have done
"""),
}

FKS = [
    ("cost_record", "sku", "product", "sku"),
    ("price_history", "sku", "product", "sku"),
    ("price_history", "decision_id", "price_decision", "decision_id"),
    ("price_history", "cost_id", "cost_record", "cost_id"),
    ("competitor_observation", "sku", "product", "sku"),
    ("inventory_snapshot", "sku", "product", "sku"),
    ("promotion_rule", "promo_id", "promotion", "promo_id"),
    ("promotion_sku", "promo_id", "promotion", "promo_id"),
    ("promotion_sku", "sku", "product", "sku"),
    ("promotion_event", "promo_id", "promotion", "promo_id"),
    ("product_status_event", "sku", "product", "sku"),
    ("orders", "sku", "product", "sku"),
    ("orders", "price_id", "price_history", "price_id"),
    ("orders", "cost_id", "cost_record", "cost_id"),
    ("order_promotion", "order_id", "orders", "order_id"),
    ("order_promotion", "promo_id", "promotion", "promo_id"),
    ("price_decision", "sku", "product", "sku"),
    ("price_decision", "cost_id", "cost_record", "cost_id"),
    ("price_decision", "competitor_obs_id", "competitor_observation", "obs_id"),
]

# Load order that satisfies all FKs (parents first)
LOAD_ORDER = ["product", "cost_record", "competitor_observation", "promotion",
              "promotion_rule", "promotion_sku", "promotion_event", "product_status_event",
              "inventory_snapshot", "price_decision", "price_history", "orders",
              "order_promotion"]

RELATIONSHIPS = [
    ("product", "cost_record", "1:N", "mandatory", "one cost row per month; effective_from/effective_to; SUPERSEDED when replaced"),
    ("product", "price_history", "1:N", "mandatory", "one row per day"),
    ("product", "inventory_snapshot", "1:N", "mandatory", "one row per day"),
    ("product", "competitor_observation", "1:N", "optional", "2 of 3 competitors track each SKU"),
    ("product", "product_status_event", "1:N", "mandatory", "lifecycle history"),
    ("product", "price_decision", "1:N", "optional", "weekly review + cost-change days"),
    ("price_decision", "price_history", "1:N", "optional", "a decision explains at most one price change per row; manual overrides have none (anomaly)"),
    ("cost_record", "price_history", "1:N", "mandatory", "cost in force on that day"),
    ("cost_record", "price_decision", "1:N", "mandatory", "cost used for the decision"),
    ("competitor_observation", "price_decision", "1:N", "optional", "reference observation"),
    ("promotion", "promotion_rule", "1:N", "mandatory", "5 rules per promotion"),
    ("promotion", "promotion_event", "1:N", "mandatory", "lifecycle history"),
    ("promotion", "promotion_sku", "1:N", "mandatory", "bridge"),
    ("product", "promotion_sku", "1:N", "optional", "bridge"),
    ("promotion <-> product", "promotion_sku", "N:M", "-", "via promotion_sku"),
    ("price_history", "orders", "1:N", "mandatory", "price in force on order date"),
    ("orders", "order_promotion", "1:N", "optional", "0-3 promotions per order"),
    ("promotion", "order_promotion", "1:N", "optional", "bridge"),
    ("orders <-> promotion", "order_promotion", "N:M", "-", "via order_promotion"),
]


def _parse():
    tables = {}
    for name, (desc, pk, spec) in _SPEC.items():
        fields = []
        for line in spec.strip().splitlines():
            parts = line.split("|")
            # rule_value row contains '|' inside the rule text: re-join the tail
            if len(parts) > 7:
                parts = parts[:6] + ["|".join(parts[6:])]
            n, t, req, allowed, unit, uniq, rule = parts
            fields.append(dict(name=n, type=t, required=(req == "R"), allowed=allowed,
                               unit=unit, unique=uniq, rule=rule))
        tables[name] = dict(desc=desc, pk=pk, fields=fields)
    return tables


TABLES = _parse()


def columns(table):
    return [f["name"] for f in TABLES[table]["fields"]]
