"""Simulation worlds and the narrated demo used for demo day."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

from .corpus import Corpus
from .models import BANDS, Band, SimClock, Status
from .notary import Notary, Store
from .scorer import MODEL_BENCHMARKS
from .service import ReferralService
from .workers import CORE, SimWorker, make_workers

BUYER = ("research-buyer", "owner-research-team", "buyer-llm")


@dataclass
class World:
    service: ReferralService
    buyer_id: str
    buyer_key: str
    workers: dict[str, SimWorker]
    seed: int

    def by_agent(self, agent_id: str) -> SimWorker:
        return next(w for w in self.workers.values() if w.agent_id == agent_id)


def build_world(seed: int = 7, clock: SimClock | None = None, keys=CORE + ("padder",),
                db_path: str = ":memory:", live: bool = False) -> World:
    """`live=True` keeps simulated workers reproducible but draws canaries from `secrets`."""
    corpus = Corpus.default()
    service = ReferralService(db_path, clock or SimClock(), corpus, None if live else seed)
    service.model_priors = dict(MODEL_BENCHMARKS)
    name, owner, model = BUYER
    buyer = service.register_agent(name, "buyer", owner, model)
    workers = make_workers(corpus, seed, keys)
    for w in workers.values():
        w.register(service)
    if "reliable" in workers and "weak" in workers:
        workers["reliable"].subcontractor = workers["weak"]
    return World(service, buyer["agent_id"], buyer["key"], workers, seed)


def run_trials(world: World, per_band: int = 4) -> None:
    """Equal exposure: every worker gets the same trial tasks in every band."""
    rng = random.Random(f"trials|{world.seed}")
    tasks = [world.service.corpus.make_task(rng, band) for band in BANDS for _ in range(per_band)]
    for spec in tasks:
        for w in world.workers.values():
            world.service.direct_hire(world.buyer_id, world.buyer_key, w.agent_id, spec.to_dict())


def pad_record(world: World, n: int = 20) -> str:
    """Misuse #2: the padder commissions easy jobs from itself through a shell buyer."""
    padder = world.workers["padder"]
    shell = world.service.register_agent("pat-shell-buyer", "buyer", padder.persona.owner, "shell")
    rng = random.Random(f"padding|{world.seed}")
    for _ in range(n):
        spec = world.service.corpus.make_task(rng, Band.EASY)
        world.service.direct_hire(shell["agent_id"], shell["key"], padder.agent_id, spec.to_dict())
    return shell["agent_id"]


# --- narrated demo -------------------------------------------------------------------

def _h(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _show(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _bands_line(profile) -> str:
    return "  ".join(f"{b}: {profile.bands[b].successes}/{profile.bands[b].n}" for b in BANDS)


def run_demo(seed: int = 4) -> World:
    world = build_world(seed)
    s = world.service
    buyer, key = world.buyer_id, world.buyer_key

    _h("1. Setup: one buyer, five workers, one dated corpus")
    c = s.describe_corpus()
    print(f"Corpus: {len(c['documents'])} documents about {len(c['competitors'])} competitors of "
          f"{c['company']}, as of {c['as_of']}.")
    for w in world.workers.values():
        p = w.persona
        print(f"  {p.name:<20} model={p.model:<14} price=${p.price:.2f}  ({p.key})")

    _h("2. Trial phase: equal trial jobs for every worker (4 per difficulty band)")
    run_trials(world)
    print("Operator view (raw numbers stay inside Referral):")
    for w in world.workers.values():
        p = s.profile(w.agent_id)
        print(f"  {w.persona.name:<20} passed {_bands_line(p)}   tier={p.tier}")
    print("\nWhat any agent sees from get_insight (descriptive only):")
    for w in world.workers.values():
        ins = s.get_insight(w.agent_id)
        print(f"  {ins['name']:<20} [{ins['tier']}] " + "; ".join(ins["guidance"][:4]))

    _h("3. One hire through Referral (a hard task)")
    spec = s.corpus.make_task(random.Random(f"hero|{seed}"), Band.HARD)
    print("Buyer -> request_match: five competitor facts, every fact needs a cited passage, "
          f"${spec.budget:.0f} budget, {spec.deadline_s:.0f}s deadline")
    match = s.request_match(buyer, key, spec.to_dict())
    _show(match)
    tried: list[str] = []
    for attempt in range(2):
        if attempt:
            match = s.request_match(buyer, key, spec.to_dict(), exclude=tuple(tried))
            print(f"\nBuyer -> request_match again, excluding {rec['worker']}: "
                  f"{match['action']} {match['candidate']['name'] if match['candidate'] else ''}")
        if not match["candidate"]:
            print("No eligible worker, so the buyer should split the task or change its terms.")
            break
        tried.append(match["candidate"]["agent_id"])
        job = s.hire(buyer, key, match["match_id"])
        print(f"\nBuyer -> hire -> {job['job_id']} dispatched to {job['worker']}; the worker locked "
              "its forecast, delivered, and the Checker ran.")
        rec = s.get_record(buyer, key, job["job_id"])
        print("Buyer -> get_record:")
        for f in rec["facts"]:
            print(f"  {f['competitor']:<20} {f['attribute']:<17} {str(f['value']):<14} {f['check']}")
        print(f"  locked forecast: {rec['locked_forecast']['p_success']:.0%} success, "
              f"${rec['locked_forecast']['cost']:.2f}, {rec['locked_forecast']['finish_s']:.0f}s")
        print(f"  status={rec['status']}  recommendation={rec['recommendation']}")
        if rec["recommendation"] == "accept":
            break

    _h("4. Misuse #1: the overconfident worker tries to revise its forecast after dispatch")
    olu = world.workers["overconfident"]
    olu.revise_next = True
    hard = s.corpus.make_task(random.Random(f"misuse1|{seed}"), Band.HARD)
    j = s.direct_hire(buyer, key, olu.agent_id, hard.to_dict())
    print(f"Notary response to the second submit_prediction: \"{olu.rejections[-1]}\"")
    kinds = [e["kind"] for e in s.notary.entries(j["job_id"])]
    print(f"Log for {j['job_id']}: {' -> '.join(kinds)}")
    m = s.request_match(buyer, key, s.corpus.make_task(random.Random(f"misuse1b|{seed}"), Band.HARD).to_dict())
    picked = m["candidate"]["name"] if m["candidate"] else "nobody"
    ins = s.get_insight(olu.agent_id)
    about_forecasts = [g for g in ins["guidance"] if "chances" in g or "forecasts" in g]
    print(f"Next hard task routes to: {picked} ({m['action']}); {olu.persona.name} is "
          f"[{ins['tier']}]: {'; '.join(about_forecasts) or 'no forecast note yet'}")

    _h("5. Misuse #2: a worker pads its record with self-commissioned easy jobs")
    pat = world.workers["padder"]
    before = s.profile(pat.agent_id)
    pad_record(world, 20)
    after = s.profile(pat.agent_id)
    print(f"Raw success rate on file: {before.raw_successes}/{before.raw_n} -> "
          f"{after.raw_successes}/{after.raw_n}  (what a public rating would show)")
    print(f"Counted jobs: {before.n_counted} -> {after.n_counted}; tier: {before.tier} -> {after.tier}")
    print(f"Guidance: {'; '.join(s.get_insight(pat.agent_id)['guidance'])}")

    _h("6. Two-hop chain: the reliable worker subcontracts a lookup to the weak one")
    rae = world.workers["reliable"]
    rae.subcontract = True
    rng = random.Random(f"chain|{seed}")
    shown = None
    for _ in range(40):
        t = s.corpus.make_task(rng, Band.HARD)
        j = s.direct_hire(buyer, key, rae.agent_id, t.to_dict())
        r = s.get_record(buyer, key, j["job_id"])
        if r["status"] == Status.FAILED and r["failure_traced_to"] != [rae.persona.name]:
            shown = r
            break
    rae.subcontract = False
    if shown:
        print(f"{shown['job_id']} failed. Subcontracts: {shown['subcontracts']}")
        for f in shown["facts"]:
            via = f" (via {f['via_job']})" if f["via_job"] else ""
            print(f"  {f['competitor']:<20} {f['attribute']:<17} {f['check']}{via}")
        print(f"Failure traced to: {shown['failure_traced_to']}")
        print(f"{rae.persona.name} guidance now includes: "
              f"{[g for g in s.get_insight(rae.agent_id)['guidance'] if 'subcontract' in g]}")
    else:
        print("No subcontractor-caused failure in 40 chained jobs with this seed.")

    _h("7. A declared model change opens a new trial profile")
    nia = world.workers["newcomer"]
    print(f"Before: {s.get_insight(nia.agent_id)['tier']}")
    s.declare_model_change(nia.agent_id, nia.key, "nimbus-3.5")
    ins = s.get_insight(nia.agent_id)
    print(f"After declaring nimbus-3.5: {ins['tier']} — {ins['guidance'][0]}")

    _h("8. Notary integrity")
    v = s.verify_ledger()
    print(f"Ledger: {v['entries']} entries, chain ok={v['ok']}, head={v['head'][:16]}…")
    copy = Store()
    s.store.db.backup(copy.db)
    copy.db.execute("DROP TRIGGER notary_no_update")
    copy.db.execute("UPDATE notary_log SET payload = replace(payload, '\"status\":\"failed\"', "
                    "'\"status\":\"passed\"') WHERE kind = 'verdict'")
    ok, problems = Notary(copy, s._key_of).verify_chain()
    print(f"After flipping failed verdicts to passed in a copy of the DB: ok={ok}, "
          f"{len(problems)} problems, first: {problems[0] if problems else '-'}")
    print("\nNext: `referral eval` compares picking strategies on identical histories.")
    return world
