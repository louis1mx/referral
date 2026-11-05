# Reproducing the HW7 benchmark

Branch `hw7-benchmark` of https://github.com/louis1mx/referral. Seeds and the split are in `split.md`; all settings are constants at the top of `src/referral/hw7.py`.

Requirements: Python 3.11+, and the Claude Code CLI on `PATH`, signed in (`claude`, then `/login`). Real workers and the Checker's semantic layer call `claude -p` in headless mode with no tools and a JSON schema. No API key is needed.

```bash
git clone https://github.com/louis1mx/referral.git && cd referral && git checkout hw7-benchmark
python3 -m venv .venv && .venv/bin/pip install -r requirements-lock.txt -e . matplotlib
export PYTHONPATH=src
.venv/bin/python -m pytest -q                              # offline unit tests
.venv/bin/python -m referral.hw7 warmup                    # 9 trial jobs per worker, shared by every condition
.venv/bin/python -m referral.hw7 pilot
.venv/bin/python -m referral.hw7 main --repeats 2          # B0, B1, R on the fresh competitors
.venv/bin/python -m referral.hw7 limit                     # B0 and R, four pools, tuning competitors
.venv/bin/python -m referral.hw7 retest --variant before
.venv/bin/python -m referral.hw7 retest --variant after
.venv/bin/python -m referral.hw7 analyze                   # summary.md, runs.csv, figures
```

Each step appends one JSON line per buyer request to `results/hw7/<step>.jsonl` and skips requests already recorded, so an interrupted step resumes. Each request's SQLite ledger (hash-chained Notary log, contracts, forecasts, deliveries, verdicts) is in `runs/hw7/<step>/`. Model outputs vary between runs, so expect the same pattern, not identical numbers; the simulated personas are deterministic given the persona seed.
