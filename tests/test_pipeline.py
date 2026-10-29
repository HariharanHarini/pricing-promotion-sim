"""End-to-end tests. Run: python -m pytest -q   (about 30 seconds)"""
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ARGS = ["--skus", "300", "--days", "60", "--promos", "100"]


def gen(out, seed=20261022):
    subprocess.run([sys.executable, "generate.py", *ARGS, "--seed", str(seed), "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    out = tmp_path_factory.mktemp("a")
    gen(out)
    return out


def test_same_seed_is_byte_identical(run_a, tmp_path):
    gen(tmp_path)
    a = json.load(open(run_a / "MANIFEST.json"))
    b = json.load(open(tmp_path / "MANIFEST.json"))
    assert a == b


def test_different_seed_changes_data(run_a, tmp_path):
    gen(tmp_path, seed=1)
    a = json.load(open(run_a / "MANIFEST.json"))
    b = json.load(open(tmp_path / "MANIFEST.json"))
    assert a["data/orders.csv"]["sha256"] != b["data/orders.csv"]["sha256"]


def test_validator_passes_all_checks(run_a):
    r = subprocess.run([sys.executable, "validate.py", str(run_a)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "FAIL" not in r.stdout


def test_ground_truth_is_separate_and_every_edge_case_present(run_a):
    gt = pd.read_csv(run_a / "ground_truth" / "ground_truth.csv")
    assert set(gt.issue_type) == {"PRICE_BELOW_FLOOR", "PROMOTION_STACK_VIOLATION", "STALE_OBSERVATION_AS_CURRENT",
                                  "MARGIN_BEFORE_DISCOUNT", "PRICE_CHANGE_LACKS_REASON"}
    for f in (run_a / "data").glob("*.csv"):
        assert "issue_type" not in pd.read_csv(f, nrows=1).columns


def test_unlabelled_prices_never_below_floor(run_a):
    ph = pd.read_csv(run_a / "data" / "price_history.csv")
    dec = pd.read_csv(run_a / "data" / "price_decision.csv")
    gt = pd.read_csv(run_a / "ground_truth" / "ground_truth.csv")
    bad_dec = set(dec[dec.final_price < dec.price_floor - 1e-6].decision_id)
    assert bad_dec == set(gt[gt.issue_type == "PRICE_BELOW_FLOOR"].record_id)
    assert (dec[~dec.decision_id.isin(bad_dec)].final_price >= dec[~dec.decision_id.isin(bad_dec)].price_floor - 1e-6).all()
