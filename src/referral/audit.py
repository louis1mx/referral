"""Independent check of an MVP run, from its SQLite ledger and the buyer's answer alone.

It does not trust what the agents or the Checker said. It checks:

1. the Notary hash chain and every entry's signature;
2. per job: the forecast was locked before the delivery, and the hidden-check commitment
   made at contract time opens to the slot the verdict revealed;
3. per delivered fact: the Checker's pass/fail against the corpus ground truth, which only
   evaluation code can see (a pass on a wrong value would be a Checker error), and what the
   semantic layer said (failing a correct, properly cited value would also be an error);
4. the buyer's final brief: every requested fact is present, equals the ground truth, and
   comes from a job the Checker passed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from .corpus import norm, same_value
from .models import Slot
from .service import ReferralService

BUYER_NAME = "acme-intel-agent"
REQUESTED = [("Ironbark AI", "latest_funding"), ("Gantry Labs", "latest_funding"),
             ("Gantry Labs", "headcount"), ("Dunmore Robotics", "flagship_product"),
             ("Everline Systems", "hq_city")]


def _same(value, truth: str) -> bool:
    return same_value(str(value or ""), truth)


def run_audit(run_dir: Path, say: Callable[[str], None] = print) -> dict:
    run_dir = Path(run_dir)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "copy.sqlite"
        shutil.copy(run_dir / "referral.sqlite", db)  # audit a copy; never touch the run's ledger
        service = ReferralService(str(db))
        report = _audit(service, run_dir, say)
        service.store.db.close()
    (run_dir / "audit.json").write_text(json.dumps(report, indent=2))
    return report


def _audit(service: ReferralService, run_dir: Path, say) -> dict:
    store, truth = service.store, service.corpus.truth
    say("=" * 78)
    say("Independent audit (reads only the ledger and the buyer's answer)")
    ledger = service.verify_ledger()
    say(f"1. Notary chain: {ledger['entries']} entries, hash chain and signatures ok={ledger['ok']}")

    buyer = service.find_agent(BUYER_NAME)
    jobs = store.query("SELECT * FROM jobs WHERE buyer_id = ? ORDER BY job_id", (buyer["agent_id"],)) if buyer else []
    job_reports, checker_errors, semantic_false_rejects = [], 0, 0
    say(f"2-3. Jobs hired by {BUYER_NAME}: {len(jobs)}")
    for job in jobs:
        worker = store.get("agents", "agent_id", job["worker_id"])
        entries = service.notary.entries(job["job_id"])
        kinds = [e["kind"] for e in entries]
        seq = {k: next(e["seq"] for e in entries if e["kind"] == k) for k in ("prediction", "delivery") if k in kinds}
        locked_first = "prediction" in seq and seq["prediction"] < seq.get("delivery", float("inf"))
        contract = next(e for e in entries if e["kind"] == "contract")
        verdict_entry = next((e for e in entries if e["kind"] == "verdict"), None)
        commitment_ok = None
        if verdict_entry:
            p = verdict_entry["payload"]
            opened = hashlib.sha256(f"{p['canary']}|{p['canary_salt']}".encode()).hexdigest()
            commitment_ok = opened == contract["payload"]["canary_commitment"]
        spec_slots = [Slot(s["competitor"], s["attribute"]) for s in job["spec"]["slots"]]
        delivered = {Slot(f["competitor"], f["attribute"]): f for f in (job["delivery"] or {}).get("facts", [])}
        verdicts = {v["slot"]: v for v in (job["verdict"] or {}).get("facts", [])}
        pred = job["prediction"] or {}
        say(f"   {job['job_id']}  worker={worker['name']} ({worker['model']})  band={job['band']}  "
            f"forecast p={pred.get('p_success')}  status={job['status']}")
        say(f"      forecast locked before delivery: {locked_first};  hidden-check commitment opens: {commitment_ok}")
        semantic = (job["verdict"] or {}).get("semantic_check")
        if semantic:
            say(f"      semantic layer ({semantic['model']}): {semantic['status']}, judged {semantic['judged']} "
                f"rule-passing facts, rejected {semantic['rejected']}")
        facts = []
        for i, slot in enumerate(spec_slots):
            f, v = delivered.get(slot), verdicts.get(i)
            correct = bool(f) and _same(f["value"], truth[slot])
            passed = bool(v and v["passed"])
            sem = (v or {}).get("semantic")
            if passed and not correct:
                checker_errors += 1
                agreement = "CHECKER ERROR: passed a wrong value"
            elif sem == "fail" and correct:
                semantic_false_rejects += 1
                agreement = "CHECKER ERROR: semantic layer failed a correct value"
            elif passed:
                agreement = "agrees (correct value)"
            elif not correct:
                agreement = "agrees (value wrong or missing)"
            else:
                agreement = "right value, but its citation failed"
            hidden = " [hidden check]" if v and v.get("canary") else ""
            say(f"      {slot.competitor:<20} {slot.attribute:<17} got={str(f['value'] if f else None):<12} "
                f"truth={truth[slot]:<10} checker={'pass' if passed else 'fail: ' + (v or {}).get('reason', 'none')}"
                f"{hidden}  -> {agreement}")
            facts.append({"slot": [slot.competitor, slot.attribute], "delivered": f and f["value"],
                          "truth": truth[slot], "checker_pass": passed, "correct": correct,
                          "hidden_check": bool(v and v.get("canary")), "semantic": sem})
        job_reports.append({"job_id": job["job_id"], "worker": worker["name"], "model": worker["model"],
                            "band": job["band"], "forecast": pred.get("p_success"), "status": job["status"],
                            "forecast_locked_first": locked_first, "commitment_ok": commitment_ok,
                            "semantic_check": semantic, "facts": facts})
    say(f"   Checker verdicts that contradict ground truth: false passes {checker_errors}, "
        f"semantic false rejects {semantic_false_rejects}")

    answer = json.loads((run_dir / "answer.json").read_text()) if (run_dir / "answer.json").exists() else None
    passed_jobs = {j["job_id"] for j in jobs if j["status"] == "passed"}
    answer_rows, answer_ok = [], bool(answer)
    say("4. Buyer's final brief vs ground truth:")
    given = {(norm(f.get("competitor", "")), norm(f.get("attribute", ""))): f for f in (answer or {}).get("facts", [])}
    for comp, attr in REQUESTED:
        f = given.get((norm(comp), norm(attr)))
        t = truth[Slot(comp, attr)]
        correct = bool(f) and _same(f.get("value"), t)
        from_passed = bool(f) and f.get("job_id") in passed_jobs
        answer_ok &= correct and from_passed
        say(f"   {comp:<20} {attr:<17} brief={str(f.get('value') if f else None):<12} truth={t:<10} "
            f"correct={correct}  from a passed job={from_passed}")
        answer_rows.append({"slot": [comp, attr], "value": f and f.get("value"), "truth": t,
                            "correct": correct, "from_passed_job": from_passed})

    insights = {}
    for name in sorted({j["worker"] for j in job_reports}):
        agent = service.find_agent(name)
        ins = service.get_insight(agent["agent_id"])
        insights[name] = ins
        say(f"   {name} now: [{ins.get('tier')}] {'; '.join(ins.get('guidance', [])[:3])}")

    all_ok = (ledger["ok"] and checker_errors == 0 and semantic_false_rejects == 0 and answer_ok
              and all(j["forecast_locked_first"] and j["commitment_ok"] for j in job_reports))
    say(f"RESULT: {'all checks pass' if all_ok else 'some checks FAILED'}")
    return {"ledger": {k: ledger[k] for k in ("ok", "entries", "head")}, "jobs": job_reports,
            "checker_false_passes": checker_errors, "semantic_false_rejects": semantic_false_rejects,
            "answer": answer_rows, "answer_ok": answer_ok,
            "insights": insights, "all_checks_pass": all_ok}


def main(run_dir: str) -> int:
    return 0 if run_audit(Path(run_dir))["all_checks_pass"] else 1
