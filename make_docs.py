#!/usr/bin/env python3
"""Render docs/data_dictionary.md and sql/schema.sql from schema.py (single source of truth)."""
import os
from schema import ENUMS, FKS, LOAD_ORDER, RELATIONSHIPS, TABLES

SQLT = {"string": "VARCHAR(160)", "int": "INTEGER", "decimal": "DECIMAL(14,4)", "date": "DATE",
        "timestamp": "TIMESTAMP", "bool": "SMALLINT"}
os.makedirs("docs", exist_ok=True)
os.makedirs("sql", exist_ok=True)

# ---------------- data dictionary
L = ["# Data dictionary", "",
     "Generated from `schema.py`. Booleans are stored as 0/1. Currency is a single unspecified unit. "
     "Margin basis everywhere: `(price - cost) / price`, where price is the list price for list-level rows "
     "and the net price AFTER all discounts for order rows.", "",
     "## Entities and cardinality", "",
     "| Parent | Child | Cardinality | Optionality | Notes |", "|---|---|---|---|---|"]
for p, c, card, opt, note in RELATIONSHIPS:
    L.append(f"| {p} | {c} | {card} | {opt} | {note} |")
L += ["", "## Enumerations", ""]
for k, v in ENUMS.items():
    L.append(f"- **{k}**: {', '.join(v)}")
L += ["", "## Tables", ""]
for t in TABLES:
    spec = TABLES[t]
    L += [f"### {t}", "", spec["desc"], "", f"Primary key: `{', '.join(spec['pk'])}`", ""]
    fk = [f for f in FKS if f[0] == t]
    if fk:
        L.append("Foreign keys: " + "; ".join(f"`{c}` -> `{pt}.{pc}`" for _, c, pt, pc in fk))
        L.append("")
    L += ["| Field | Type | Req | Allowed values | Unit | Unique | Validation rule |", "|---|---|---|---|---|---|---|"]
    for f in spec["fields"]:
        al = f["allowed"]
        if al.startswith("enum:"):
            al = ", ".join(ENUMS[al[5:]]) if len(ENUMS[al[5:]]) <= 8 else al[5:] + " (see Enumerations)"
        L.append(f"| {f['name']} | {f['type']} | {'R' if f['required'] else 'O'} | {al} | {f['unit']} | {f['unique']} | {f['rule'].replace('|', '/')} |")
    L.append("")
open("docs/data_dictionary.md", "w").write("\n".join(L))

# ---------------- DDL
D = ["-- Generated from schema.py. ANSI-style; runs on SQLite and PostgreSQL.", ""]
for t in LOAD_ORDER + ["ground_truth"]:
    spec = TABLES[t]
    cols = []
    for f in spec["fields"]:
        c = f"  {f['name']} {SQLT[f['type']]}" + ("" if f["required"] else "")
        if f["required"]:
            c += " NOT NULL"
        if f["allowed"].startswith("enum:"):
            vals = ", ".join(f"'{v}'" for v in ENUMS[f["allowed"][5:]])
            c += f" CHECK ({f['name']} IN ({vals}))"
        cols.append(c)
    cols.append(f"  PRIMARY KEY ({', '.join(spec['pk'])})")
    for _, c, pt, pc in [f for f in FKS if f[0] == t]:
        cols.append(f"  FOREIGN KEY ({c}) REFERENCES {pt}({pc})")
    D.append(f"-- {spec['desc']}")
    D.append(f"CREATE TABLE {t} (\n" + ",\n".join(cols) + "\n);\n")
D.append("CREATE INDEX ix_price_history_sku_date ON price_history(sku, price_date);")
D.append("CREATE INDEX ix_orders_sku_date ON orders(sku, order_date);")
D.append("CREATE INDEX ix_decision_sku ON price_decision(sku, decision_ts);")
D.append("CREATE INDEX ix_obs_sku ON competitor_observation(sku, ingested_at);")
open("sql/schema.sql", "w").write("\n".join(D) + "\n")
print("wrote docs/data_dictionary.md, sql/schema.sql")
