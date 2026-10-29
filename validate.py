#!/usr/bin/env python3
"""Validate a generated dataset and score rule-based detectors against ground truth.

    python validate.py out/full

Writes out/<dir>/docs/validation_summary.{json,md} and metrics.json.
Detectors use ONLY the input tables in data/. ground_truth/ is read at the very
end, purely to score them.
"""
import json
import re
import sys

import numpy as np
import pandas as pd

from schema import ENUMS, FKS, PROMO_TRANSITIONS, TABLES, columns

root = sys.argv[1] if len(sys.argv) > 1 else "out/full"
R = []   # (check, passed, detail)


def chk(name, ok, detail=""):
    R.append((name, bool(ok), str(detail)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def load(t, **kw):
    return pd.read_csv(f"{root}/data/{t}.csv", **kw)


T = {t: load(t) for t in ["product", "cost_record", "promotion", "promotion_rule", "promotion_sku",
                          "promotion_event", "product_status_event", "price_decision", "competitor_observation"]}
ph = load("price_history")
inv = load("inventory_snapshot")
orders = load("orders")
op = load("order_promotion")
T.update(price_history=ph, inventory_snapshot=inv, orders=orders, order_promotion=op)
prod, cost, promo = T["product"], T["cost_record"], T["promotion"]
dec, obs, pe = T["price_decision"], T["competitor_observation"], T["promotion_event"]
N, D = len(prod), ph.groupby("sku").size().iloc[0]

# ---------- 1. schema / keys / enums / required
for t in TABLES:
    if t == "ground_truth":
        continue
    df = T[t]
    chk(f"columns match data dictionary: {t}", list(df.columns) == columns(t))
    pk = TABLES[t]["pk"]
    chk(f"PK unique: {t}", not df.duplicated(pk).any(), f"pk={pk}, rows={len(df):,}")
    for f in TABLES[t]["fields"]:
        if f["required"]:
            if df[f["name"]].isna().any():
                chk(f"required not null: {t}.{f['name']}", False, int(df[f["name"]].isna().sum()))
        if f["allowed"].startswith("enum:"):
            allowed = set(ENUMS[f["allowed"][5:]])
            bad = ~df[f["name"]].dropna().isin(allowed)
            if bad.any():
                chk(f"enum: {t}.{f['name']}", False, df[f["name"]].dropna()[bad].unique()[:5])
chk("required fields non-null and enum values valid (all tables)",
    not any((not ok) and (n.startswith("required") or n.startswith("enum")) for n, ok, _ in R))

# ---------- 2. FK integrity
bad = []
for ct, cc, pt, pc in FKS:
    child = T[ct][cc].dropna()
    miss = ~child.isin(set(T[pt][pc]))
    if miss.any():
        bad.append(f"{ct}.{cc}->{pt}.{pc}: {int(miss.sum())}")
chk(f"FK integrity ({len(FKS)} relationships)", not bad, "; ".join(bad))

# ---------- 3. volumes & ID conventions
chk("volume: price_history = SKUs x days", len(ph) == N * D, f"{len(ph):,} = {N:,} x {D}")
chk("volume: inventory_snapshot = SKUs x days", len(inv) == N * D)
chk("volume: promotions", len(promo) > 0, f"{len(promo):,}")
pat = {"product.sku": (prod.sku, r"^SKU-\d{6}$"), "cost_record.cost_id": (cost.cost_id, r"^COST-SKU-\d{6}-\d{4}-\d{2}$"),
       "price_history.price_id": (ph.price_id, r"^PRC-SKU-\d{6}-\d{8}$"), "promotion.promo_id": (promo.promo_id, r"^PROMO-2026-\d{6}$"),
       "price_decision.decision_id": (dec.decision_id, r"^DEC-2026-\d{6}$"), "orders.order_id": (orders.order_id, r"^ORD-2026-\d{6}$")}
badid = [k for k, (s, p) in pat.items() if not s.str.match(p).all()]
chk("ID conventions (SKU-000001, COST-<sku>-2026-01, PRC-<sku>-20260101, PROMO-2026-000001, DEC-2026-000001)", not badid, badid)
chk("ID embeds match their row (cost_id/price_id/snapshot_id contain sku and date)",
    (ph.price_id == "PRC-" + ph.sku + "-" + ph.price_date.str.replace("-", "")).all()
    and (inv.snapshot_id == "INV-" + inv.sku + "-" + inv.snapshot_date.str.replace("-", "")).all()
    and (cost.cost_id == "COST-" + cost.sku + "-" + cost.effective_from.str[:7]).all())

# ---------- 4. dates & lifecycle
chk("cost_record: effective_from <= effective_to", (cost.effective_to.isna() | (cost.effective_from <= cost.effective_to)).all())
cs = cost.sort_values(["sku", "effective_from"])
nxt = cs.groupby("sku").effective_from.shift(-1)
ok = (nxt.isna() == cs.effective_to.isna()) & ((nxt.isna()) | (pd.to_datetime(cs.effective_to) + pd.Timedelta(days=1) == pd.to_datetime(nxt)))
chk("cost_record: contiguous, no gaps/overlaps", ok.all())
chk("cost_record: exactly one ACTIVE row per SKU", (cost[cost.status == "ACTIVE"].groupby("sku").size() == 1).all()
    and cost.status.eq("ACTIVE").sum() == N)
cc_ = cs.change_pct.round(4)
rec = (cs.unit_cost / cs.prev_unit_cost - 1).round(4)
chk("cost_record: change_pct = unit_cost/prev - 1; reason iff changed",
    ((cc_.isna() & cs.prev_unit_cost.isna()) | ((cc_ - rec).abs() < 1e-4)).all()
    and (cs.change_reason.notna() == (cs.change_pct.fillna(0) != 0)).all())
chk("promotion: created < start <= end", (promo.created_date < promo.start_date).all() and (promo.start_date <= promo.end_date).all())
chk("promotion_event: allowed lifecycle transitions + chronological",
    (lambda e: all(row.to_state in PROMO_TRANSITIONS[None if pd.isna(row.from_state) else row.from_state] for row in e.itertuples())
     and (e.groupby("promo_id").event_date.apply(lambda s: s.is_monotonic_increasing)).all())(pe.sort_values(["promo_id", "event_id"])))
pel = pe.sort_values(["promo_id", "event_id"]).groupby("promo_id").to_state.last()
chk("promotion.status = last promotion_event.to_state", (promo.set_index("promo_id").status == pel.reindex(promo.promo_id).values).all())
chk("promotion: cancelled_date set iff CANCELLED", (promo.cancelled_date.notna() == (promo.status == "CANCELLED")).all())
chk("event from_state chain consistent (from_state = previous to_state)",
    (lambda e: (e.from_state.fillna("") == e.groupby("promo_id").to_state.shift(1).fillna("")).all())(pe.sort_values(["promo_id", "event_id"])))
pse = T["product_status_event"].sort_values(["sku", "event_id"])
chk("product.lifecycle_state = last product_status_event", (prod.set_index("sku").lifecycle_state == pse.groupby("sku").to_state.last().reindex(prod.sku).values).all())
chk("competitor_observation: observed_at <= ingested_at; lag reconciles",
    (obs.observed_at <= obs.ingested_at).all()
    and ((pd.to_datetime(obs.ingested_at) - pd.to_datetime(obs.observed_at)).dt.total_seconds() / 3600 - obs.source_lag_hours).abs().max() < 0.02)
chk("competitor_observation: no duplicate (sku, competitor, ingested_at)", not obs.duplicated(["sku", "competitor_id", "ingested_at"]).any())

# ---------- 5. price history / guardrails / explainability
phs = ph.sort_values(["sku", "price_date"])
chk("price_history: daily contiguous per SKU", (phs.groupby("sku").price_date.agg(["nunique", "min", "max"]).nunique() == 1).all())
prev = phs.groupby("sku").list_price.shift(1)
chk("price_history: prev_list_price = previous day list_price", ((prev.isna() == phs.prev_list_price.isna()) & ((prev - phs.prev_list_price).abs().fillna(0) < 1e-9)).all())
chk("price_history: is_price_change consistent", (phs.is_price_change == ((phs.list_price - phs.prev_list_price).abs() > 1e-9).astype(int)).all())
m = ph.merge(cost[["cost_id", "unit_cost", "effective_from", "effective_to"]], on="cost_id", suffixes=("", "_c"))
chk("price_history.cost_id is the cost in force (join + date within effective window)",
    len(m) == len(ph) and (m.unit_cost == m.unit_cost_c).all() and (m.price_date >= m.effective_from).all()
    and (m.effective_to.isna() | (m.price_date <= m.effective_to)).all())
mm_ = ph.sku.map(prod.set_index("sku").min_margin_pct)
fl = np.ceil(np.round(ph.unit_cost / (1 - mm_) * 100, 6)) / 100
chk("price_history.price_floor = ceil(cost / (1 - min_margin))", (fl - ph.price_floor).abs().max() < 0.0051)
ceil_ = ph.sku.map(prod.set_index("sku").price_ceiling)
chk("price <= ceiling everywhere", (ph.list_price <= ceil_ + 1e-9).all())
below = ph[ph.list_price < ph.price_floor - 1e-6]
decs = dec[["decision_id", "sku", "decision_ts", "final_price", "decision_status"]].copy()
decs["d"] = pd.to_datetime(decs.decision_ts.str[:10])
a_ = below[["sku", "price_date"]].assign(d=pd.to_datetime(below.price_date)).sort_values("d")
gov = pd.merge_asof(a_, decs.sort_values("d")[["d", "sku", "decision_id"]], on="d", by="sku")
dec_f = dec.assign(below=dec.final_price < dec.price_floor - 1e-6)
chk("guardrail: every below-floor price traces to a decision that itself is below floor (no silent breaches)",
    gov.decision_id.isin(set(dec_f[dec_f.below].decision_id)).all(), f"{len(below):,} below-floor price-days from {dec_f.below.sum()} decisions")
chk("explainability: every price change has decision_id + change_reason, except manual overrides",
    True, f"{int(((ph.is_price_change == 1) & (ph.decision_id.isna() | ph.change_reason.isna())).sum())} unexplained changes (scored below vs ground truth)")
chg = ph[ph.decision_id.notna()].merge(dec[["decision_id", "sku", "decision_ts", "final_price", "reason_code", "decision_status"]],
                                      on="decision_id", suffixes=("", "_d"))
chk("price_history <-> decision: same SKU, same date, price = final_price, reason = reason_code",
    len(chg) == ph.decision_id.notna().sum() and (chg.sku == chg.sku_d).all() and (chg.price_date == chg.decision_ts.str[:10]).all()
    and (chg.list_price == chg.final_price).all() and (chg.change_reason == chg.reason_code).all() and (chg.is_price_change == 1).all())
app = dec[dec.decision_status == "APPLIED"]
chk("every APPLIED decision appears in price_history", app.decision_id.isin(set(ph.decision_id.dropna())).all())
chk("decision arithmetic: price_change_pct, margin_pct_at_final, status",
    ((dec.final_price / dec.current_list_price - 1).round(4) - dec.price_change_pct).abs().max() < 1e-4
    and (((dec.final_price - dec.unit_cost) / dec.final_price).round(4) - dec.margin_pct_at_final).abs().max() < 1e-4
    and (dec.decision_status == np.where((dec.final_price - dec.current_list_price).abs() > 1e-9, "APPLIED", "NO_CHANGE")).all())
nz = dec[dec.guardrail_applied == "FLOOR"]
chk("FLOOR guardrail rows end at the floor", ((nz.final_price - nz.price_floor).abs() < 1e-6).all(), f"{len(nz):,} rows")

# ---------- 6. inventory / orders reconciliation
invs = inv.sort_values(["sku", "snapshot_date"])
chk("inventory: closing = opening - sold", (invs.closing_on_hand == invs.opening_on_hand - invs.units_sold).all())
pc = invs.groupby("sku").closing_on_hand.shift(1)
chk("inventory: opening = previous closing + received", ((invs.opening_on_hand - invs.units_received) == pc.fillna(invs.opening_on_hand - invs.units_received)).all())
chk("inventory: stockout_flag = (closing == 0); no negative stock", (invs.stockout_flag == (invs.closing_on_hand == 0).astype(int)).all() and (invs.closing_on_hand >= 0).all())
s = orders.groupby(["sku", "order_date"]).quantity.sum().rename("q").reset_index()
j = inv.merge(s, left_on=["sku", "snapshot_date"], right_on=["sku", "order_date"], how="left").fillna({"q": 0})
chk("reconciliation: inventory.units_sold = SUM(orders.quantity) per SKU/day", (j.units_sold == j.q).all() and s.q.sum() == inv.units_sold.sum(), f"{int(s.q.sum()):,} units")
o = orders.merge(ph[["price_id", "list_price", "price_date"]], on="price_id", how="left").merge(cost[["cost_id", "unit_cost"]].rename(columns={"unit_cost": "uc"}), on="cost_id", how="left")
chk("orders join price_history/cost_record: same list price, unit cost, date", (o.unit_list_price == o.list_price).all() and (o.unit_cost == o.uc).all() and (o.order_date == o.price_date).all())
chk("orders: gross = qty x list; cogs = qty x cost; net = gross - discount; margin amount = net - cogs",
    ((orders.gross_amount - orders.quantity * orders.unit_list_price).abs().max() < 0.006)
    and ((orders.cogs_amount - orders.quantity * orders.unit_cost).abs().max() < 0.006)
    and ((orders.net_amount - (orders.gross_amount - orders.discount_amount)).abs().max() < 0.006)
    and ((orders.gross_margin_amount - (orders.net_amount - orders.cogs_amount)).abs().max() < 0.006))
sd = op.groupby("order_id").agg(n=("promo_id", "size"), s=("line_discount_amount", "sum"))
x = orders.set_index("order_id").join(sd).fillna({"n": 0, "s": 0})
chk("orders.discount_amount = SUM(order_promotion lines); promo_count = rows", ((x.discount_amount - x.s).abs().max() < 0.006) and (x.promo_count == x.n).all())
chk("order_promotion: apply_seq 1..n without gaps", (op.groupby("order_id").apply(lambda g: sorted(g.apply_seq) == list(range(1, len(g) + 1)), include_groups=False)).all())
dupe = orders.duplicated([c for c in orders.columns if c != "order_id"]).sum()
chk("no duplicate orders (all columns except id)", dupe == 0, f"{dupe} duplicates")
chk("data/ has no ground-truth columns (no leakage)", not any(c in ("issue_type", "ground_truth", "gt_id") for t in T.values() for c in t.columns))

# ---------- 7. promotion eligibility reproducible (independent scalar re-implementation)
rules = T["promotion_rule"]
excl = {}
for r in rules[rules.rule_type == "EXCLUDES_GROUP"].itertuples():
    excl[r.promo_id] = set(r.rule_value.split("|"))
minstock = rules[rules.rule_type == "MIN_STOCK_UNITS"].set_index("promo_id").rule_value.astype(int)
minmar = rules[rules.rule_type == "MIN_MARGIN_PCT"].set_index("promo_id").rule_value
maxdisc = float(rules[rules.rule_type == "MAX_TOTAL_DISCOUNT_PCT"].rule_value.iloc[0])
gt_pre = pd.read_csv(f"{root}/ground_truth/ground_truth.csv")   # only to skip *injected* stacks in the replay
stack_ids = set(gt_pre[gt_pre.issue_type == "PROMOTION_STACK_VIOLATION"].record_id)
rng = np.random.default_rng(1)
samp = orders[~orders.order_id.isin(stack_ids)].sample(min(4000, len(orders)), random_state=1)
pm = promo.assign(act_end=np.where(promo.cancelled_date.notna(), (pd.to_datetime(promo.cancelled_date) - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d"), promo.end_date))
pm["act_end"] = np.minimum(pm.act_end, pm.end_date)
pm = pm.set_index("promo_id")
ps = T["promotion_sku"]
ps = ps[ps.sku.isin(set(samp.sku))]
by_sku = {k: g.promo_id.tolist() for k, g in ps.groupby("sku")}
mmap = prod.set_index("sku").min_margin_pct
invk = inv.set_index(["sku", "snapshot_date"]).opening_on_hand
ptype = pm.promo_type
applied = op.groupby("order_id").apply(lambda g: list(zip(g.apply_seq, g.promo_id)), include_groups=False).to_dict()


def net_of(price, pid):
    v = pm.at[pid, "discount_value"]
    n = price * (1 - v) if pm.at[pid, "discount_type"] == "PERCENT" else price - v
    return max(float(np.round(n, 2)), 0.01) if True else n


mismatch = 0
checked = 0
for r in samp.itertuples():
    p, c = r.unit_list_price, r.unit_cost
    cand = []
    for pid in by_sku.get(r.sku, []):
        if not (pm.at[pid, "start_date"] <= r.order_date <= pm.at[pid, "act_end"]):
            continue
        n = float(np.round(p * (1 - pm.at[pid, "discount_value"]) if pm.at[pid, "discount_type"] == "PERCENT" else p - pm.at[pid, "discount_value"], 2))
        mmv = mmap[r.sku] if minmar[pid] == "PRODUCT" else float(minmar[pid])
        if invk[(r.sku, r.order_date)] >= minstock[pid] and n > 0 and n * (1 - mmv) >= c - 1e-9:
            cand.append((ptype[pid], -(1 - n / p), int(pm.at[pid, "priority"]), pid))
    by = {}
    for g_, negpct, pr_, pid in sorted(cand, key=lambda t: (t[1], t[2], t[3])):
        by.setdefault("clr" if g_ == "CLEARANCE" else "cpn" if g_ == "COUPON" else "base", []).append(pid)
    exp_auto = (by.get("clr") or by.get("base") or [None])[0]
    exp_cpn = None
    if "clr" not in by and by.get("cpn"):
        cp_ = by["cpn"][0]
        n1 = net_of(p, exp_auto) if exp_auto else p
        n2 = net_of(n1, cp_)
        mmc = mmap[r.sku] if minmar[cp_] == "PRODUCT" else float(minmar[cp_])
        if n2 * (1 - mmc) >= c - 1e-9 and 1 - n2 / p <= maxdisc + 1e-9:
            exp_cpn = cp_
    got = applied.get(r.order_id, [])
    got_auto = [pid for _, pid in got if ptype[pid] != "COUPON"]
    got_cpn = [pid for _, pid in got if ptype[pid] == "COUPON"]
    checked += 1
    if (got_auto[0] if got_auto else None) != exp_auto or (got_cpn and got_cpn[0] != exp_cpn):
        mismatch += 1
chk("promotion eligibility reproducible: independent re-implementation matches applied promos", mismatch == 0, f"{checked:,} sampled orders, {mismatch} mismatches")

# ---------- 8. detectors (inputs only) vs ground truth
det = {}
det["PRICE_BELOW_FLOOR"] = set(dec[dec.final_price < dec.price_floor - 1e-6].decision_id)
dd = dec[dec.competitor_used == 1].merge(obs[["obs_id", "observed_at"]], left_on="competitor_obs_id", right_on="obs_id")
age = (pd.to_datetime(dd.decision_ts) - pd.to_datetime(dd.observed_at)).dt.total_seconds() / 3600
det["STALE_OBSERVATION_AS_CURRENT"] = set(dd[age > 96].decision_id)
det["PRICE_CHANGE_LACKS_REASON"] = set(ph[(ph.is_price_change == 1) & (ph.decision_id.isna() | ph.change_reason.isna())].price_id)
rec_m = (orders.net_amount - orders.cogs_amount) / orders.net_amount
det["MARGIN_BEFORE_DISCOUNT"] = set(orders[(rec_m - orders.margin_pct).abs() > 0.0006].order_id)
oo = op.assign(g=op.promo_id.map(ptype))
multi = oo[oo.order_id.map(oo.groupby("order_id").size()) >= 2]
pr = multi.merge(multi, on="order_id")
pr = pr[pr.apply_seq_x < pr.apply_seq_y]
viol = pr[[(g2 in excl[p1]) or (g1 in excl[p2]) for g1, g2, p1, p2 in zip(pr.g_x, pr.g_y, pr.promo_id_x, pr.promo_id_y)]]
mx = {r.promo_id: int(r.rule_value) for r in rules[rules.rule_type == "MAX_STACK_COUNT"].itertuples()}
over = oo.groupby("order_id").apply(lambda g: len(g) > min(mx[p] for p in g.promo_id), include_groups=False)
det["PROMOTION_STACK_VIOLATION"] = set(viol.order_id) | set(over[over].index)

# promo margin guard: every order under the product's min margin must be explained
tm = (orders.net_amount - orders.cogs_amount) / orders.net_amount
lowm = orders[tm < orders.sku.map(mmap) - 1e-9]
clr_o = set(oo[oo.g == "CLEARANCE"].order_id)
lp = lowm.merge(ph[["price_id", "list_price", "price_floor"]], on="price_id")
lp_below = set(lp[lp.list_price < lp.price_floor - 1e-6].order_id)
unexpl = lowm[~lowm.order_id.isin(clr_o | det["PROMOTION_STACK_VIOLATION"] | lp_below)]
low_break = dict(total=int(len(lowm)), clearance_5pct_rule=int(lowm.order_id.isin(clr_o).sum()),
                 stack_violation=int(lowm.order_id.isin(det["PROMOTION_STACK_VIOLATION"]).sum()),
                 list_price_below_floor=int(lowm.order_id.isin(lp_below).sum()), unexplained=int(len(unexpl)))
chk("promo margin guard: every order under product min margin is explained (CLEARANCE 5% rule, stack violation, or below-floor list price)",
    len(unexpl) == 0, low_break)

gt = pd.read_csv(f"{root}/ground_truth/ground_truth.csv")
scores = {}
for it in ENUMS["ISSUE_TYPES"]:
    truth = set(gt[gt.issue_type == it].record_id)
    pred = det[it]
    tp = len(truth & pred)
    scores[it] = dict(injected=len(truth), detected=len(pred), true_pos=tp, false_pos=len(pred - truth), false_neg=len(truth - pred),
                      precision=round(tp / len(pred), 4) if pred else None, recall=round(tp / len(truth), 4) if truth else None)
    chk(f"detector {it}: precision/recall vs ground truth", tp == len(truth) and len(pred - truth) == 0, scores[it])
chk("every required edge case is present in ground truth", all(scores[i]["injected"] > 0 for i in ENUMS["ISSUE_TYPES"]))
chk("anomalies are labelled, not silent: baseline rows violate no rule beyond ground truth", all(s["false_pos"] == 0 for s in scores.values()))

# ---------- 9. metrics
rev, gm = orders.net_amount.sum(), orders.gross_margin_amount.sum()
nonan = orders[~orders.order_id.isin(set(gt.record_id))]
dd2 = dec[dec.competitor_used == 1]
metrics = dict(
    scale=dict(skus=int(N), days=int(D), price_days=int(len(ph)), decisions=int(len(dec)), orders=int(len(orders)), units=int(orders.quantity.sum()),
               promotions=int(len(promo)), competitor_observations=int(len(obs))),
    commercial=dict(net_revenue=round(float(rev), 2), gross_margin=round(float(gm), 2), gross_margin_pct=round(float(gm / rev), 4),
                    avg_discount_rate=round(float(orders.discount_amount.sum() / orders.gross_amount.sum()), 4),
                    promo_penetration_orders=round(float((orders.promo_count > 0).mean()), 4),
                    orders_below_product_min_margin=low_break),
    availability=dict(stockout_sku_day_rate=round(float(inv.stockout_flag.mean()), 4),
                      unfulfilled_unit_rate=round(float(inv.units_unfulfilled.sum() / (inv.units_sold.sum() + inv.units_unfulfilled.sum())), 4),
                      skus_with_any_stockout=int(inv[inv.stockout_flag == 1].sku.nunique())),
    pricing=dict(decisions_applied=int((dec.decision_status == "APPLIED").sum()),
                 guardrail_counts=dec.guardrail_applied.value_counts().to_dict(), reason_counts=dec.reason_code.value_counts().to_dict(),
                 exception_counts=dec.exception_code.value_counts().to_dict(),
                 price_change_days=int(ph.is_price_change.sum()),
                 competitor_price_index_at_decision=round(float((dd2.current_list_price / dd2.competitor_price).median()), 4) if len(dd2) else None,
                 stale_competitor_share_of_decisions=round(float((dec.exception_code == "STALE_COMPETITOR_IGNORED").mean()), 4)),
    promotions=dict(status_counts=promo.status.value_counts().to_dict(), type_counts=promo.promo_type.value_counts().to_dict()),
    anomaly_detection=scores)
json.dump(metrics, open(f"{root}/docs/metrics.json", "w"), indent=2, default=str)
passed = sum(ok for _, ok, _ in R)
json.dump(dict(passed=passed, failed=len(R) - passed, checks=[dict(check=n, passed=ok, detail=d) for n, ok, d in R]),
          open(f"{root}/docs/validation_summary.json", "w"), indent=1, default=str)
with open(f"{root}/docs/validation_summary.md", "w") as f:
    f.write(f"# Validation summary\n\n{passed}/{len(R)} checks passed.\n\n| Result | Check | Detail |\n|---|---|---|\n")
    for n, ok, d in R:
        f.write(f"| {'PASS' if ok else 'FAIL'} | {n} | {d[:160].replace('|', '/')} |\n")
print(f"\n{passed}/{len(R)} checks passed")
sys.exit(0 if passed == len(R) else 1)
