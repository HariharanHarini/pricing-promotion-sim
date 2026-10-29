# AI usage disclosure

**Tool:** Claude (Anthropic), in the claude.ai chat interface, in one long conversation. Full prompt history: `docs/PROMPT_HISTORY.md`.

## Where AI did the work (be plain about this)

- Nearly all code was written by Claude: `schema.py`, `generate.py`, `validate.py`, `make_docs.py`, `export_sql.py`, `repro_check.py`, tests, and the first drafts of the README and design notes.
- Claude chose the simulation design, the stacking rules, the anomaly-injection approach and the detector design, from the brief I supplied.
- Claude ran the code in its own sandbox, found and fixed bugs, and produced the results I report.

## What I did myself

Fill in each line honestly. Delete any you did not actually do.

- [ ] Where I relied on AI most heavily

## What I did myself

- I supplied the project brief and chose to build the full project from it.
- I installed and ran the project locally on Windows in VS Code (PowerShell,virtual environment) on 27/10/2026. I fixed my own working-folder andnetwork problems and ran the commands myself.
- I found a Windows-only test failure (path separators in the manifest) and reported it with the output. That led to a portability fix in`generate.py`, which I applied and re-tested.
- I ran the tests, the validator and the reproducibility check locally.
- I decided what belonged in the repository and removed unneeded files.
- I reviewed the project's limitations and recorded them as known drawbacks.
- I experimented with the competitor freshness window: changing it from 96 to 48 hours raised the share of decisions that ignored a stale competitor price from 6.4% to 32.6% (starter dataset, seed 20261022),and cut the share of decisions using a competitor price from 89.8% to63.3%. I reverted the change.
- While experimenting with the freshness window (96 to 48 hours), the validator's stale-observation detector failed (recall 0.16) because the 96-hour threshold is hard-coded separately in `generate.py` and
  `validate.py`. I reverted the change. A better design would share one constant between them.

Simulation logic, vectorised pandas/numpy code, and the validator's independent promo-eligibility replay.
