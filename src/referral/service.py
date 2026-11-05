"""ReferralService: one service that owns every business rule and permission check.

The MCP server, the simulations and the tests all go through this class, so the rules
below hold no matter who is calling:

- every agent registers first and authenticates with its key on every call;
- a worker can only act on jobs assigned to it, and must lock a forecast before it
  delivers; a locked forecast cannot be revised;
- only the Checker writes verdicts; a timeout counts as a failure;
- a buyer can only read its own jobs;
- clients get tiers and guidance, never raw scores.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import random
import secrets
import threading
from collections.abc import Callable
from dataclasses import asdict

from . import matcher
from .checker import attribute_failures, check_delivery, review_semantics
from .credentials import Issuer, verify_credential
from .corpus import Corpus, slug
from .models import (Action, Band, Fact, LiveClock, ReferralError, SimClock, Slot, Status,
                     TaskSpec, SETTLED)
from .notary import Notary, Store, canonical
from .scorer import Profile, build_profile, evidence_label, insights

DERIVE = object()
CREDENTIAL_TTL_S = 7 * 24 * 3600

ACTION_NOTES = {
    Action.HIRE: "Call hire(match_id) to lock a contract. The worker must lock its forecast "
                 "before it delivers, and the Checker verifies every fact.",
    Action.BOUNDED_TRIAL: "Only trial-tier workers fit this task. Hire as a bounded trial and "
                          "keep the stakes low; the result will count toward its record.",
    Action.NO_MATCH: "No worker on file is likely enough to pass this task within the budget "
                     "and deadline. Split the task, relax the deadline or raise the budget.",
}


def locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class ReferralService:
    def __init__(self, db_path: str = ":memory:", clock: SimClock | None = None,
                 corpus: Corpus | None = None, seed: int | None = None):
        """`seed` is for simulations only: it makes the hidden canary slot a reproducible
        function of (seed, task) so strategies can be compared on identical draws. Live
        services leave it unset and draw the canary from `secrets`, so a worker that
        reads this code still cannot tell which slot is checked."""
        self.store = Store(db_path)
        self.clock = clock or LiveClock()
        self.corpus = corpus or Corpus.default()
        self.seed = seed
        # The Checker's semantic layer (semantic.Judge). None runs the rule layer only, as
        # simulations do; the MVP server sets it after seeding the simulated history.
        self.judge = None
        # Benchmark priors per model, set by the operator. Empty means every model starts
        # from the same neutral prior: a prior nobody can check should not favor anyone.
        self.model_priors: dict[str, float] = {}
        self.notary = Notary(self.store, self._key_of)
        self._handlers: dict[str, Callable[[ReferralService, dict], None]] = {}
        self._lock = threading.RLock()
        self.issuer = Issuer()
        self.service_id = self._register_internal("referral", "service")
        self.checker_id = self._register_internal("checker", "checker")

    # --- identity ------------------------------------------------------------------

    def _key_of(self, agent_id: str) -> str:
        row = self.store.get("agents", "agent_id", agent_id)
        if row is None:
            raise ReferralError(f"unknown agent {agent_id!r}")
        return row["key"]

    def _register_internal(self, name: str, role: str) -> str:
        agent_id = f"agt-{name}"
        if self.store.get("agents", "agent_id", agent_id) is None:
            self.store.insert("agents", {"agent_id": agent_id, "name": name, "role": role,
                                         "owner": "referral", "model": None, "key": secrets.token_hex(16),
                                         "domains": [], "created_at": self.clock.now()})
        return agent_id

    @locked
    def add_checker(self, name: str) -> dict:
        """Operator-only: authorize an extra checker (for example an external validator)."""
        agent_id = self._register_internal(f"checker-{slug(name)}", "checker")
        return {"agent_id": agent_id, "key": self._key_of(agent_id)}

    @locked
    def register_agent(self, name: str, role: str, owner: str, model: str,
                       price: float | None = None, typical_seconds: float | None = None,
                       domains: list[str] | None = None, declared_success: float | None = None) -> dict:
        """`declared_success` is the worker's own claim about its success rate. Referral records
        it so buyers can compare it with checked results; its own Matcher never reads it."""
        if role not in ("buyer", "worker"):
            raise ReferralError("role must be 'buyer' or 'worker'")
        if declared_success is not None and not 0.0 <= declared_success <= 1.0:
            raise ReferralError("declared_success must be in [0, 1]")
        if self.store.get("agents", "name", name) is not None:
            raise ReferralError(f"an agent named {name!r} is already registered")
        if role == "worker" and price is None:
            raise ReferralError("workers must declare a price per job")
        agent_id = f"agt-{slug(name)}"
        key = secrets.token_hex(16)
        self.store.insert("agents", {
            "agent_id": agent_id, "name": name, "role": role, "owner": owner, "model": model,
            "key": key, "domains": domains or ["sourced-research"], "price": price,
            "typical_seconds": typical_seconds, "declared_success": declared_success,
            "created_at": self.clock.now(),
        })
        self.notary.append("register", agent_id, {
            "name": name, "role": role, "owner": owner, "model": model, "price": price,
            "declared_success": declared_success,
            "key_fingerprint": hashlib.sha256(key.encode()).hexdigest()[:16],
        }, None, self.clock.now())
        return {"agent_id": agent_id, "key": key, "tier": "trial",
                "note": "Keep this key; every call is authenticated and logged under it."}

    def _auth(self, agent_id: str, key: str, roles: tuple[str, ...] | None = None) -> dict:
        row = self.store.get("agents", "agent_id", agent_id)
        if row is None or not hmac.compare_digest(row["key"], key or ""):
            raise ReferralError("unknown agent or wrong key")
        if roles and row["role"] not in roles:
            raise ReferralError(f"{row['role']} agents cannot do this")
        return row

    @locked
    def declare_model_change(self, agent_id: str, key: str, model: str) -> dict:
        agent = self._auth(agent_id, key, ("worker",))
        if model == agent["model"]:
            raise ReferralError("that is already the declared model")
        self.store.update("agents", "agent_id", agent_id, {"model": model})
        self.notary.append("model_change", agent_id, {"from": agent["model"], "to": model},
                           None, self.clock.now())
        return {"agent_id": agent_id, "model": model, "tier": "trial",
                "note": "A new model starts a new trial profile."}

    def find_agent(self, name: str) -> dict | None:
        return self.store.get("agents", "name", name)

    def attach_worker(self, agent_id: str, handler: Callable[[ReferralService, dict], None]) -> None:
        """Run `handler(service, assignment)` whenever this worker is hired (in-process workers)."""
        self._handlers[agent_id] = handler

    # --- profiles ------------------------------------------------------------------

    def _settled_jobs(self, worker_id: str) -> list[dict]:
        marks = ",".join("?" for _ in SETTLED)
        return self.store.query(
            f"SELECT * FROM jobs WHERE worker_id = ? AND status IN ({marks}) "
            "ORDER BY settled_at, job_id", (worker_id, *SETTLED))

    @locked
    def profile(self, agent_id: str) -> Profile:
        """Internal view with raw numbers. Never returned to clients as-is."""
        agent = self.store.get("agents", "agent_id", agent_id)
        jobs = self._settled_jobs(agent_id)
        current = [j for j in jobs if j["worker_model"] == agent["model"]]
        previous = sorted({j["worker_model"] for j in jobs} - {agent["model"]})
        return build_profile(agent, current, previous, self.model_priors)

    def workers(self, domain: str) -> list[dict]:
        return [a for a in self.store.query("SELECT * FROM agents WHERE role = 'worker' ORDER BY name")
                if domain in a["domains"]]

    @locked
    def get_insight(self, agent_id: str) -> dict:
        agent = self.store.get("agents", "agent_id", agent_id)
        if agent is None or agent["role"] != "worker":
            raise ReferralError(f"no worker {agent_id!r}")
        p = self.profile(agent_id)
        return {"agent_id": agent_id, "name": agent["name"], "tier": str(p.tier),
                "evidence": evidence_label(p.n_counted), "guidance": insights(p)}

    # --- credentials ---------------------------------------------------------------

    @locked
    def get_credential(self, agent_id: str, domain: str | None = None) -> dict:
        """A signed attestation of a worker's tier that other registries can carry."""
        agent = self.store.get("agents", "agent_id", agent_id)
        if agent is None or agent["role"] != "worker":
            raise ReferralError(f"no worker {agent_id!r}")
        domain = domain or agent["domains"][0]
        if domain not in agent["domains"]:
            raise ReferralError(f"{agent['name']} is not registered for {domain!r}")
        p = self.profile(agent_id)
        now = self.clock.now()
        subject = {"id": agent_id, "name": agent["name"], "model": agent["model"], "domain": domain,
                   "tier": str(p.tier), "evidence": evidence_label(p.n_counted),
                   "notaryHead": self.notary.head()}
        credential = self.issuer.issue(subject, now, CREDENTIAL_TTL_S)
        self.notary.append("credential_issued", self.service_id, {
            "subject": agent_id, "domain": domain, "tier": str(p.tier),
            "validUntil": credential["validUntil"]}, None, now)
        return credential

    def get_issuer_key(self) -> dict:
        return {"issuer": self.issuer.issuer_id, "alg": "Ed25519", "jwk": self.issuer.public_jwk}

    def verify_credential(self, credential: dict) -> dict:
        ok, reason = verify_credential(credential, self.issuer.public_jwk, self.clock.now())
        return {"valid": ok, "reason": reason}

    # --- matching ------------------------------------------------------------------

    @locked
    def request_match(self, agent_id: str, key: str, task: dict, strategy: str = "referral",
                      profiles: dict[str, Profile] | None = None,
                      exclude: tuple[str, ...] = (), min_success: float | None = None) -> dict:
        buyer = self._auth(agent_id, key, ("buyer", "worker"))
        self.expire_overdue()
        spec = TaskSpec.from_dict(task)
        self.corpus.validate(spec)
        if spec.budget <= 0 or spec.deadline_s <= 0:
            raise ReferralError("budget and deadline must be positive")
        band = self.corpus.difficulty(spec.slots)
        pool = [(a, (profiles or {}).get(a["agent_id"]) or self.profile(a["agent_id"]))
                for a in self.workers(spec.domain)
                if a["agent_id"] != agent_id and a["owner"] != buyer["owner"]]
        if min_success is not None and not 0.0 <= min_success <= 1.0:
            raise ReferralError("min_success must be in [0, 1]")
        # Buyers may name excluded workers by agent_id or by name.
        excluded = {(self.find_agent(x) or {"agent_id": x})["agent_id"] for x in exclude}
        decision = matcher.decide(spec, band, pool, strategy, excluded, min_success)
        match_id = f"match-{self.store.count('matches') + 1:04d}"
        chosen = decision.chosen.agent["agent_id"] if decision.chosen else None
        self.store.insert("matches", {"match_id": match_id, "buyer_id": agent_id,
                                      "spec": spec.to_dict(), "band": str(band), "candidate_id": chosen,
                                      "action": str(decision.action), "strategy": strategy,
                                      "created_at": self.clock.now()})
        self.notary.append("match", self.service_id, {
            "match_id": match_id, "buyer": agent_id, "band": str(band), "strategy": strategy,
            "action": str(decision.action), "candidate": chosen,
        }, None, self.clock.now())
        return self._match_view(match_id, decision, band)

    def _match_view(self, match_id: str, decision: matcher.Decision, band: Band) -> dict:
        view = {"match_id": match_id, "difficulty_band": str(band), "action": str(decision.action),
                "candidate": None, "alternatives": [], "note": ACTION_NOTES[decision.action]}
        if decision.chosen:
            c = decision.chosen
            view["candidate"] = {
                "agent_id": c.agent["agent_id"], "name": c.agent["name"], "tier": str(c.profile.tier),
                "evidence": evidence_label(c.profile.bands[band].n), "price": c.agent["price"],
                "guidance": insights(c.profile, band)[:3],
            }
            view["alternatives"] = [{"name": o.agent["name"], "tier": str(o.profile.tier)}
                                    for o in decision.ranked if o is not c][:2]
        return view

    # --- contracts -----------------------------------------------------------------

    @locked
    def hire(self, agent_id: str, key: str, match_id: str) -> dict:
        self._auth(agent_id, key, ("buyer", "worker"))
        match = self.store.get("matches", "match_id", match_id)
        if match is None or match["buyer_id"] != agent_id:
            raise ReferralError("no such match for this buyer")
        if match["action"] == Action.NO_MATCH:
            raise ReferralError("this match found no eligible worker; request a new match")
        if self.store.query("SELECT job_id FROM jobs WHERE match_id = ?", (match_id,)):
            raise ReferralError("this match was already used; request a new match to rematch")
        spec = TaskSpec.from_dict(match["spec"])
        return self._open_job(agent_id, match["candidate_id"], spec, Band(match["band"]),
                              trial=match["action"] == Action.BOUNDED_TRIAL, match_id=match_id)

    @locked
    def direct_hire(self, agent_id: str, key: str, worker_id: str, task: dict) -> dict:
        """Hire a named worker without the Matcher, e.g. repeat business."""
        self._auth(agent_id, key, ("buyer", "worker"))
        worker = self.store.get("agents", "agent_id", worker_id)
        if worker is None or worker["role"] != "worker":
            raise ReferralError(f"no worker {worker_id!r}")
        spec = TaskSpec.from_dict(task)
        self.corpus.validate(spec)
        return self._open_job(agent_id, worker_id, spec, self.corpus.difficulty(spec.slots))

    @locked
    def subcontract(self, agent_id: str, key: str, parent_job_id: str, worker_id: str,
                    slot_indices: list[int], budget: float | None = None) -> dict:
        """Open a second-hop contract for some slots of a job assigned to the caller."""
        self._auth(agent_id, key, ("worker",))
        parent = self._job(parent_job_id)
        if parent is None or parent["worker_id"] != agent_id:
            raise ReferralError("you can only subcontract your own jobs")
        if parent["status"] not in (Status.DISPATCHED, Status.PREDICTED):
            raise ReferralError(f"parent job is already {parent['status']}")
        worker = self.store.get("agents", "agent_id", worker_id)
        if worker is None or worker["role"] != "worker" or worker_id == agent_id:
            raise ReferralError(f"cannot subcontract to {worker_id!r}")
        spec = TaskSpec.from_dict(parent["spec"])
        if not slot_indices or any(i < 0 or i >= len(spec.slots) for i in slot_indices):
            raise ReferralError("slot_indices must point into the parent task")
        slots = [spec.slots[i] for i in slot_indices]
        sub = TaskSpec(spec.company, slots, budget if budget is not None else worker["price"],
                       max(1.0, parent["deadline_at"] - self.clock.now()), spec.corpus_ids,
                       spec.acceptance, spec.domain)
        # The hidden check follows its slot, so both hops are held to the same standard.
        canary = slot_indices.index(parent["canary"]) if parent["canary"] in slot_indices else None
        return self._open_job(agent_id, worker_id, sub, self.corpus.difficulty(slots),
                              parent_job_id=parent_job_id, canary=canary)

    def _open_job(self, buyer_id: str, worker_id: str, spec: TaskSpec, band: Band, *,
                  trial: bool = False, match_id: str | None = None,
                  parent_job_id: str | None = None, canary=DERIVE) -> dict:
        buyer = self.store.get("agents", "agent_id", buyer_id)
        worker = self.store.get("agents", "agent_id", worker_id)
        job_id = f"job-{self.store.count('jobs') + 1:04d}"
        if canary is DERIVE:
            if self.seed is None:
                canary = secrets.randbelow(len(spec.slots))
            else:
                canary = random.Random(f"{self.seed}|{canonical(spec.to_dict())}").randrange(len(spec.slots))
        salt = secrets.token_hex(8)
        now = self.clock.now()
        self_dealing = buyer["owner"] == worker["owner"]
        self.store.insert("jobs", {
            "job_id": job_id, "buyer_id": buyer_id, "worker_id": worker_id,
            "worker_model": worker["model"], "parent_job_id": parent_job_id, "match_id": match_id,
            "spec": spec.to_dict(), "band": str(band), "canary": canary, "canary_salt": salt,
            "status": Status.DISPATCHED, "trial": int(trial), "self_dealing": int(self_dealing),
            "created_at": now, "deadline_at": now + spec.deadline_s, "budget": spec.budget,
            "price": worker["price"],
        })
        self.notary.append("contract", buyer_id, {
            "buyer": buyer_id, "worker": worker_id, "worker_model": worker["model"],
            "band": str(band), "budget": spec.budget, "deadline_s": spec.deadline_s,
            "price": worker["price"], "spec": spec.to_dict(), "parent_job_id": parent_job_id,
            "trial": trial, "self_dealing": self_dealing,
            "canary_commitment": hashlib.sha256(f"{canary}|{salt}".encode()).hexdigest(),
        }, job_id, now)
        handler = self._handlers.get(worker_id)
        if handler is not None:
            try:
                handler(self, self._assignment(self._job(job_id)))
            except ReferralError as e:
                self.notary.append("worker_error", self.service_id, {"error": str(e)}, job_id,
                                   self.clock.now())
        job = self._job(job_id)
        return {"job_id": job_id, "worker": worker["name"], "status": job["status"],
                "difficulty_band": str(band), "self_commissioned": self_dealing}

    def _job(self, job_id: str) -> dict | None:
        return self.store.get("jobs", "job_id", job_id)

    def _assignment(self, job: dict) -> dict:
        buyer = self.store.get("agents", "agent_id", job["buyer_id"])
        return {"job_id": job["job_id"], "buyer": buyer["name"], "task": job["spec"],
                "difficulty_band": job["band"], "seconds_left": job["deadline_at"] - self.clock.now(),
                "parent_job_id": job["parent_job_id"],
                "instructions": "Lock your forecast with submit_prediction before you start, "
                                "then return the facts with submit_delivery."}

    @locked
    def get_assignment(self, agent_id: str, key: str) -> list[dict]:
        self._auth(agent_id, key, ("worker",))
        self.expire_overdue()
        rows = self.store.query("SELECT * FROM jobs WHERE worker_id = ? AND status IN (?, ?) "
                                "ORDER BY job_id", (agent_id, Status.DISPATCHED, Status.PREDICTED))
        return [self._assignment(j) for j in rows]

    def _assigned(self, agent_id: str, job_id: str) -> dict:
        job = self._job(job_id)
        if job is None or job["worker_id"] != agent_id:
            raise ReferralError("that job is not assigned to you")
        return job

    @locked
    def submit_prediction(self, agent_id: str, key: str, job_id: str, p_success: float,
                          cost: float, finish_seconds: float) -> dict:
        self._auth(agent_id, key, ("worker",))
        job = self._assigned(agent_id, job_id)
        attempt = {"p_success": p_success, "cost": cost, "finish_s": finish_seconds}
        if job["prediction"] is not None or job["status"] != Status.DISPATCHED:
            reason = "forecast already locked" if job["prediction"] else f"job is {job['status']}"
            self.notary.append("prediction_rejected", agent_id, {"attempted": attempt, "reason": reason},
                               job_id, self.clock.now())
            raise ReferralError(f"{reason}; a forecast cannot be revised after it is locked")
        if not 0.0 <= p_success <= 1.0 or cost < 0 or finish_seconds <= 0:
            raise ReferralError("p_success must be in [0, 1]; cost and finish time must be positive")
        now = self.clock.now()
        prediction = {**attempt, "locked_at": now}
        self.store.update("jobs", "job_id", job_id, {"prediction": prediction, "status": Status.PREDICTED})
        self.notary.append("prediction", agent_id, prediction, job_id, now)
        return {"job_id": job_id, "locked": True, "locked_at": now}

    @locked
    def submit_delivery(self, agent_id: str, key: str, job_id: str, facts: list[dict],
                        cost: float | None = None) -> dict:
        self._auth(agent_id, key, ("worker",))
        job = self._assigned(agent_id, job_id)
        if job["status"] == Status.DISPATCHED:
            self.notary.append("delivery_rejected", agent_id, {"reason": "no locked forecast"},
                               job_id, self.clock.now())
            raise ReferralError("lock a forecast with submit_prediction before delivering")
        if job["status"] != Status.PREDICTED:
            raise ReferralError(f"job is already {job['status']}")
        parsed = [Fact.from_dict(f) for f in facts]
        now = self.clock.now()
        elapsed = now - job["created_at"]
        # The buyer is charged the price locked in the contract. What the worker says it spent
        # is kept beside it, as a signal about its cost forecasts, but never billed.
        reported = float(cost) if cost is not None else None
        cost = job["price"]
        self.notary.append("delivery", agent_id, {"facts": [asdict(f) for f in parsed], "cost": cost,
                                                  "reported_cost": reported, "elapsed_s": elapsed}, job_id, now)
        self.store.update("jobs", "job_id", job_id, {"reported_cost": reported})
        self.store.update("jobs", "job_id", job_id, {"delivery": {"facts": [asdict(f) for f in parsed]}})
        if now > job["deadline_at"]:
            self._settle(job, Status.TIMEOUT, [], cost, elapsed, [agent_id], within_budget=True)
        else:
            spec = TaskSpec.from_dict(job["spec"])
            verdicts = check_delivery(spec, job["canary"], parsed, self.corpus)
            semantic = None
            if self.judge is not None:
                # Runs under the service lock: one model call per delivery, a few seconds.
                verdicts, semantic = review_semantics(verdicts, spec, parsed, self.corpus, self.judge)
            within_budget = cost <= spec.budget + 1e-9
            if all(v.passed for v in verdicts) and within_budget:
                self._settle(job, Status.PASSED, verdicts, cost, elapsed, [], within_budget, semantic)
            else:
                subs = {j["job_id"]: j for j in
                        self.store.query("SELECT * FROM jobs WHERE parent_job_id = ?", (job_id,))}
                culprits = attribute_failures(agent_id, spec, parsed, verdicts, subs) or [agent_id]
                self._settle(job, Status.FAILED, verdicts, cost, elapsed, culprits, within_budget, semantic)
        return {"job_id": job_id, "status": self._job(job_id)["status"]}

    def _settle(self, job: dict, status: Status, verdicts: list, cost: float | None,
                elapsed: float | None, culprits: list[str], within_budget: bool,
                semantic: dict | None = None) -> None:
        now = self.clock.now()
        verdict = {"facts": [asdict(v) for v in verdicts], "within_budget": within_budget,
                   "timeout": status == Status.TIMEOUT, "semantic_check": semantic}
        self.store.update("jobs", "job_id", job["job_id"], {
            "status": status, "verdict": verdict, "outcome": int(status == Status.PASSED),
            "cost": cost, "elapsed": elapsed, "attributed": culprits, "settled_at": now,
        })
        self.notary.append("verdict", self.checker_id, {
            "status": str(status), "facts": [[v.slot, v.passed, v.reason] for v in verdicts],
            "within_budget": within_budget, "failure_traced_to": culprits, "semantic_check": semantic,
            # Opening the commitment lets an auditor confirm which slot was the hidden check.
            "canary": job["canary"], "canary_salt": job["canary_salt"],
        }, job["job_id"], now)

    @locked
    def expire_overdue(self) -> int:
        now = self.clock.now()
        rows = self.store.query("SELECT * FROM jobs WHERE status IN (?, ?) AND deadline_at < ?",
                                (Status.DISPATCHED, Status.PREDICTED, now))
        for job in rows:
            self._settle(job, Status.TIMEOUT, [], None, now - job["created_at"], [job["worker_id"]], True)
        return len(rows)

    @locked
    def add_validator_note(self, agent_id: str, key: str, job_id: str, note: str) -> dict:
        """Extra evidence from an authorized checker; ordinary agents are refused."""
        self._auth(agent_id, key, ("checker",))
        if self._job(job_id) is None:
            raise ReferralError(f"no job {job_id!r}")
        self.notary.append("validator_note", agent_id, {"note": note}, job_id, self.clock.now())
        return {"job_id": job_id, "logged": True}

    # --- records -------------------------------------------------------------------

    @locked
    def get_record(self, agent_id: str, key: str, job_id: str) -> dict:
        self._auth(agent_id, key)
        job = self._job(job_id)
        if job is None or job["buyer_id"] != agent_id:
            raise ReferralError("buyers can only see their own jobs")
        self.expire_overdue()
        job = self._job(job_id)
        worker = self.store.get("agents", "agent_id", job["worker_id"])
        spec = TaskSpec.from_dict(job["spec"])
        facts = {Slot(f["competitor"], f["attribute"]): f for f in (job["delivery"] or {}).get("facts", [])}
        checks = {v["slot"]: v for v in (job["verdict"] or {}).get("facts", [])}
        rows = []
        for i, slot in enumerate(spec.slots):
            f = facts.get(slot)
            v = checks.get(i)
            rows.append({"competitor": slot.competitor, "attribute": slot.attribute,
                         "value": f["value"] if f else None, "doc_id": f["doc_id"] if f else None,
                         "quote": f["quote"] if f else None, "via_job": f["via_job"] if f else None,
                         "check": None if v is None else ("pass" if v["passed"] else f"fail: {v['reason']}")})
        status = job["status"]
        if status == Status.PASSED:
            recommendation = "accept"
        elif status in (Status.FAILED, Status.TIMEOUT):
            recommendation = "reject_and_rematch"
        else:
            recommendation = "wait"
        subs = self.store.query("SELECT job_id, worker_id, status FROM jobs WHERE parent_job_id = ?", (job_id,))
        return {
            "job_id": job_id, "status": status, "difficulty_band": job["band"], "worker": worker["name"],
            "locked_forecast": job["prediction"], "facts": rows, "cost": job["cost"],
            "elapsed_s": job["elapsed"], "within_budget": (job["verdict"] or {}).get("within_budget"),
            "recommendation": recommendation, "semantic_check": (job["verdict"] or {}).get("semantic_check"),
            "failure_traced_to": [self.store.get("agents", "agent_id", a)["name"] for a in job["attributed"] or []],
            "subcontracts": [{"job_id": s["job_id"], "worker": self.store.get("agents", "agent_id", s["worker_id"])["name"],
                              "status": s["status"]} for s in subs],
            "notary_entries": len(self.notary.entries(job_id)),
        }

    def verify_ledger(self) -> dict:
        ok, problems = self.notary.verify_chain()
        return {"ok": ok, "entries": self.store.count("notary_log"), "head": self.notary.head(),
                "problems": problems}

    # --- corpus access for workers -------------------------------------------------

    def describe_corpus(self) -> dict:
        return self.corpus.describe()

    def read_document(self, doc_id: str) -> dict:
        doc = self.corpus.docs.get(doc_id)
        if doc is None:
            raise ReferralError(f"no document {doc_id!r}")
        return {"doc_id": doc.doc_id, "subject": doc.subject, "date": doc.date, "text": doc.text}
