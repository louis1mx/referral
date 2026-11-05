"""HW7 benchmark: does hiring through Referral put fewer wrong facts into a buyer's brief than
hiring by the workers' own descriptions?

Every hire runs in its own fresh service with its own SQLite ledger (kept under runs/hw7/), so
hires can run in parallel. Worker profiles come from one shared warm-up and are frozen, so
every condition sees the same history, as in evaluate.py. The real workers are Claude models
called through the claude CLI in headless mode (no tools, JSON schema); the unreliable ones
are the simulated personas. Facts are judged against corpus.truth here, in evaluation code,
never by the Checker.

    python -m referral.hw7 warmup | pilot | main | limit | retest | analyze
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import random
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from .corpus import Corpus, same_value
from .models import BANDS, Action, SimClock, Status, TaskSpec
from .scorer import build_profile
from .semantic import ApiRunner, ClaudeJudge
from .workers import PERSONAS, LLMOutputError, LLMWorker, SimWorker

OUT = Path("results/hw7")
RUNS = Path("runs/hw7")

FRESH = ["Dunmore Robotics", "Gantry Labs", "Halcyon Motion"]
TUNING = ["Borealis Automation", "Cobalt Dynamics", "Everline Systems", "Fathom Mechatronics",
          "Ironbark AI"]
SEEDS = {"warmup": 7001, "pilot": 7000, "main": 7002, "limit": 7003, "retest": 7004}
PERSONA_SEED = 865
BUDGET, DEADLINE_S = 2.0, 300.0
WORKER_EFFORT = "low"
JUDGE_MODEL = "claude-haiku-5-5"
DECLARED = {"haiku": 0.9, "sonnet": 0.9, "opus": 0.9, "overconfident": 0.95, "padder": 0.9}
CONDITIONS = {"B0": "self_report", "B1": "outcomes", "R": "referral"}
SETTLED = {str(s) for s in (Status.PASSED, Status.FAILED, Status.TIMEOUT)}
POOLS = {
    "main": ["haiku", "sonnet", "opus", "overconfident", "padder"],
    "u0": ["haiku", "sonnet", "opus"],
    "u80": ["sonnet", "overconfident", "padder", "overconfident-2", "padder-2"],
    "newcomer": ["haiku", "sonnet", "opus", "overconfident", "padder", "sonnet-newcomer"],
}

_lock = threading.Lock()


# --- the claude CLI as a Messages client ------------------------------------------------

class CliMessages:
    """`client.messages.create` backed by `claude -p` with no tools and a JSON schema, so
    LLMWorker and ApiRunner run unchanged on a signed-in Claude Code instead of an API key."""

    def __init__(self, timeout_s: float = 240.0):
        self.timeout_s = timeout_s
        self.messages = self

    def create(self, *, model, system, messages, output_config, timeout=None, **_):
        sys_text = system if isinstance(system, str) else "\n\n".join(b["text"] for b in system)
        cmd = ["claude", "-p", messages[0]["content"], "--model", model, "--system-prompt", sys_text,
               "--setting-sources", "", "--settings", '{"disableAllHooks": true}', "--tools", "",
               "--strict-mcp-config", "--output-format", "json", "--no-session-persistence",
               "--json-schema", json.dumps(output_config["format"]["schema"])]
        if output_config.get("effort"):
            cmd += ["--effort", output_config["effort"]]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                                  timeout=timeout or self.timeout_s)
            out = json.loads(done.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            raise LLMOutputError(f"claude CLI failed: {e}") from e
        u = out.get("usage") or {}
        usage = SimpleNamespace(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                                cache_read_input_tokens=u.get("cache_read_input_tokens", 0),
                                cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0))
        if out.get("is_error") or not isinstance(out.get("structured_output"), dict):
            raise LLMOutputError(f"claude CLI returned no structured output: {str(out.get('result'))[:200]}")
        text = json.dumps(out["structured_output"])
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=text)])


# --- pools -------------------------------------------------------------------------------

def make_worker(key: str, corpus: Corpus, persona_seed: int):
    if key in ("haiku", "sonnet", "opus"):
        return LLMWorker(key, corpus, client=CliMessages(), effort=WORKER_EFFORT, declared_success=DECLARED[key])
    if key == "sonnet-newcomer":
        return LLMWorker("sonnet", corpus, client=CliMessages(), effort=WORKER_EFFORT,
                         name="claude-sonnet-newcomer", owner="owner-sonnet-newcomer", declared_success=0.9)
    base, _, copy = key.partition("-")
    p = PERSONAS[base]
    if copy:
        p = dataclasses.replace(p, key=key, name=f"{p.name}-{copy}", owner=f"{p.owner}-{copy}")
    w = SimWorker(p, corpus, persona_seed)
    w.declared_success = DECLARED[base]
    return w


def fresh_service(corpus: Corpus, path: Path):
    from .service import ReferralService
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    s = ReferralService(str(path), SimClock(), corpus, seed=None)
    judge_runner = ApiRunner(client=CliMessages(), effort="low")
    s.judge = ClaudeJudge(JUDGE_MODEL, runner=judge_runner)
    b = s.register_agent("hw7-buyer", "buyer", "owner-hw7-buyer", "scripted-buyer")
    return s, b, judge_runner


def worker_usage(w, job_id: str) -> dict:
    calls = [c for c in getattr(w, "calls", []) if c.job_id == job_id]
    return {"api_usd": sum(c.usd for c in calls), "tokens": sum(c.input_tokens + c.output_tokens
                                                                + c.cache_read_tokens + c.cache_write_tokens
                                                                for c in calls),
            "api_seconds": sum(c.seconds for c in calls),
            "api_error": getattr(w, "errors", {}).get(job_id)}


# --- warm-up -----------------------------------------------------------------------------

def warmup_tasks(corpus: Corpus) -> list[TaskSpec]:
    rng = random.Random(f"hw7-warmup|{SEEDS['warmup']}")
    return [corpus.make_task(rng, band, budget=BUDGET, deadline_s=DEADLINE_S, competitors=TUNING)
            for band in BANDS for _ in range(3)]


def run_warmup(keys: list[str], parallel: int = 6) -> dict:
    """Every worker gets the same 9 trial jobs (3 per band) on tuning competitors. Three per band
    is the least at which the Scorer may use a band's forecasts (MIN_FORECASTS_FOR_TRUST)."""
    path = OUT / "warmup.json"
    done = json.loads(path.read_text()) if path.exists() else {"agents": {}, "jobs": {}}
    corpus = Corpus.default()
    tasks = warmup_tasks(corpus)
    todo = [(k, i) for k in keys for i in range(len(tasks)) if f"{k}|{i}" not in done["jobs"]]

    def one(item):
        key, i = item
        s, b, judge = fresh_service(corpus, RUNS / "warmup" / f"{key}-{i}.sqlite")
        w = make_worker(key, corpus, PERSONA_SEED)
        w.register(s)
        job = s.direct_hire(b["agent_id"], b["key"], w.agent_id, tasks[i].to_dict())
        row = s.store.get("jobs", "job_id", job["job_id"])
        agent = s.store.get("agents", "agent_id", w.agent_id)
        u = worker_usage(w, job["job_id"])
        s.store.db.close()
        with _lock:
            done["agents"][key] = {k: agent[k] for k in ("agent_id", "name", "model", "price")}
            done["jobs"][f"{key}|{i}"] = {"row": row, "usage": u,
                                         "judge_usd": sum(c["usd"] for c in judge.calls)}
            path.write_text(json.dumps(done, indent=1, default=str))
        print(f"warmup {key} task {i}: {row['status']}", flush=True)

    with ThreadPoolExecutor(parallel) as ex:
        list(ex.map(one, todo))
    return done


def frozen_profiles(keys: list[str]) -> dict:
    done = json.loads((OUT / "warmup.json").read_text())
    out = {}
    for k in keys:
        if k not in done["agents"]:
            continue   # no record: the newcomer
        rows = [v["row"] for j, v in sorted(done["jobs"].items()) if j.split("|")[0] == k]
        rows = [r for r in rows if r["status"] in SETTLED]
        for n, r in enumerate(rows):
            r["settled_at"] = float(n)   # order by trial index
        agent = done["agents"][k]
        out[agent["agent_id"]] = build_profile(agent, rows, None, {})
    return out


# --- one buyer request -------------------------------------------------------------------

def judge_facts(corpus: Corpus, spec: TaskSpec, facts: list[dict]) -> list[dict]:
    """Ground truth for each requested slot, from evaluation code only."""
    rows = []
    by_slot = {(f["competitor"], f["attribute"]): f for f in facts if f.get("value") is not None}
    for slot in spec.slots:
        f = by_slot.get((slot.competitor, slot.attribute))
        truth = corpus.truth[slot]
        if f is None:
            rows.append({"slot": [slot.competitor, slot.attribute], "state": "missing", "proper": False})
            continue
        doc = corpus.docs.get(f.get("doc_id") or "")
        ok = bool(doc) and same_value(str(f["value"]), truth)
        proper = ok and doc.subject == slot.competitor and (f.get("quote") or "").lower() in doc.text.lower()
        rows.append({"slot": [slot.competitor, slot.attribute], "state": "correct" if ok else "wrong",
                     "proper": proper, "checker": f.get("check")})
    return rows


def run_request(step: str, cond: str, strategy: str, spec: TaskSpec, task_id: str, band: str,
                pool: list[str], profiles: dict, repeat: int, persona_seed: int,
                min_success: float | None = None) -> dict:
    corpus = Corpus.default()
    tag = f"{step}/{cond}-r{repeat}-{task_id}"
    s, b, judge = fresh_service(corpus, RUNS / f"{tag}.sqlite")
    workers = {}
    for k in pool:
        w = make_worker(k, corpus, persona_seed)
        w.register(s)
        workers[w.agent_id] = w
    t0 = time.perf_counter()
    tried, attempts, first_match = [], [], None
    for attempt in range(2):
        m = s.request_match(b["agent_id"], b["key"], spec.to_dict(), strategy, profiles,
                            exclude=tuple(tried), min_success=min_success)
        first_match = first_match or m
        if m["action"] == Action.NO_MATCH:
            attempts.append({"attempt": attempt + 1, "no_match": True})
            break
        job = s.hire(b["agent_id"], b["key"], m["match_id"])
        rec = s.get_record(b["agent_id"], b["key"], job["job_id"])
        w = workers[m["candidate"]["agent_id"]]
        tried.append(w.agent_id)
        facts = judge_facts(corpus, spec, rec["facts"])
        attempts.append({"attempt": attempt + 1, "no_match": False, "worker": rec["worker"],
                         "action": m["action"], "status": rec["status"], "cost": rec["cost"],
                         "reported_cost": s._job(job["job_id"])["reported_cost"],
                         "seconds": rec["elapsed_s"], "facts": facts, **worker_usage(w, job["job_id"])})
        if rec["status"] == Status.PASSED:
            break
    passed = next((a for a in attempts if a.get("status") == Status.PASSED), None)
    first = attempts[0] if attempts and not attempts[0]["no_match"] else None
    n = len(spec.slots)

    def brief(att):
        states = [f["state"] for f in att["facts"]] if att else ["missing"] * n
        return {"correct": states.count("correct"), "wrong": states.count("wrong"),
                "missing": states.count("missing")}

    out = {"step": step, "cond": cond, "strategy": strategy, "repeat": repeat, "task_id": task_id,
           "band": band, "pool": pool, "slots": [[x.competitor, x.attribute] for x in spec.slots],
           "first_pick": first["worker"] if first else None,
           "first_action": first_match["action"] if first_match else None,
           "attempts": attempts, "brief": brief(passed), "raw_brief": brief(first),
           "cost": sum(a.get("cost") or 0 for a in attempts),
           "api_usd": sum(a.get("api_usd") or 0 for a in attempts),
           "judge_usd": sum(c["usd"] for c in judge.calls),
           "tokens": sum(a.get("tokens") or 0 for a in attempts) + sum(
               c["input_tokens"] + c["output_tokens"] for c in judge.calls),
           "seconds": sum(a.get("seconds") or 0 for a in attempts),
           "wall_s": time.perf_counter() - t0,
           "ledger_ok": s.verify_ledger()["ok"], "ledger": f"runs/hw7/{tag}.sqlite"}
    s.store.db.close()
    return out


def run_batch(step: str, items: list[dict], parallel: int = 6) -> list[dict]:
    path = OUT / f"{step}.jsonl"
    seen = set()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            seen.add((r["cond"], r["repeat"], r["task_id"]))
    todo = [it for it in items if (it["cond"], it["repeat"], it["task_id"]) not in seen]

    def one(it):
        r = run_request(step=step, **it)
        with _lock, path.open("a") as f:
            f.write(json.dumps(r, default=str) + "\n")
        print(f"{step} {it['cond']} r{it['repeat']} {it['task_id']}: pick={r['first_pick']} "
              f"brief={r['brief']} cost={r['cost']:.2f} wall={r['wall_s']:.0f}s", flush=True)
        return r

    with ThreadPoolExecutor(parallel) as ex:
        list(ex.map(one, todo))
    return [json.loads(x) for x in path.read_text().splitlines()]


def tasks_for(step: str, competitors: list[str], per_band: int) -> list[tuple[str, str, TaskSpec]]:
    corpus = Corpus.default()
    rng = random.Random(f"hw7-{step}|{SEEDS[step]}")
    out = []
    for band in BANDS:
        for i in range(per_band):
            out.append((f"{band}-{i}", str(band), corpus.make_task(rng, band, budget=BUDGET, deadline_s=DEADLINE_S,
                                                                    competitors=competitors)))
    return out


def items(step, conds, tasks, pool, repeats=1, **extra):
    profiles = frozen_profiles(pool)
    return [{"cond": c, "strategy": CONDITIONS.get(c, c), "spec": spec, "task_id": tid, "band": band,
             "pool": pool, "profiles": profiles, "repeat": r, "persona_seed": PERSONA_SEED + r, **extra}
            for r in range(repeats) for tid, band, spec in tasks for c in conds]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="referral.hw7")
    ap.add_argument("step", choices=["warmup", "pilot", "main", "limit", "retest", "analyze"])
    ap.add_argument("--parallel", type=int, default=6)
    ap.add_argument("--variant", default="before", help="retest: before | after")
    ap.add_argument("--repeats", type=int, default=2)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.step == "warmup":
        run_warmup(sorted({k for p in POOLS.values() for k in p} - {"sonnet-newcomer"}), a.parallel)
    elif a.step == "pilot":
        run_batch("pilot", items("pilot", list(CONDITIONS), tasks_for("pilot", TUNING, 1)[::2], POOLS["main"]),
                  a.parallel)
    elif a.step == "main":
        run_batch("main", items("main", list(CONDITIONS), tasks_for("main", FRESH, 4), POOLS["main"],
                                repeats=a.repeats), a.parallel)
    elif a.step == "limit":
        tasks = tasks_for("limit", TUNING, 2)
        for setting in ("u0", "main", "u80", "newcomer"):
            run_batch(f"limit-{setting}", items(f"limit-{setting}", ["B0", "R"], tasks, POOLS[setting]),
                      a.parallel)
    elif a.step == "retest":
        from . import hw7_change
        extra = hw7_change.options(a.variant)
        run_batch(f"retest-{a.variant}", items(f"retest-{a.variant}", ["R"], tasks_for("retest", FRESH, 2),
                                               hw7_change.POOL, **extra), a.parallel)
    else:
        from .hw7_analyze import analyze
        analyze()


if __name__ == "__main__":
    main()
