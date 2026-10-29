#!/usr/bin/env python3
"""Pricing & promotion simulation - synthetic data generator.

    python generate.py --skus 5000 --days 180 --promos 2000 --seed 20261022 --out out/full

Same code for starter and full data; only --skus/--days/--promos change.
All outcomes (stock, orders, margins, promo applications, statuses) are derived
by a day-by-day simulation from the documented rules. Anomalies are injected
*inside* the simulation as labelled rule bypasses, so downstream rows stay
consistent, and every injection is written to ground_truth.csv.
"""
import argparse
import hashlib
import json
import os
import time

import numpy as np
import pandas as pd

from schema import ENUMS, TABLES, columns

# ----------------------------------------------------------------- config
CATS = {  # median_cost, min_margin_lo, min_margin_hi, elasticity_mean, base_rate_median(units/day)
    "Electronics":    (40, .10, .16, -1.6, .20),
    "Home & Kitchen": (12, .12, .20, -1.8, .30),
    "Apparel":        (9,  .15, .22, -2.2, .35),
    "Grocery":        (3,  .10, .14, -1.4, .90),
    "Beauty":         (6,  .14, .22, -2.0, .40),
    "Toys":           (8,  .13, .20, -2.1, .30),
    "Sports":         (15, .12, .19, -1.9, .25),
    "Office":         (5,  .12, .18, -1.7, .45),
    "Pet":            (7,  .12, .18, -1.8, .45),
    "Garden":         (11, .12, .20, -1.9, .20),
}
NOUNS = {
    "Electronics": ["Speaker", "Charger", "Headset", "Webcam", "Router", "Power Bank"],
    "Home & Kitchen": ["Kettle", "Pan Set", "Blender", "Organizer", "Lamp", "Mixer"],
    "Apparel": ["T-Shirt", "Jacket", "Joggers", "Socks 3-Pack", "Hoodie", "Cap"],
    "Grocery": ["Granola", "Olive Oil", "Pasta", "Coffee Beans", "Tea Box", "Honey"],
    "Beauty": ["Face Wash", "Serum", "Shampoo", "Lip Balm", "Sunscreen", "Body Lotion"],
    "Toys": ["Puzzle", "Building Set", "Plush", "Board Game", "RC Car", "Art Kit"],
    "Sports": ["Yoga Mat", "Water Bottle", "Dumbbell Pair", "Skipping Rope", "Gym Bag", "Band Set"],
    "Office": ["Notebook", "Pen Set", "Desk Pad", "Stapler", "Planner", "Folder Pack"],
    "Pet": ["Dog Chew", "Cat Toy", "Pet Bowl", "Leash", "Pet Bed", "Treat Pack"],
    "Garden": ["Planter", "Hose Nozzle", "Pruner", "Seed Kit", "Watering Can", "Gloves"],
}
CFG = dict(
    FRESH_H=96,          # competitor observation is "current" if age <= 96h at decision time
    MAX_STEP=0.10,       # max price move per decision
    BAND=0.005,          # moves smaller than 0.5% are NO_CHANGE
    UNDERCUT=1.03, RAISE=0.93,   # competitor triggers
    LOW_COVER=7, OVER_COVER=75,  # days-of-cover triggers
    MAX_DISC=0.40,       # max total promo discount (MAX_TOTAL_DISCOUNT_PCT rule)
    DEC_MIN=30,          # decisions run at 00:30
    P_BELOW_FLOOR=0.004, P_STALE_AS_CURRENT=0.15, P_MANUAL_CHANGE=0.0004,
    P_STACK_VIOLATION=0.01, P_MARGIN_BEFORE_DISC=0.015,
    COUPON_USE=0.35,
)
GROUP_EXCLUDES = {   # documented stacking matrix -> written into promotion_rule
    "SITEWIDE":  ["SITEWIDE", "CATEGORY", "CLEARANCE"],
    "CATEGORY":  ["SITEWIDE", "CATEGORY", "CLEARANCE"],
    "COUPON":    ["COUPON", "CLEARANCE"],
    "CLEARANCE": ["SITEWIDE", "CATEGORY", "COUPON", "CLEARANCE"],
}
MIN_STOCK = {"SITEWIDE": 1, "CATEGORY": 3, "COUPON": 3, "CLEARANCE": 5}
MAX_STACK = {"SITEWIDE": 2, "CATEGORY": 2, "COUPON": 2, "CLEARANCE": 1}
PTYPES = ENUMS["PROMO_TYPES"]
PCR = ENUMS["PRICE_CHANGE_REASONS"]
RC = {r: i + 1 for i, r in enumerate(PCR)}


def ceil_cents(x):
    return np.ceil(np.round(np.asarray(x, dtype=float) * 100, 6)) / 100


def ids(prefix, nums, w=6):
    return np.array([f"{prefix}{int(n):0{w}d}" for n in nums], dtype=object)


def obj(a):
    return np.asarray(a, dtype=object)


# ----------------------------------------------------------------- generator
def build(a):
    t0 = time.time()
    N, D, P = a.skus, a.days, a.promos
    ss = np.random.SeedSequence(a.seed)
    r_prod, r_cost, r_mkt, r_obs, r_promo, r_sim, r_anom = [np.random.default_rng(s) for s in ss.spawn(7)]
    start = np.datetime64(a.start, "D")
    days = start + np.arange(D)
    day_str = days.astype(str)
    ymd = np.char.replace(day_str, "-", "")
    L = D - 1
    stats = {}

    def ds(k):
        return str(start + np.timedelta64(int(k), "D"))

    # calendar / months
    mkey = days.astype("datetime64[M]")
    mi = (mkey - mkey[0]).astype(int)
    M = int(mi[-1]) + 1
    mlabel = np.array([str(x) for x in mkey[[np.nonzero(mi == k)[0][0] for k in range(M)]]])
    mstart = [int(np.nonzero(mi == k)[0][0]) for k in range(M)]       # first day index of month
    dow = (days.astype("datetime64[D]").astype(int) + 3) % 7           # Mon=0
    dowf = np.array([1, 1, 1, 1, 1.05, 1.25, 1.2])[dow]

    # ---------------- products
    cats = ENUMS["CATEGORIES"]
    brands = ENUMS["BRANDS"]
    ci = r_prod.integers(0, len(cats), N)
    bi = r_prod.integers(0, len(brands), N)
    med = np.array([CATS[c][0] for c in cats])[ci]
    mlo = np.array([CATS[c][1] for c in cats])[ci]
    mhi = np.array([CATS[c][2] for c in cats])[ci]
    elm = np.array([CATS[c][3] for c in cats])[ci]
    ratem = np.array([CATS[c][4] for c in cats])[ci]
    cost0 = np.maximum(0.5, np.round(med * np.exp(r_prod.normal(0, 0.5, N)), 2))
    mm = np.round(r_prod.uniform(mlo, mhi), 2)
    margin0 = r_prod.uniform(0.25, 0.50, N)
    list0 = np.ceil(cost0 / (1 - margin0)) - 0.01
    list0 = np.round(np.maximum(list0, ceil_cents(cost0 / (1 - mm) * 1.05)), 2)
    ceil_ = np.round(1.5 * list0, 2)
    elas = np.clip(r_prod.normal(elm, 0.35), -3.2, -0.8)
    rate_base = ratem * np.exp(r_prod.normal(0, 0.8, N))
    lead = r_prod.choice([5, 7, 10, 14], N, p=[.2, .4, .25, .15])
    launch = start - r_prod.integers(30, 1100, N).astype("timedelta64[D]")
    noun_i = r_prod.integers(0, 6, N)
    model_no = r_prod.integers(100, 999, N)
    n_disc = int(round(0.02 * N))
    disc_idx = r_prod.choice(N, n_disc, replace=False) if n_disc else np.array([], int)
    disc_day = np.full(N, 10 ** 6)
    disc_day[disc_idx] = r_prod.integers(max(1, int(.33 * D)), max(2, int(.83 * D)), n_disc)
    sku_str = np.array([f"SKU-{i + 1:06d}" for i in range(N)])
    names = [f"{brands[bi[i]]} {NOUNS[cats[ci[i]]][noun_i[i]]} {model_no[i]}" for i in range(N)]
    product = pd.DataFrame(dict(
        sku=sku_str, product_name=names, category=np.array(cats)[ci], brand=np.array(brands)[bi],
        launch_date=launch.astype(str), lifecycle_state=np.where(disc_day <= L, "DISCONTINUED", "ACTIVE"),
        min_margin_pct=mm, initial_list_price=list0, price_ceiling=ceil_, lead_time_days=lead))
    ev = []
    for i in range(N):
        ev.append((str(launch[i]), i, None, "ACTIVE", "initial listing"))
        if disc_day[i] <= L:
            ev.append((ds(disc_day[i]), i, "ACTIVE", "DISCONTINUED", "supplier end-of-life"))
    ev.sort(key=lambda x: (x[0], x[1]))
    pse = pd.DataFrame(dict(
        event_id=ids("PSE-2026-", range(1, len(ev) + 1)), sku=[sku_str[e[1]] for e in ev],
        event_date=[e[0] for e in ev], from_state=[e[2] for e in ev], to_state=[e[3] for e in ev],
        reason=[e[4] for e in ev]))

    # ---------------- costs (monthly records)
    cost = np.zeros((N, M))
    cost[:, 0] = cost0
    chg_pct = np.zeros((N, M))
    chg_rsn = np.full((N, M), None, dtype=object)
    for m in range(1, M):
        hit = r_cost.random(N) < 0.18
        up = r_cost.random(N) < 0.65
        pct = np.where(up, r_cost.uniform(.02, .10, N), -r_cost.uniform(.02, .08, N))
        upr = r_cost.choice(["SUPPLIER_INCREASE", "FREIGHT_SURCHARGE", "FX_MOVE"], N)
        dnr = r_cost.choice(["SUPPLIER_DISCOUNT", "VOLUME_REBATE"], N)
        new = np.round(cost[:, m - 1] * (1 + pct), 2)
        new = np.clip(new, np.round(cost0 * .8, 2), np.round(cost0 * 1.35, 2))
        new = np.maximum(np.where(hit, new, cost[:, m - 1]), 0.01)
        changed = new != cost[:, m - 1]
        chg_pct[:, m] = np.where(changed, np.round(new / cost[:, m - 1] - 1, 4), 0.0)
        chg_rsn[:, m] = np.where(changed, np.where(chg_pct[:, m] > 0, upr, dnr), None)
        cost[:, m] = new
    cr_sku = np.repeat(sku_str, M)
    cr_lbl = np.tile(mlabel, N)
    ms_dates = [start + np.timedelta64(d_, "D") for d_ in mstart]
    eff_from = np.tile(np.array([str(x) for x in ms_dates]), N)
    eff_to = np.tile(np.array([str(ms_dates[k + 1] - np.timedelta64(1, "D")) if k < M - 1 else "" for k in range(M)]), N)
    prev_cost = np.concatenate([np.full((N, 1), np.nan), cost[:, :-1]], 1)
    cpct = chg_pct.copy().astype(object)
    cpct[:, 0] = None
    cost_rec = pd.DataFrame(dict(
        cost_id=np.char.add(np.char.add(np.char.add("COST-", cr_sku), "-"), cr_lbl),
        sku=cr_sku, effective_from=eff_from, effective_to=np.where(eff_to == "", None, eff_to),
        unit_cost=cost.ravel(), prev_unit_cost=prev_cost.ravel(), change_pct=cpct.ravel(),
        change_reason=chg_rsn.ravel(),
        status=np.tile(np.array(["SUPERSEDED"] * (M - 1) + ["ACTIVE"]), N)))

    # ---------------- market & competitors
    logret = r_mkt.normal(0, 0.003, (N, D))
    logret[:, 0] = 0
    for m in range(1, M):
        logret[:, mstart[m]] += 0.7 * np.log1p(chg_pct[:, m]) * (r_mkt.random(N) < 0.8)
    market = list0[:, None] * np.exp(np.cumsum(logret, 1))
    bias = r_obs.normal(0, 0.03, (N, 3))
    noise = r_obs.normal(0, 0.01, (N, 3, D))
    comp_price = np.maximum(0.5, np.round(market[:, None, :] * (1 + bias[:, :, None] + noise), 2))
    excl = r_obs.integers(0, 3, N)
    tracked = np.arange(3)[None, :] != excl[:, None]
    src = r_obs.choice(3, (N, 3), p=[.5, .35, .15])
    stale_p = np.array([.02, .08, .25])[src]
    K = D // 3 + 2
    off = r_obs.integers(0, 3, (N, 3, 1))
    jit = (r_obs.random((N, 3, K)) < 0.10).astype(int)
    dayg = off + 3 * np.arange(K)[None, None, :] + jit
    keep = (dayg < D) & tracked[:, :, None] & (r_obs.random((N, 3, K)) >= 0.15)
    si, cj, _ = np.nonzero(keep)
    ing_day = dayg[keep]
    n_o = len(si)
    ing_min = ing_day * 1440 + r_obs.integers(0, 1440, n_o)
    stale = r_obs.random(n_o) < stale_p[si, cj]
    lag_h = np.where(stale, r_obs.uniform(100, 300, n_o), r_obs.uniform(1, 20, n_o))
    lag_min = np.round(lag_h * 60).astype(np.int64)
    obs_min = ing_min - lag_min
    obs_day = np.clip(obs_min // 1440, 0, D - 1)
    o_price = comp_price[si, cj, obs_day]
    o_instock = r_obs.random(n_o) >= 0.10
    order_ = np.lexsort((cj, si, ing_min))
    si, cj, ing_min, obs_min, lag_min, o_price, o_instock = [x[order_] for x in (si, cj, ing_min, obs_min, lag_min, o_price, o_instock)]
    o_key = si * 3 + cj
    t_base = np.datetime64(a.start + "T00:00:00", "s")
    comp_ids = np.array(ENUMS["COMPETITORS"])
    src_names = np.array(ENUMS["SOURCE_TYPES"])
    obs_id = ids("OBS-2026-", range(1, n_o + 1))
    obs_df = pd.DataFrame(dict(
        obs_id=obs_id, sku=sku_str[si], competitor_id=comp_ids[cj],
        observed_at=np.datetime_as_string(t_base + (obs_min * 60).astype("timedelta64[s]"), unit="s"),
        ingested_at=np.datetime_as_string(t_base + (ing_min * 60).astype("timedelta64[s]"), unit="s"),
        competitor_price=o_price, in_stock=o_instock.astype(int), source_type=src_names[src[si, cj]],
        source_lag_hours=np.round(lag_min / 60, 2)))

    # ---------------- promotions
    n_sw = max(1, int(round(.012 * P)))
    n_cat = int(round(.25 * P))
    n_cpn = int(round(.40 * P))
    n_clr = P - n_sw - n_cat - n_cpn
    grp = np.repeat([0, 1, 2, 3], [n_sw, n_cat, n_cpn, n_clr])
    p_start = r_promo.integers(0, D, P)
    dur = np.select([grp == 0, grp == 1, grp == 2, grp == 3],
                    [r_promo.integers(3, 8, P), r_promo.integers(7, 22, P),
                     r_promo.integers(7, 31, P), r_promo.integers(10, 31, P)])
    srt = np.lexsort((np.arange(P), grp, p_start))
    grp, p_start, dur = grp[srt], p_start[srt], dur[srt]
    p_end = p_start + dur - 1
    amt_flag = (r_promo.random(P) < .4) & (grp == 2)
    v_sw, v_cat = r_promo.uniform(.05, .12, P), r_promo.uniform(.08, .25, P)
    v_cpn, v_amt, v_clr = r_promo.uniform(.05, .20, P), r_promo.uniform(1, 10, P), r_promo.uniform(.20, .50, P)
    p_dtype = amt_flag.astype(int)
    p_val = np.select([grp == 0, grp == 1, (grp == 2) & amt_flag, grp == 2, grp == 3],
                      [v_sw, v_cat, np.maximum(1.0, np.round(v_amt * 2) / 2), v_cpn, v_clr])
    p_val = np.where(p_dtype == 1, p_val, np.round(p_val, 2))
    p_prio = r_promo.integers(1, 6, P)
    sched_gap, create_gap = r_promo.integers(1, 5, P), r_promo.integers(2, 10, P)
    canc = r_promo.random(P) < .05
    canc_day = p_start + r_promo.integers(-2, np.maximum(dur, 1))
    canc = canc & (canc_day <= L)
    act_end = np.minimum(np.where(canc, canc_day - 1, p_end), L)
    act_len = np.maximum(act_end - p_start + 1, 0)
    sc_cat = r_promo.integers(0, len(cats), P)
    sc_brand = r_promo.integers(0, len(brands), P)
    sku_cat, sku_brand = ci, bi
    b_p, b_s = [], []
    for i in range(P):
        if grp[i] == 0:
            s = np.arange(N)
        elif grp[i] == 1:
            s = np.nonzero((sku_cat == sc_cat[i]) & (sku_brand == sc_brand[i]))[0]
        else:
            k = int(r_promo.integers(5, 61 if grp[i] == 2 else 41))
            s = np.sort(r_promo.choice(N, min(k, N), replace=False))
        b_p.append(np.full(len(s), i))
        b_s.append(s)
    b_p, b_s = np.concatenate(b_p), np.concatenate(b_s)
    # promotion events + status
    pe = []
    for i in range(P):
        st, en = int(p_start[i]), int(p_end[i])
        sch = st - int(sched_gap[i])
        cr = sch - int(create_gap[i])
        cd = int(canc_day[i]) if canc[i] else None
        path = [(cr, None, "DRAFT", f"USR-ANALYST-{(i % 7) + 1:02d}"), (sch, "DRAFT", "SCHEDULED", "USR-OPSMGR-01"),
                (st, "SCHEDULED", "ACTIVE", "SYSTEM"), (en + 1, "ACTIVE", "ENDED", "SYSTEM")]
        cur = None
        for dk, fr, to, actor in path:
            if dk > L or (cd is not None and dk >= cd):
                break
            pe.append((dk, i, fr, to, actor))
            cur = to
        if cd is not None:
            pe.append((cd, i, cur, "CANCELLED", "USR-OPSMGR-01"))
    pe.sort(key=lambda x: (x[0], x[1]))
    final_state = {}
    for e in pe:
        final_state[e[1]] = e[3]
    promo_ids = ids("PROMO-2026-", range(1, P + 1))
    gnames = np.array(PTYPES)[grp]
    promo = pd.DataFrame(dict(
        promo_id=promo_ids,
        promo_name=[f"{gnames[i].title()} offer {i + 1}" for i in range(P)],
        promo_type=gnames,
        coupon_code=[f"CPN{i + 1:06d}" if grp[i] == 2 else None for i in range(P)],
        scope_type=np.array(ENUMS["SCOPE_TYPES"])[np.select([grp == 0, grp == 1], [0, 1], 2)],
        scope_category=[cats[sc_cat[i]] if grp[i] == 1 else None for i in range(P)],
        scope_brand=[brands[sc_brand[i]] if grp[i] == 1 else None for i in range(P)],
        discount_type=np.where(p_dtype == 1, "AMOUNT", "PERCENT"), discount_value=p_val,
        start_date=[ds(x) for x in p_start], end_date=[ds(x) for x in p_end], priority=p_prio,
        created_date=[ds(p_start[i] - sched_gap[i] - create_gap[i]) for i in range(P)],
        status=[final_state[i] for i in range(P)],
        cancelled_date=[ds(canc_day[i]) if canc[i] else None for i in range(P)]))
    pev = pd.DataFrame(dict(
        event_id=ids("PEV-2026-", range(1, len(pe) + 1)), promo_id=[promo_ids[e[1]] for e in pe],
        event_date=[ds(e[0]) for e in pe], from_state=[e[2] for e in pe], to_state=[e[3] for e in pe],
        actor=[e[4] for e in pe]))
    rr = []
    for i in range(P):
        g = gnames[i]
        base = f"RULE-2026-{i + 1:06d}-"
        rr += [(base + "01", promo_ids[i], "MIN_STOCK_UNITS", str(MIN_STOCK[g])),
               (base + "02", promo_ids[i], "MIN_MARGIN_PCT", "0.05" if g == "CLEARANCE" else "PRODUCT"),
               (base + "03", promo_ids[i], "MAX_TOTAL_DISCOUNT_PCT", str(CFG["MAX_DISC"])),
               (base + "04", promo_ids[i], "EXCLUDES_GROUP", "|".join(GROUP_EXCLUDES[g])),
               (base + "05", promo_ids[i], "MAX_STACK_COUNT", str(MAX_STACK[g]))]
    prule = pd.DataFrame(rr, columns=["rule_id", "promo_id", "rule_type", "rule_value"])
    psku = pd.DataFrame(dict(promo_id=promo_ids[b_p], sku=sku_str[b_s]))
    p_minm = np.where(grp == 3, 0.05, np.nan)
    p_minstock = np.array([MIN_STOCK[g] for g in gnames])
    cls_of = np.array([0, 0, 1, 2])
    # promo x sku x day expansion
    lens = act_len[b_p]
    tot = int(lens.sum())
    rep = np.repeat(np.arange(len(b_p)), lens)
    offs = np.arange(tot) - np.repeat(np.cumsum(lens) - lens, lens)
    psd_day = (p_start[b_p][rep] + offs).astype(np.int32)
    psd_p = b_p[rep].astype(np.int32)
    psd_s = b_s[rep].astype(np.int32)
    o = np.argsort(psd_day, kind="stable")
    psd_day, psd_p, psd_s = psd_day[o], psd_p[o], psd_s[o]
    ptr = np.searchsorted(psd_day, np.arange(D + 1))
    del rep, offs, o
    stats.update(promo_sku_day_rows=tot)

    # ---------------- simulation state
    price = list0.copy()
    stock0 = np.ceil(rate_base * r_sim.uniform(15, 45, N)).astype(int) + 3
    on_hand = stock0.copy()
    pipeline = np.zeros((N, D + 45), dtype=np.int64)
    sold_hist = np.zeros((N, D))
    open_hist = np.zeros((N, D), int)
    recv_hist = np.zeros((N, D), int)
    unmet_hist = np.zeros((N, D), int)
    close_hist = np.zeros((N, D), int)
    rp_hist = np.zeros((N, D), int)
    price_hist = np.zeros((N, D))
    reason_hist = np.zeros((N, D), np.int8)
    dec_hist = np.zeros((N, D), np.int32)
    cost_last = cost0.copy()
    price_hist[:, 0] = price
    reason_hist[:, 0] = RC["INITIAL_LISTING"]
    n_cust = max(1000, N * 12)
    dec_chunks, ord_chunks, op_chunks = [], [], []
    gt_dec_bf, gt_dec_stale, gt_manual = [], [], []
    gt_stack, gt_margin = [], []
    dec_ctr = 0
    ord_ctr = 0
    st_psd = dict(total=0, fail_stock=0, fail_margin=0, coupon_conflicts=0, coupon_dropped_stack=0)

    def stage(net, pidx):
        has = pidx >= 0
        pi = np.where(has, pidx, 0)
        n2 = np.where(p_dtype[pi] == 0, net * (1 - p_val[pi]), net - p_val[pi])
        n2 = np.maximum(np.round(n2, 2), 0.01)
        return np.where(has, n2, net)

    for d in range(D):
        m = int(mi[d])
        cost_d = cost[:, m]
        flr = ceil_cents(cost_d / (1 - mm))
        recv = pipeline[:, d].copy()
        prev_close = on_hand.copy()
        sa_draw, bf_draw = r_anom.random(N), r_anom.random(N)
        bf_mag = r_anom.uniform(.85, .97, N)
        man_draw, man_mag = r_anom.random(N), r_anom.uniform(.03, .08, N)
        man_sign = np.where(r_anom.random(N) < .5, -1, 1)
        sel = None
        if d >= 1:
            if d % 7 == 0:
                sel = np.arange(N)
            elif mi[d] != mi[d - 1]:
                sel = np.nonzero(chg_pct[:, m] != 0)[0]
        decided = np.zeros(N, bool)
        if sel is not None and sel.size:
            S = sel.size
            ar = np.arange(S)
            cur, c, fl, ce, oh = price[sel], cost_d[sel], flr[sel], ceil_[sel], prev_close[sel]
            lo = max(0, d - 28)
            avg = sold_hist[sel, lo:d].mean(1)
            cover = np.where(oh > 0, np.minimum(999.0, oh / np.maximum(avg, 0.02)), 0.0)
            ts_min = d * 1440 + CFG["DEC_MIN"]
            nv = int(np.searchsorted(ing_min, ts_min, side="right"))
            last = np.full(N * 3, -1, np.int64)
            last[o_key[:nv]] = np.arange(nv)
            lm = last.reshape(N, 3)[sel]
            valid = lm >= 0
            li = np.where(valid, lm, 0)
            pr = o_price[li]
            age = (ts_min - obs_min[li]) / 60.0
            ins = o_instock[li] & valid
            fresh = ins & (age <= CFG["FRESH_H"])
            has_fresh = fresh.any(1)
            jf = np.where(fresh, pr, np.inf).argmin(1)
            stale_ok = ins & ~fresh
            any_stale = stale_ok.any(1) & ~has_fresh
            stockout = oh <= 0
            anom_stale = any_stale & (sa_draw[sel] < CFG["P_STALE_AS_CURRENT"]) & ~stockout
            js = np.where(stale_ok, age, np.inf).argmin(1)
            jv = np.where(valid, age, np.inf).argmin(1)
            used = (has_fresh | anom_stale) & ~stockout
            jref = np.where(has_fresh, jf, np.where(any_stale, js, jv))
            has_ref = valid.any(1)
            cp_ref = np.where(has_ref, pr[ar, jref], np.nan)
            cage = np.where(has_ref, age[ar, jref], np.nan)
            cobs = np.where(has_ref, li[ar, jref], -1)
            cp = np.where(used, cp_ref, np.nan)
            exc = np.select([stockout, ~has_ref, ~(has_fresh | anom_stale) & any_stale,
                             ~(has_fresh | anom_stale) & ~ins.any(1)],
                            ["STOCKOUT_HOLD", "NO_COMPETITOR_DATA", "STALE_COMPETITOR_IGNORED",
                             "COMPETITOR_OUT_OF_STOCK"], default="")
            comp_hi = used & (cur > cp * CFG["UNDERCUT"])
            comp_lo = used & (cur < cp * CFG["RAISE"])
            low = (cover < CFG["LOW_COVER"]) & ~stockout
            over = cover > CFG["OVER_COVER"]
            cprc = c / cost_last[sel] - 1
            cost_up = cprc > 0.0005
            t_comp = np.where(comp_hi, cp * 0.995, cp * 0.97)
            conds = [stockout, comp_hi | comp_lo, low, over, cost_up]
            target = np.select(conds, [cur, t_comp, cur * 1.04, cur * .95, cur * (1 + .8 * cprc)], default=cur)
            reason = np.select(conds, ["STOCKOUT_HOLD", "COMPETITOR_MATCH", "LOW_STOCK_INCREASE",
                                       "OVERSTOCK_MARKDOWN", "COST_PASS_THROUGH"], default="HOLD_NO_SIGNAL").astype(object)
            cand = np.round(target, 2)
            slo, shi = np.round(cur * (1 - CFG["MAX_STEP"]), 2), np.round(cur * (1 + CFG["MAX_STEP"]), 2)
            stepped = np.minimum(np.maximum(cand, slo), shi)
            g = np.where(np.abs(stepped - cand) > 1e-9, "MAX_STEP", "NONE").astype(object)
            final = np.round(np.minimum(np.maximum(stepped, fl), ce), 2)
            g = np.where(final > stepped + 1e-9, "FLOOR", np.where(final < stepped - 1e-9, "CEILING", g)).astype(object)
            nc = (np.abs(final - cur) <= CFG["BAND"] * cur) & (cur >= fl - 1e-9) & (cur <= ce + 1e-9)
            final = np.where(nc, cur, final)
            g = np.where(nc, "NONE", g).astype(object)
            cost_changed = np.abs(c - cost_last[sel]) > 1e-9
            fix = (g == "FLOOR") & np.isin(reason, ["HOLD_NO_SIGNAL", "STOCKOUT_HOLD"])
            reason = np.where(fix, np.where(cost_changed, "COST_PASS_THROUGH", "FLOOR_ENFORCEMENT"), reason).astype(object)
            # --- injected anomaly: guardrail bypass -> price below floor
            bfp = np.round(fl * bf_mag[sel], 2)
            bf = (bf_draw[sel] < CFG["P_BELOW_FLOOR"]) & ~stockout & (np.abs(bfp - cur) > 1e-9)
            final = np.where(bf, bfp, final)
            g = np.where(bf, "NONE", g).astype(object)
            reason = np.where(bf & np.isin(reason, ["HOLD_NO_SIGNAL", "FLOOR_ENFORCEMENT", "COST_PASS_THROUGH"]),
                              "OVERSTOCK_MARKDOWN", reason).astype(object)
            chg = np.abs(final - cur) > 1e-9
            dnum = dec_ctr + 1 + ar
            dec_ctr += S
            dec_chunks.append(dict(
                dnum=dnum, sku_i=sel, d=np.full(S, d), cost=c, cur=cur, fl=fl, ce=ce, cobs=cobs, cp=cp_ref, cage=cage,
                used=used, oh=oh, avg=avg, cover=cover, cand=cand, g=g, final=final,
                status=np.where(chg, "APPLIED", "NO_CHANGE"), reason=reason, exc=exc))
            if bf.any():
                gt_dec_bf.append((dnum[bf], fl[bf], final[bf]))
            if anom_stale.any():
                gt_dec_stale.append((dnum[anom_stale], cage[anom_stale], cobs[anom_stale]))
            price[sel] = final
            cost_last[sel] = c
            decided[sel] = True
            reason_hist[sel[chg], d] = [RC[x] for x in reason[chg]]
            dec_hist[sel[chg], d] = dnum[chg]
        # --- injected anomaly: manual price change with no reason / no decision
        if d >= 1:
            newp = np.round(np.clip(price * (1 + man_sign * man_mag), flr, ceil_), 2)
            mchg = (man_draw < CFG["P_MANUAL_CHANGE"]) & ~decided & (np.abs(newp - price) > 1e-9)
            if mchg.any():
                gt_manual.append((np.nonzero(mchg)[0], d))
                price = np.where(mchg, newp, price)
        price_hist[:, d] = price

        # --- promotions for the day
        opening = prev_close + recv
        pk, sk = psd_p[ptr[d]:ptr[d + 1]], psd_s[ptr[d]:ptr[d + 1]]
        auto = np.full(N, -1)
        base1 = base2 = cpn1 = cpn2 = clr1 = np.full(N, -1)
        if pk.size:
            p_ = price[sk]
            c_ = cost_d[sk]
            net = np.round(np.where(p_dtype[pk] == 0, p_ * (1 - p_val[pk]), p_ - p_val[pk]), 2)
            mmv = np.where(np.isnan(p_minm[pk]), mm[sk], p_minm[pk])
            stock_ok = opening[sk] >= p_minstock[pk]
            marg_ok = (net > 0) & (net * (1 - mmv) >= c_ - 1e-9)
            ok = stock_ok & marg_ok
            st_psd["total"] += pk.size
            st_psd["fail_stock"] += int((~stock_ok).sum())
            st_psd["fail_margin"] += int((stock_ok & ~marg_ok).sum())
            df = pd.DataFrame(dict(s=sk[ok], p=pk[ok], cls=cls_of[grp[pk[ok]]], pct=(1 - net / p_)[ok], pr=p_prio[pk[ok]]))
            df = df.sort_values(["s", "cls", "pct", "pr", "p"], ascending=[True, True, False, True, True], kind="stable")
            df["rk"] = df.groupby(["s", "cls"]).cumcount()

            def pick(cls, rk):
                sub = df[(df.cls == cls) & (df.rk == rk)]
                arr = np.full(N, -1)
                arr[sub.s.values] = sub.p.values
                return arr
            base1, base2, cpn1, cpn2, clr1 = pick(0, 0), pick(0, 1), pick(1, 0), pick(1, 1), pick(2, 0)
        auto = np.where(clr1 >= 0, clr1, base1)
        net1 = stage(price, auto)
        cp_i = np.where(cpn1 >= 0, cpn1, 0)
        net2 = stage(net1, np.where(cpn1 >= 0, cpn1, -1))
        mmc = np.where(np.isnan(p_minm[cp_i]), mm, p_minm[cp_i])
        cvalid = ((cpn1 >= 0) & (clr1 < 0) & (net2 * (1 - mmc) >= cost_d - 1e-9)
                  & (1 - net2 / price <= CFG["MAX_DISC"] + 1e-9))
        st_psd["coupon_conflicts"] += int((cpn2 >= 0).sum())
        st_psd["coupon_dropped_stack"] += int(((cpn1 >= 0) & (clr1 < 0) & ~cvalid).sum())
        vkind = np.where((clr1 >= 0) & (cpn1 >= 0), 1,
                         np.where((base1 >= 0) & (base2 >= 0), 2, np.where((cpn1 >= 0) & (cpn2 >= 0), 3, 0)))

        # --- demand
        rel = np.clip(price / market[:, d], 0.3, 3.0)
        a_pct = np.where(auto >= 0, 1 - net1 / price, 0.0)
        c_pct = np.where(cvalid, 1 - net2 / np.maximum(net1, 0.01), 0.0)
        lam = (rate_base * dowf[d] * rel ** elas * (1 + 3.0 * a_pct + 0.35 * 3.0 * c_pct)
               * np.exp(r_sim.normal(0, .25, N) - .03))
        n_ord = r_sim.poisson(lam / 1.25)
        tot_o = int(n_ord.sum())
        sk_o = np.repeat(np.arange(N), n_ord)
        qty = r_sim.choice([1, 2, 3], size=tot_o, p=[.8, .15, .05])
        sec = r_sim.integers(0, 86400, tot_o)
        oo = np.argsort(sec, kind="stable")
        sk_o, qty, sec = sk_o[oo], qty[oo], sec[oo]
        cum = pd.Series(qty).groupby(sk_o).cumsum().values if tot_o else np.array([], int)
        kp = cum <= opening[sk_o]
        demanded = np.bincount(sk_o, weights=qty, minlength=N)
        sk_k, q_k, sec_k = sk_o[kp], qty[kp], sec[kp]
        sold = np.bincount(sk_k, weights=q_k, minlength=N).astype(int)
        closing = opening - sold
        Kn = len(sk_k)
        cu_draw = r_sim.random(Kn)
        cust = r_sim.integers(1, n_cust + 1, Kn)
        chan = r_sim.choice(3, Kn, p=[.5, .3, .2])
        sv_draw, ma_draw = r_anom.random(Kn), r_anom.random(Kn)
        vk = vkind[sk_k]
        sv = (vk > 0) & (sv_draw < CFG["P_STACK_VIOLATION"])
        use_c = cvalid[sk_k] & (cu_draw < CFG["COUPON_USE"])
        A = auto[sk_k]
        B = np.where(use_c, cpn1[sk_k], -1)
        B = np.where(sv & ((vk == 1) | (vk == 3)), cpn1[sk_k], B)
        V = np.where(sv & (vk == 2), base2[sk_k], np.where(sv & (vk == 3), cpn2[sk_k], -1))
        n0 = price[sk_k]
        n1 = stage(n0, A)
        n2 = stage(n1, B)
        n3 = stage(n2, V)
        ds1, ds2, ds3 = n0 - n1, n1 - n2, n2 - n3
        l1, l2, l3 = np.round(q_k * ds1, 2), np.round(q_k * ds2, 2), np.round(q_k * ds3, 2)
        cst = cost_d[sk_k]
        mg = np.round((n3 - cst) / n3, 4)
        disc_any = n3 < n0 - 1e-9
        ma = (ma_draw < CFG["P_MARGIN_BEFORE_DISC"]) & disc_any & ~sv
        mg = np.where(ma, np.round((n0 - cst) / n0, 4), mg)
        o_no = ord_ctr + 1 + np.arange(Kn)
        ord_ctr += Kn
        ord_chunks.append(dict(ono=o_no, sku_i=sk_k, d=np.full(Kn, d), sec=sec_k, cust=cust, chan=chan, q=q_k, n0=n0,
                               cst=cst, l1=l1, l2=l2, l3=l3, mg=mg, n3=n3, A=A, B=B, V=V))
        if sv.any():
            gt_stack.append((o_no[sv], vk[sv]))
        if ma.any():
            gt_margin.append((o_no[ma], mg[ma], np.round((n3 - cst) / n3, 4)[ma]))
        # --- replenishment
        sold_hist[:, d] = sold
        trail = sold_hist[:, max(0, d - 13):d + 1].mean(1)
        rate_est = np.maximum(np.where(d >= 7, 0.3 * trail + 0.7 * rate_base, rate_base), 0.05)
        rp = np.ceil(rate_est * (lead + 7)).astype(int) + 1
        inbound = pipeline[:, d + 1:].sum(1)
        need = (closing + inbound <= rp) & (disc_day > d)
        po_q = np.maximum(np.ceil(rate_est * 35).astype(int), 5)
        delay = (r_sim.random(N) < .12) * r_sim.integers(5, 15, N)
        arr = d + 1 + lead + delay
        idx = np.nonzero(need)[0]
        pipeline[idx, arr[idx]] += po_q[idx]
        open_hist[:, d], recv_hist[:, d], unmet_hist[:, d] = opening, recv, (demanded - sold).astype(int)
        close_hist[:, d], rp_hist[:, d] = closing, rp
        on_hand = closing

    # ---------------- assemble tables
    def cat(chunks, key):
        return np.concatenate([c[key] for c in chunks])

    # decisions
    dc = dec_chunks
    dnum, d_sku, d_day = cat(dc, "dnum"), cat(dc, "sku_i"), cat(dc, "d")
    d_final, d_cur, d_cost = cat(dc, "final"), cat(dc, "cur"), cat(dc, "cost")
    dec_df = pd.DataFrame(dict(
        decision_id=ids("DEC-2026-", dnum), sku=sku_str[d_sku],
        decision_ts=[f"{day_str[x]}T00:30:00" for x in d_day],
        cost_id=np.char.add(np.char.add(np.char.add("COST-", sku_str[d_sku]), "-"), mlabel[mi[d_day]]),
        unit_cost=d_cost, current_list_price=d_cur, price_floor=np.round(cat(dc, "fl"), 2), price_ceiling=cat(dc, "ce"),
        competitor_obs_id=[obs_id[x] if x >= 0 else None for x in cat(dc, "cobs")],
        competitor_price=cat(dc, "cp"), competitor_age_hours=np.round(cat(dc, "cage"), 2),
        competitor_used=cat(dc, "used").astype(int), opening_on_hand=cat(dc, "oh").astype(int),
        avg_daily_sales_28d=np.round(cat(dc, "avg"), 4), days_of_cover=np.round(cat(dc, "cover"), 1),
        candidate_price=cat(dc, "cand"), guardrail_applied=cat(dc, "g"), final_price=d_final,
        price_change_pct=np.round(d_final / d_cur - 1, 4), decision_status=cat(dc, "status"),
        reason_code=cat(dc, "reason"),
        exception_code=[x if x else None for x in cat(dc, "exc")],
        margin_pct_at_final=np.round((d_final - d_cost) / d_final, 4), rule_version="PR-1.0"))
    dec_ids_by_no = dec_df.decision_id.values

    # price history
    sku_rep = np.repeat(sku_str, D)
    ymd_t = np.tile(ymd, N)
    lbl_day = mlabel[mi]
    cost_day = cost[:, mi]
    floor_day = ceil_cents(cost_day / (1 - mm[:, None]))
    prev = np.concatenate([np.full((N, 1), np.nan), price_hist[:, :-1]], 1)
    is_chg = (~np.isnan(prev)) & (np.abs(price_hist - prev) > 1e-9)
    rnames = np.array([None] + PCR, dtype=object)
    dec_flat = dec_hist.ravel()
    dec_col = np.full(N * D, None, dtype=object)
    nz = np.nonzero(dec_flat > 0)[0]
    dec_col[nz] = dec_ids_by_no[dec_flat[nz] - 1]
    ph = pd.DataFrame(dict(
        price_id=np.char.add(np.char.add(np.char.add("PRC-", sku_rep), "-"), ymd_t), sku=sku_rep,
        price_date=np.tile(day_str, N), list_price=price_hist.ravel(), prev_list_price=prev.ravel(),
        is_price_change=is_chg.ravel().astype(int), change_reason=rnames[reason_hist.ravel()], decision_id=dec_col,
        cost_id=np.char.add(np.char.add(np.char.add("COST-", sku_rep), "-"), np.tile(lbl_day, N)),
        unit_cost=cost_day.ravel(), price_floor=np.round(floor_day.ravel(), 2),
        margin_pct=np.round((price_hist - cost_day) / price_hist, 4).ravel()))
    del sku_rep, ymd_t, dec_col

    # inventory
    avg28 = np.zeros((N, D))
    cs = np.cumsum(sold_hist, 1)
    for dd in range(D):
        lo_ = max(0, dd - 27)
        avg28[:, dd] = (cs[:, dd] - (cs[:, lo_ - 1] if lo_ > 0 else 0)) / (dd - lo_ + 1)
    cover_inv = np.where(close_hist > 0, np.minimum(999.0, close_hist / np.maximum(avg28, 0.02)), 0.0)
    sku_rep = np.repeat(sku_str, D)
    inv = pd.DataFrame(dict(
        snapshot_id=np.char.add(np.char.add(np.char.add("INV-", sku_rep), "-"), np.tile(ymd, N)), sku=sku_rep,
        snapshot_date=np.tile(day_str, N), opening_on_hand=open_hist.ravel(), units_received=recv_hist.ravel(),
        units_sold=sold_hist.astype(int).ravel(), units_unfulfilled=unmet_hist.ravel(), closing_on_hand=close_hist.ravel(),
        stockout_flag=(close_hist == 0).ravel().astype(int), reorder_point=rp_hist.ravel(),
        days_of_cover=np.round(cover_inv, 1).ravel()))
    del sku_rep

    # orders
    oc = ord_chunks
    ono, o_sku, o_day, o_sec = cat(oc, "ono"), cat(oc, "sku_i"), cat(oc, "d"), cat(oc, "sec")
    o_q, o_n0, o_cst = cat(oc, "q"), cat(oc, "n0"), cat(oc, "cst")
    o_l1, o_l2, o_l3, o_n3 = cat(oc, "l1"), cat(oc, "l2"), cat(oc, "l3"), cat(oc, "n3")
    o_disc = np.round(o_l1 + o_l2 + o_l3, 2)
    gross = np.round(o_q * o_n0, 2)
    net_amt = np.round(gross - o_disc, 2)
    cogs = np.round(o_q * o_cst, 2)
    A_, B_, V_ = cat(oc, "A"), cat(oc, "B"), cat(oc, "V")
    ts = t_base + (o_day * 86400 + o_sec).astype("timedelta64[s]")
    ts_str = np.datetime_as_string(ts, unit="s")
    orders = pd.DataFrame(dict(
        order_id=ids("ORD-2026-", ono), order_ts=ts_str, order_date=day_str[o_day],
        customer_id=ids("CUST-", cat(oc, "cust")), channel=np.array(ENUMS["CHANNELS"])[cat(oc, "chan")],
        sku=sku_str[o_sku],
        quantity=o_q, price_id=np.char.add(np.char.add(np.char.add("PRC-", sku_str[o_sku]), "-"), ymd[o_day]),
        cost_id=np.char.add(np.char.add(np.char.add("COST-", sku_str[o_sku]), "-"), mlabel[mi[o_day]]),
        unit_list_price=o_n0, unit_cost=o_cst, gross_amount=gross, discount_amount=o_disc, net_amount=net_amt,
        cogs_amount=cogs, gross_margin_amount=np.round(net_amt - cogs, 2), margin_pct=cat(oc, "mg"),
        promo_count=(A_ >= 0).astype(int) + (B_ >= 0) + (V_ >= 0)))
    seqA = np.ones(len(ono), int)
    seqB = 1 + (A_ >= 0)
    seqV = 1 + (A_ >= 0) + (B_ >= 0)
    parts = []
    for pidx, ln, sq in ((A_, o_l1, seqA), (B_, o_l2, seqB), (V_, o_l3, seqV)):
        mk = pidx >= 0
        parts.append(pd.DataFrame(dict(order_id=ids("ORD-2026-", ono[mk]), promo_id=promo_ids[pidx[mk]],
                                       apply_seq=sq[mk], line_discount_amount=ln[mk])))
    op = pd.concat(parts, ignore_index=True)
    op = op.sort_values(["order_id", "apply_seq"], kind="stable").reset_index(drop=True)

    # ground truth
    gt = []

    def add(rt, rid, it, desc, exp):
        gt.append((rt, rid, it, desc, exp))
    for dn, fl_, fp_ in gt_dec_bf:
        for x, f1, f2 in zip(dn, fl_, fp_):
            add("price_decision", dec_ids_by_no[x - 1], "PRICE_BELOW_FLOOR",
                f"final_price {f2:.2f} below price_floor {f1:.2f}; guardrail bypassed",
                "final_price >= price_floor (guardrail FLOOR)")
    for dn, ag, co in gt_dec_stale:
        for x, a1, o1 in zip(dn, ag, co):
            add("price_decision", dec_ids_by_no[x - 1], "STALE_OBSERVATION_AS_CURRENT",
                f"observation {obs_id[o1]} aged {a1:.1f}h (> {CFG['FRESH_H']}h) used as current",
                "ignore stale observation; exception STALE_COMPETITOR_IGNORED")
    for sk_i, dd in gt_manual:
        for s in sk_i:
            add("price_history", f"PRC-{sku_str[s]}-{ymd[dd]}", "PRICE_CHANGE_LACKS_REASON",
                "manual price override without decision_id or change_reason",
                "every price change references a decision_id and change_reason")
    kinds = {1: "CLEARANCE+COUPON", 2: "BASE+BASE", 3: "COUPON+COUPON"}
    for on_, vk_ in gt_stack:
        for x, k in zip(on_, vk_):
            add("orders", f"ORD-2026-{int(x):06d}", "PROMOTION_STACK_VIOLATION",
                f"prohibited stack {kinds[int(k)]} applied",
                "apply at most one promo per exclusive group (best discount wins)")
    for on_, wrong, right in gt_margin:
        for x, w_, r_ in zip(on_, wrong, right):
            add("orders", f"ORD-2026-{int(x):06d}", "MARGIN_BEFORE_DISCOUNT",
                f"margin_pct {w_:.4f} computed on list price before discount",
                f"margin_pct = (net - cost) / net = {r_:.4f}")
    gt_df = pd.DataFrame(gt, columns=["record_type", "record_id", "issue_type", "description", "expected_outcome"])
    gt_df = gt_df.sort_values(["issue_type", "record_id"], kind="stable").reset_index(drop=True)
    gt_df.insert(0, "gt_id", ids("GT-", range(1, len(gt_df) + 1)))

    tables = dict(product=product, cost_record=cost_rec, price_history=ph, competitor_observation=obs_df,
                  inventory_snapshot=inv, promotion=promo, promotion_rule=prule, promotion_sku=psku,
                  promotion_event=pev, product_status_event=pse, orders=orders, order_promotion=op,
                  price_decision=dec_df)
    stats.update(skus=N, days=D, promos=P, seed=a.seed, seconds=round(time.time() - t0, 1),
                 promo_resolution=st_psd, groups=dict(zip(PTYPES, [n_sw, n_cat, n_cpn, n_clr])),
                 anomalies=gt_df.issue_type.value_counts().to_dict())
    return tables, gt_df, stats


def write_all(tables, gt_df, stats, out):
    os.makedirs(f"{out}/data", exist_ok=True)
    os.makedirs(f"{out}/ground_truth", exist_ok=True)
    os.makedirs(f"{out}/docs", exist_ok=True)
    manifest = {}
    items = list(tables.items()) + [("ground_truth", gt_df)]
    for name, df in items:
        cols = columns(name)
        assert set(df.columns) == set(cols), (name, set(df.columns) ^ set(cols))
        df = df[cols]
        path = f"{out}/ground_truth/{name}.csv" if name == "ground_truth" else f"{out}/data/{name}.csv"
        df.to_csv(path, index=False, lineterminator="\n")
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        manifest[os.path.relpath(path, out).replace(os.sep, "/")] = dict(rows=len(df), bytes=os.path.getsize(path), sha256=h.hexdigest())
    json.dump(manifest, open(f"{out}/MANIFEST.json", "w"), indent=2)
    json.dump(stats, open(f"{out}/docs/generation_stats.json", "w"), indent=2, default=str)
    gt_df.to_json(f"{out}/ground_truth/ground_truth.json", orient="records", indent=1)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", type=int, default=5000)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--promos", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--out", default="out/full")
    args = ap.parse_args()
    tbl, gt_df, st = build(args)
    mf = write_all(tbl, gt_df, st, args.out)
    for k, v in mf.items():
        print(f"{k:45s} {v['rows']:>9,d} rows  {v['bytes'] / 1e6:8.1f} MB")
    print("anomalies:", st["anomalies"], "| seconds:", st["seconds"])