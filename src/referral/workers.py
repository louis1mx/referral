"""Instrumented simulated workers.

Each persona has a per-fact accuracy for each difficulty band. When it gets a fact
wrong it produces a real wrong delivery (a stale citation, a look-alike firm, an
invented quote, a value missing from its quote, or nothing), and the Checker has to
catch it. The simulator keeps ground truth on the side, only for evaluation.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field

from .corpus import AS_OF, DYNAMIC_ATTRS, Corpus
from .models import BAND_TIME, Band, Fact, LiveClock, ReferralError, Slot, TaskSpec
from .notary import canonical


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    owner: str
    model: str
    accuracy: dict
    price: float
    seconds: float              # typical time for a medium task
    forecast_shift: float = 0.0
    forecast_floor: float = 0.0
    revises_forecast: bool = False
    subcontract_to: str | None = None


E, M, H = Band.EASY, Band.MEDIUM, Band.HARD

PERSONAS = {
    "reliable": Persona("reliable", "rae-reliable", "owner-rae", "atlas-large-2",
                        {E: 0.99, M: 0.97, H: 0.93}, price=1.6, seconds=80),
    "weak": Persona("weak", "hal-honest-weak", "owner-hal", "atlas-mini-2",
                    {E: 0.97, M: 0.88, H: 0.75}, price=0.6, seconds=50),
    "overconfident": Persona("overconfident", "olu-overconfident", "owner-olu", "corvid-1",
                             {E: 0.98, M: 0.90, H: 0.78}, price=0.9, seconds=60,
                             forecast_shift=0.30, forecast_floor=0.90),
    "newcomer": Persona("newcomer", "nia-newcomer", "owner-nia", "nimbus-3",
                        {E: 0.98, M: 0.95, H: 0.90}, price=1.0, seconds=75),
    "padder": Persona("padder", "pat-padder", "owner-pat", "atlas-mini-2",
                      {E: 0.96, M: 0.80, H: 0.60}, price=0.7, seconds=45),
}
CORE = ("reliable", "weak", "overconfident", "newcomer")


@dataclass
class Truth:
    true_success: bool
    culprits: list[str] = field(default_factory=list)   # persona keys that introduced errors
    origins: dict[int, str] = field(default_factory=dict)  # slot index -> persona key that wrote it


class SimWorker:
    """Callable handler: `service.attach_worker(agent_id, worker)`."""

    def __init__(self, persona: Persona, corpus: Corpus, seed: int):
        self.persona = persona
        self.corpus = corpus
        self.seed = seed
        self.agent_id: str = ""
        self.key: str = ""
        self.subcontractor: SimWorker | None = None
        self.subcontract = False    # hand the last two slots of each job to the subcontractor
        self.revise_next = False    # try to change its forecast after dispatch, once
        self.truth: dict[str, Truth] = {}
        self.rejections: list[str] = []
        self._attempts: dict[str, int] = {}
        self.declared_success: float | None = None   # its own claim, stated at registration

    def register(self, service) -> None:
        p = self.persona
        creds = service.register_agent(p.name, "worker", p.owner, p.model, price=p.price,
                                       typical_seconds=p.seconds, declared_success=self.declared_success)
        self.agent_id, self.key = creds["agent_id"], creds["key"]
        service.attach_worker(self.agent_id, self)

    def _rng(self, spec: dict) -> random.Random:
        # Same worker + same task (+ same attempt number) -> same outcome, in any world.
        fp = canonical(spec)
        n = self._attempts.get(fp, 0)
        self._attempts[fp] = n + 1
        return random.Random(f"{self.seed}|{self.persona.key}|{fp}|{n}")

    def failure_modes(self, slot: Slot, band: Band) -> list[str]:
        modes = ["invented_quote", "unsupported", "missing"]
        if self.corpus.stale_doc(slot):
            modes.append("stale")
        if band == Band.HARD and slot.competitor in self.corpus.lookalikes and slot.attribute in DYNAMIC_ATTRS:
            modes.append("lookalike")
        return modes

    def pass_probability(self, spec: TaskSpec, band: Band) -> float:
        """Chance that every fact passes the Checker. A stale citation slips through
        unless its slot happens to be the hidden canary (one slot in n)."""
        a = self.persona.accuracy[band]
        p = 1.0
        for slot in spec.slots:
            modes = self.failure_modes(slot, band)
            undetected = modes.count("stale") / len(modes) * (1 - 1 / len(spec.slots))
            p *= a + (1 - a) * undetected
        return p

    def forecast(self, spec: TaskSpec, band: Band, rng: random.Random) -> float:
        f = self.pass_probability(spec, band) + rng.gauss(0, 0.04) + self.persona.forecast_shift
        f = max(f, self.persona.forecast_floor)
        return round(min(0.98, max(0.02, f)), 3)

    def make_fact(self, slot: Slot, band: Band, rng: random.Random) -> tuple[Fact | None, bool]:
        """Return (fact, correct). Wrong facts come from the realistic failure modes."""
        doc = self.corpus.source_doc(slot)
        value = self.corpus.truth[slot]
        good = Fact(slot.competitor, slot.attribute, value, doc.doc_id, self.corpus.sentence_with(doc, value))
        if rng.random() < self.persona.accuracy[band]:
            return good, True
        mode = rng.choice(self.failure_modes(slot, band))
        if mode == "stale":
            old = self.corpus.stale_doc(slot)
            v = self.corpus.stale[slot]
            return Fact(slot.competitor, slot.attribute, v, old.doc_id, self.corpus.sentence_with(old, v)), False
        if mode == "lookalike":
            twin = self.corpus.docs[self.corpus.lookalikes[slot.competitor]]
            sentence = twin.text.split(". ")[-1] if slot.attribute == "headcount" else twin.text.split(". ")[0]
            v = [w for w in sentence.replace(".", "").split() if w[0] in "$0123456789"][0]
            return Fact(slot.competitor, slot.attribute, v, twin.doc_id, sentence), False
        if mode == "invented_quote":
            return Fact(slot.competitor, slot.attribute, value, doc.doc_id,
                        f"{slot.competitor} reported {value} in its latest filing."), False
        if mode == "unsupported":
            return Fact(slot.competitor, slot.attribute, value + "0", doc.doc_id, good.quote), False
        return None, False

    def __call__(self, service, assignment: dict) -> None:
        p = self.persona
        spec = TaskSpec.from_dict(assignment["task"])
        band = Band(assignment["difficulty_band"])
        job_id = assignment["job_id"]
        rng = self._rng(assignment["task"])

        work_s = p.seconds * BAND_TIME[band] * rng.lognormvariate(0, 0.15)
        cost = round(p.price * (1 + abs(rng.gauss(0, 0.04))), 3)
        service.submit_prediction(self.agent_id, self.key, job_id, self.forecast(spec, band, rng),
                                  p.price, round(p.seconds * BAND_TIME[band], 1))
        if self.revise_next:
            self.revise_next = False
            try:
                service.submit_prediction(self.agent_id, self.key, job_id, 0.2, p.price, work_s)
            except ReferralError as e:
                self.rejections.append(str(e))

        facts: list[Fact] = []
        culprits: list[str] = []
        origins: dict[int, str] = {}
        sub_slots: set[int] = set()
        sub_s = 0.0
        if self.subcontractor and self.subcontract and len(spec.slots) > 2:
            sub_slots = {len(spec.slots) - 2, len(spec.slots) - 1}
            before = service.clock.now()
            sub = service.subcontract(self.agent_id, self.key, job_id, self.subcontractor.agent_id,
                                      sorted(sub_slots))
            sub_s = service.clock.now() - before
            record = service.get_record(self.agent_id, self.key, sub["job_id"])
            sub_truth = self.subcontractor.truth.get(sub["job_id"])
            for row in record["facts"]:
                if row["value"] is None:
                    continue
                facts.append(Fact(row["competitor"], row["attribute"], row["value"], row["doc_id"],
                                  row["quote"], via_job=sub["job_id"]))
            if sub_truth and not sub_truth.true_success:
                culprits.append(self.subcontractor.persona.key)
            origins.update({i: self.subcontractor.persona.key for i in sub_slots})

        for i, slot in enumerate(spec.slots):
            if i in sub_slots:
                continue
            fact, correct = self.make_fact(slot, band, rng)
            origins[i] = p.key
            if fact:
                facts.append(fact)
            if not correct and p.key not in culprits:
                culprits.append(p.key)

        service.clock.advance(max(0.0, work_s - sub_s))
        self.truth[job_id] = Truth(true_success=not culprits, culprits=culprits, origins=origins)
        service.submit_delivery(self.agent_id, self.key, job_id, [asdict(f) for f in facts], cost)


def make_workers(corpus: Corpus, seed: int, keys=CORE + ("padder",)) -> dict[str, SimWorker]:
    return {k: SimWorker(PERSONAS[k], corpus, seed) for k in keys}


# --- live LLM workers ----------------------------------------------------------------

# Anthropic list prices, USD per million tokens (input, output), as of 2026-10.
LLM_PRICING = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
# key -> (agent name, model, fee per job charged to buyers, typical seconds). Fees are illustrative.
LLM_WORKERS = {
    "opus": ("claude-opus-worker", "claude-opus-5-5", 1.6, 60),
    "sonnet": ("claude-sonnet-worker", "claude-sonnet-5-5", 0.9, 40),
    "haiku": ("claude-haiku-worker", "claude-haiku-5-5", 0.3, 20),
}

FORECAST_SCHEMA = {
    "type": "object",
    "properties": {"p_success": {"type": "number"}, "finish_seconds": {"type": "number"}},
    "required": ["p_success", "finish_seconds"],
    "additionalProperties": False,
}
FACT_FIELDS = ("competitor", "attribute", "value", "doc_id", "quote")
DELIVERY_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in FACT_FIELDS},
        "required": list(FACT_FIELDS),
        "additionalProperties": False,
    }}},
    "required": ["facts"],
    "additionalProperties": False,
}

WORKER_SYSTEM = """You are a research worker agent hired through Referral, a service that \
verifies every delivery. You extract facts about companies from a fixed corpus of dated \
documents. The corpus date is {as_of}. Use only the documents below.

<documents>
{documents}
</documents>"""

FORECAST_PROMPT = """Task from {buyer}: {n} facts about competitors of {company}, difficulty \
band "{band}" (assigned by Referral).

Slots:
{slots}

Acceptance criteria: {acceptance}
Budget ${budget:.2f}, deadline {deadline:.0f} seconds.

Before you start, lock a forecast. Estimate the probability that ALL {n} facts will pass \
the checks, and how many seconds you will need. The forecast cannot be changed later and \
is scored against the checked result with a Brier score, so an honest estimate scores best."""

DELIVERY_PROMPT = """Now do the task.

Slots:
{slots}

Acceptance criteria: {acceptance}

Return exactly one fact per slot. For each fact give the competitor and attribute exactly \
as written in the slot, the value, the doc_id of the document you used, and a quote copied \
character for character from that document that contains the value."""


class LLMOutputError(Exception):
    """The model refused, ran out of tokens, or returned unusable output."""


def _api_errors() -> tuple[type[BaseException], ...]:
    try:
        import anthropic
    except ImportError:
        return (LLMOutputError,)
    return (LLMOutputError, anthropic.APIError)


@dataclass
class LLMCall:
    job_id: str
    stage: str
    model: str
    seconds: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    usd: float


class LLMWorker:
    """A worker backed by a real Claude model, using the same service API as any agent.

    It reads the permitted documents, locks a forecast with one request, then produces
    the facts with a second request. Only the delivered facts are checked.
    """

    def __init__(self, key: str, corpus: Corpus, client=None, effort: str = "medium",
                 owner: str | None = None, name: str | None = None,
                 declared_success: float | None = None):
        self.key_name = key
        self.name, self.model, self.price, self.typical_seconds = LLM_WORKERS[key]
        self.name = name or self.name   # a second worker on the same model needs its own name
        self.declared_success = declared_success
        self.owner = owner or f"owner-{self.name}"
        self.corpus = corpus
        self.effort = effort
        self._client = client
        self.agent_id = ""
        self.key = ""
        self.calls: list[LLMCall] = []
        self.errors: dict[str, str] = {}

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def register(self, service) -> None:
        creds = service.register_agent(self.name, "worker", self.owner, self.model, price=self.price,
                                       typical_seconds=self.typical_seconds,
                                       declared_success=self.declared_success)
        self.agent_id, self.key = creds["agent_id"], creds["key"]
        service.attach_worker(self.agent_id, self)

    def _system(self, service, spec: TaskSpec) -> str:
        ids = spec.corpus_ids or list(self.corpus.docs)
        docs = [service.read_document(i) for i in ids]
        body = "\n\n".join(f'<document doc_id="{d["doc_id"]}" subject="{d["subject"]}" date="{d["date"]}">\n'
                           f'{d["text"]}\n</document>' for d in docs)
        return WORKER_SYSTEM.format(as_of=AS_OF, documents=body)

    def _ask(self, job_id: str, stage: str, system: str, prompt: str, schema: dict) -> dict:
        t0 = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        seconds = time.perf_counter() - t0
        u = response.usage
        read = getattr(u, "cache_read_input_tokens", 0) or 0
        write = getattr(u, "cache_creation_input_tokens", 0) or 0
        price_in, price_out = LLM_PRICING.get(self.model, (0.0, 0.0))
        usd = (u.input_tokens + 1.25 * write + 0.1 * read) * price_in / 1e6 + u.output_tokens * price_out / 1e6
        self.calls.append(LLMCall(job_id, stage, self.model, seconds, u.input_tokens, u.output_tokens,
                                  read, write, usd))
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LLMOutputError(f"{stage}: stop_reason={response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMOutputError(f"{stage}: no text block in the response")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"{stage}: invalid JSON ({e})") from e

    def __call__(self, service, assignment: dict) -> None:
        job_id = assignment["job_id"]
        spec = TaskSpec.from_dict(assignment["task"])
        slots = "\n".join(f"{i + 1}. {s.competitor} | {s.attribute}" for i, s in enumerate(spec.slots))
        system = self._system(service, spec)
        started = len(self.calls)
        locked = False
        try:
            f = self._ask(job_id, "forecast", system, FORECAST_PROMPT.format(
                buyer=assignment["buyer"], n=len(spec.slots), company=spec.company,
                band=assignment["difficulty_band"], slots=slots, acceptance=spec.acceptance,
                budget=spec.budget, deadline=spec.deadline_s), FORECAST_SCHEMA)
            p = min(1.0, max(0.0, float(f["p_success"])))
            service.submit_prediction(self.agent_id, self.key, job_id, p, self.price,
                                      max(1.0, float(f["finish_seconds"])))
            locked = True
            d = self._ask(job_id, "delivery", system,
                          DELIVERY_PROMPT.format(slots=slots, acceptance=spec.acceptance), DELIVERY_SCHEMA)
        except _api_errors() as e:
            self.errors[job_id] = f"{'after' if locked else 'before'} forecast: {e}"
            return
        if not isinstance(service.clock, LiveClock):
            service.clock.advance(sum(c.seconds for c in self.calls[started:]))
        facts = [{k: str(fact.get(k, "")) for k in FACT_FIELDS} for fact in d.get("facts", [])]
        # Report what the job really cost in API calls; the buyer is billed the contract price.
        spent = round(sum(c.usd for c in self.calls[started:]), 6)
        service.submit_delivery(self.agent_id, self.key, job_id, facts, spent)
