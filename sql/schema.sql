-- Generated from schema.py. ANSI-style; runs on SQLite and PostgreSQL.

-- Master data. One row per sellable SKU.
CREATE TABLE product (
  sku VARCHAR(160) NOT NULL,
  product_name VARCHAR(160) NOT NULL,
  category VARCHAR(160) NOT NULL CHECK (category IN ('Electronics', 'Home & Kitchen', 'Apparel', 'Grocery', 'Beauty', 'Toys', 'Sports', 'Office', 'Pet', 'Garden')),
  brand VARCHAR(160) NOT NULL CHECK (brand IN ('Aurora', 'Nimbus', 'Verdant', 'Kestrel', 'Lumen', 'Orchid', 'Basalt', 'Cobalt', 'Meridian', 'Solstice', 'Tamarind', 'Zephyr')),
  launch_date DATE NOT NULL,
  lifecycle_state VARCHAR(160) NOT NULL CHECK (lifecycle_state IN ('ACTIVE', 'DISCONTINUED')),
  min_margin_pct DECIMAL(14,4) NOT NULL,
  initial_list_price DECIMAL(14,4) NOT NULL,
  price_ceiling DECIMAL(14,4) NOT NULL,
  lead_time_days INTEGER NOT NULL,
  PRIMARY KEY (sku)
);

-- Monthly cost history. One row per SKU per calendar month; new row each month, old row kept (SUPERSEDED).
CREATE TABLE cost_record (
  cost_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  unit_cost DECIMAL(14,4) NOT NULL,
  prev_unit_cost DECIMAL(14,4),
  change_pct DECIMAL(14,4),
  change_reason VARCHAR(160) CHECK (change_reason IN ('SUPPLIER_INCREASE', 'FREIGHT_SURCHARGE', 'FX_MOVE', 'SUPPLIER_DISCOUNT', 'VOLUME_REBATE')),
  status VARCHAR(160) NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
  PRIMARY KEY (cost_id),
  FOREIGN KEY (sku) REFERENCES product(sku)
);

-- Competitor price snapshots with source timestamp (observed_at) and ingestion timestamp.
CREATE TABLE competitor_observation (
  obs_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  competitor_id VARCHAR(160) NOT NULL CHECK (competitor_id IN ('COMP-A', 'COMP-B', 'COMP-C')),
  observed_at TIMESTAMP NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  competitor_price DECIMAL(14,4) NOT NULL,
  in_stock SMALLINT NOT NULL,
  source_type VARCHAR(160) NOT NULL CHECK (source_type IN ('API_FEED', 'SCRAPE', 'MANUAL_SHEET')),
  source_lag_hours DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (obs_id),
  FOREIGN KEY (sku) REFERENCES product(sku)
);

-- Promotion header. Lifecycle is DRAFT > SCHEDULED > ACTIVE > ENDED, or CANCELLED from any pre-ended state.
CREATE TABLE promotion (
  promo_id VARCHAR(160) NOT NULL,
  promo_name VARCHAR(160) NOT NULL,
  promo_type VARCHAR(160) NOT NULL CHECK (promo_type IN ('SITEWIDE', 'CATEGORY', 'COUPON', 'CLEARANCE')),
  coupon_code VARCHAR(160),
  scope_type VARCHAR(160) NOT NULL CHECK (scope_type IN ('ALL', 'CATEGORY_BRAND', 'SKU_LIST')),
  scope_category VARCHAR(160) CHECK (scope_category IN ('Electronics', 'Home & Kitchen', 'Apparel', 'Grocery', 'Beauty', 'Toys', 'Sports', 'Office', 'Pet', 'Garden')),
  scope_brand VARCHAR(160) CHECK (scope_brand IN ('Aurora', 'Nimbus', 'Verdant', 'Kestrel', 'Lumen', 'Orchid', 'Basalt', 'Cobalt', 'Meridian', 'Solstice', 'Tamarind', 'Zephyr')),
  discount_type VARCHAR(160) NOT NULL CHECK (discount_type IN ('PERCENT', 'AMOUNT')),
  discount_value DECIMAL(14,4) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  priority INTEGER NOT NULL,
  created_date DATE NOT NULL,
  status VARCHAR(160) NOT NULL CHECK (status IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')),
  cancelled_date DATE,
  PRIMARY KEY (promo_id)
);

-- Eligibility / stacking rules attached to each promotion.
CREATE TABLE promotion_rule (
  rule_id VARCHAR(160) NOT NULL,
  promo_id VARCHAR(160) NOT NULL,
  rule_type VARCHAR(160) NOT NULL CHECK (rule_type IN ('MIN_STOCK_UNITS', 'MIN_MARGIN_PCT', 'MAX_TOTAL_DISCOUNT_PCT', 'EXCLUDES_GROUP', 'MAX_STACK_COUNT')),
  rule_value VARCHAR(160) NOT NULL,
  PRIMARY KEY (rule_id),
  FOREIGN KEY (promo_id) REFERENCES promotion(promo_id)
);

-- Bridge: which SKUs each promotion covers (N:M).
CREATE TABLE promotion_sku (
  promo_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  PRIMARY KEY (promo_id, sku),
  FOREIGN KEY (promo_id) REFERENCES promotion(promo_id),
  FOREIGN KEY (sku) REFERENCES product(sku)
);

-- Promotion state-change history (append-only).
CREATE TABLE promotion_event (
  event_id VARCHAR(160) NOT NULL,
  promo_id VARCHAR(160) NOT NULL,
  event_date DATE NOT NULL,
  from_state VARCHAR(160) CHECK (from_state IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')),
  to_state VARCHAR(160) NOT NULL CHECK (to_state IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')),
  actor VARCHAR(160) NOT NULL,
  PRIMARY KEY (event_id),
  FOREIGN KEY (promo_id) REFERENCES promotion(promo_id)
);

-- Product lifecycle history (append-only).
CREATE TABLE product_status_event (
  event_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  event_date DATE NOT NULL,
  from_state VARCHAR(160) CHECK (from_state IN ('ACTIVE', 'DISCONTINUED')),
  to_state VARCHAR(160) NOT NULL CHECK (to_state IN ('ACTIVE', 'DISCONTINUED')),
  reason VARCHAR(160) NOT NULL,
  PRIMARY KEY (event_id),
  FOREIGN KEY (sku) REFERENCES product(sku)
);

-- Daily stock position per SKU.
CREATE TABLE inventory_snapshot (
  snapshot_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  snapshot_date DATE NOT NULL,
  opening_on_hand INTEGER NOT NULL,
  units_received INTEGER NOT NULL,
  units_sold INTEGER NOT NULL,
  units_unfulfilled INTEGER NOT NULL,
  closing_on_hand INTEGER NOT NULL,
  stockout_flag SMALLINT NOT NULL,
  reorder_point INTEGER NOT NULL,
  days_of_cover DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (snapshot_id),
  FOREIGN KEY (sku) REFERENCES product(sku)
);

-- One row per pricing evaluation: inputs, candidate, guardrails, outcome. Append-only.
CREATE TABLE price_decision (
  decision_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  decision_ts TIMESTAMP NOT NULL,
  cost_id VARCHAR(160) NOT NULL,
  unit_cost DECIMAL(14,4) NOT NULL,
  current_list_price DECIMAL(14,4) NOT NULL,
  price_floor DECIMAL(14,4) NOT NULL,
  price_ceiling DECIMAL(14,4) NOT NULL,
  competitor_obs_id VARCHAR(160),
  competitor_price DECIMAL(14,4),
  competitor_age_hours DECIMAL(14,4),
  competitor_used SMALLINT NOT NULL,
  opening_on_hand INTEGER NOT NULL,
  avg_daily_sales_28d DECIMAL(14,4) NOT NULL,
  days_of_cover DECIMAL(14,4) NOT NULL,
  candidate_price DECIMAL(14,4) NOT NULL,
  guardrail_applied VARCHAR(160) NOT NULL CHECK (guardrail_applied IN ('NONE', 'MAX_STEP', 'FLOOR', 'CEILING')),
  final_price DECIMAL(14,4) NOT NULL,
  price_change_pct DECIMAL(14,4) NOT NULL,
  decision_status VARCHAR(160) NOT NULL CHECK (decision_status IN ('APPLIED', 'NO_CHANGE')),
  reason_code VARCHAR(160) NOT NULL CHECK (reason_code IN ('COMPETITOR_MATCH', 'LOW_STOCK_INCREASE', 'OVERSTOCK_MARKDOWN', 'COST_PASS_THROUGH', 'FLOOR_ENFORCEMENT', 'STOCKOUT_HOLD', 'HOLD_NO_SIGNAL')),
  exception_code VARCHAR(160) CHECK (exception_code IN ('STALE_COMPETITOR_IGNORED', 'COMPETITOR_OUT_OF_STOCK', 'NO_COMPETITOR_DATA', 'STOCKOUT_HOLD')),
  margin_pct_at_final DECIMAL(14,4) NOT NULL,
  rule_version VARCHAR(160) NOT NULL,
  PRIMARY KEY (decision_id),
  FOREIGN KEY (sku) REFERENCES product(sku),
  FOREIGN KEY (cost_id) REFERENCES cost_record(cost_id),
  FOREIGN KEY (competitor_obs_id) REFERENCES competitor_observation(obs_id)
);

-- Daily list price per SKU. Append-only; one row per SKU per day.
CREATE TABLE price_history (
  price_id VARCHAR(160) NOT NULL,
  sku VARCHAR(160) NOT NULL,
  price_date DATE NOT NULL,
  list_price DECIMAL(14,4) NOT NULL,
  prev_list_price DECIMAL(14,4),
  is_price_change SMALLINT NOT NULL,
  change_reason VARCHAR(160) CHECK (change_reason IN ('COMPETITOR_MATCH', 'LOW_STOCK_INCREASE', 'OVERSTOCK_MARKDOWN', 'COST_PASS_THROUGH', 'FLOOR_ENFORCEMENT', 'STOCKOUT_HOLD', 'HOLD_NO_SIGNAL', 'INITIAL_LISTING')),
  decision_id VARCHAR(160),
  cost_id VARCHAR(160) NOT NULL,
  unit_cost DECIMAL(14,4) NOT NULL,
  price_floor DECIMAL(14,4) NOT NULL,
  margin_pct DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (price_id),
  FOREIGN KEY (sku) REFERENCES product(sku),
  FOREIGN KEY (decision_id) REFERENCES price_decision(decision_id),
  FOREIGN KEY (cost_id) REFERENCES cost_record(cost_id)
);

-- Customer order lines (one SKU per row). Named 'orders' because ORDER is a SQL keyword.
CREATE TABLE orders (
  order_id VARCHAR(160) NOT NULL,
  order_ts TIMESTAMP NOT NULL,
  order_date DATE NOT NULL,
  customer_id VARCHAR(160) NOT NULL,
  channel VARCHAR(160) NOT NULL CHECK (channel IN ('WEB', 'APP', 'STORE')),
  sku VARCHAR(160) NOT NULL,
  quantity INTEGER NOT NULL,
  price_id VARCHAR(160) NOT NULL,
  cost_id VARCHAR(160) NOT NULL,
  unit_list_price DECIMAL(14,4) NOT NULL,
  unit_cost DECIMAL(14,4) NOT NULL,
  gross_amount DECIMAL(14,4) NOT NULL,
  discount_amount DECIMAL(14,4) NOT NULL,
  net_amount DECIMAL(14,4) NOT NULL,
  cogs_amount DECIMAL(14,4) NOT NULL,
  gross_margin_amount DECIMAL(14,4) NOT NULL,
  margin_pct DECIMAL(14,4) NOT NULL,
  promo_count INTEGER NOT NULL,
  PRIMARY KEY (order_id),
  FOREIGN KEY (sku) REFERENCES product(sku),
  FOREIGN KEY (price_id) REFERENCES price_history(price_id),
  FOREIGN KEY (cost_id) REFERENCES cost_record(cost_id)
);

-- Bridge: promotions applied to an order, in application order (N:M).
CREATE TABLE order_promotion (
  order_id VARCHAR(160) NOT NULL,
  promo_id VARCHAR(160) NOT NULL,
  apply_seq INTEGER NOT NULL,
  line_discount_amount DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (order_id, promo_id),
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (promo_id) REFERENCES promotion(promo_id)
);

-- Separate label file for injected anomalies. NEVER used as an input feature.
CREATE TABLE ground_truth (
  gt_id VARCHAR(160) NOT NULL,
  record_type VARCHAR(160) NOT NULL,
  record_id VARCHAR(160) NOT NULL,
  issue_type VARCHAR(160) NOT NULL CHECK (issue_type IN ('PRICE_BELOW_FLOOR', 'PROMOTION_STACK_VIOLATION', 'STALE_OBSERVATION_AS_CURRENT', 'MARGIN_BEFORE_DISCOUNT', 'PRICE_CHANGE_LACKS_REASON')),
  description VARCHAR(160) NOT NULL,
  expected_outcome VARCHAR(160) NOT NULL,
  PRIMARY KEY (gt_id)
);

CREATE INDEX ix_price_history_sku_date ON price_history(sku, price_date);
CREATE INDEX ix_orders_sku_date ON orders(sku, order_date);
CREATE INDEX ix_decision_sku ON price_decision(sku, decision_ts);
CREATE INDEX ix_obs_sku ON competitor_observation(sku, ingested_at);
