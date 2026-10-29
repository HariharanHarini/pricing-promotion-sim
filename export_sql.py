#!/usr/bin/env python3
"""Export SQL seed data and/or build a SQLite database from the generated CSVs.

    python export_sql.py out/starter --seed-sql out/starter/sql/seed_starter.sql --sqlite out/starter/pricing_sim.db
    python export_sql.py out/full --sqlite out/full/pricing_sim.db
"""
import argparse
import os
import sqlite3

import pandas as pd

from schema import LOAD_ORDER, TABLES

ap = argparse.ArgumentParser()
ap.add_argument("root")
ap.add_argument("--seed-sql")
ap.add_argument("--sqlite")
a = ap.parse_args()
ddl = open("sql/schema.sql").read()


def lit(v, typ):
    if v == "":
        return "NULL"
    return v if typ in ("int", "decimal", "bool") else "'" + v.replace("'", "''") + "'"


if a.seed_sql:
    os.makedirs(os.path.dirname(a.seed_sql), exist_ok=True)
    with open(a.seed_sql, "w") as f:
        f.write("-- Seed data (starter scale). Run sql/schema.sql first.\nBEGIN;\n")
        for t in LOAD_ORDER:
            df = pd.read_csv(f"{a.root}/data/{t}.csv", dtype=str, keep_default_na=False)
            types = [x["type"] for x in TABLES[t]["fields"]]
            cols = ", ".join(df.columns)
            for i in range(0, len(df), 500):
                rows = ",\n".join("(" + ", ".join(lit(v, ty) for v, ty in zip(r, types)) + ")" for r in df.iloc[i:i + 500].itertuples(index=False))
                f.write(f"INSERT INTO {t} ({cols}) VALUES\n{rows};\n")
        f.write("COMMIT;\n")
    print("wrote", a.seed_sql)

if a.sqlite:
    if os.path.exists(a.sqlite):
        os.remove(a.sqlite)
    con = sqlite3.connect(a.sqlite)
    con.executescript(ddl)
    con.execute("PRAGMA foreign_keys=ON")
    for t in LOAD_ORDER:
        n = 0
        for ch in pd.read_csv(f"{a.root}/data/{t}.csv", chunksize=100000):
            ch = ch.astype(object).where(ch.notna(), None)
            con.executemany(f"INSERT INTO {t} ({', '.join(ch.columns)}) VALUES ({', '.join('?' * len(ch.columns))})", ch.values.tolist())
            n += len(ch)
        con.commit()
        print(f"loaded {t:24s} {n:>9,d}")
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    print("PRAGMA foreign_key_check violations:", len(bad))
    con.close()
