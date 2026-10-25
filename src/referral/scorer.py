"""The Scorer: per-agent profiles, tiers and descriptive insights.

v1 scores three of the six signals in the proposal: calibration (Brier score and bias),
difficulty-weighted quality, and chain attribution. Stability/trend, cost and time
overruns are computed and logged but do not affect the tier yet.

Nothing in this module is returned to clients as a number. `insights` turns a profile
into short sentences, and the Matcher only exposes tiers and evidence labels.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .models import BAND_WEIGHT, BANDS, Band, Tier

# Illustrative public-benchmark priors for the fictional models in the simulation.
# Real models (e.g. live LLM workers) are not listed on purpose: they get
# DEFAULT_BENCHMARK, a placeholder, until we source a real benchmark score.
MODEL_BENCHMARKS = {
    "atlas-large-2": 0.92,
    "atlas-mini-2": 0.78,
    "corvid-1": 0.85,
    "nimbus-3": 0.88,
    "nimbus-3.5": 0.91,
}
DEFAULT_BENCHMARK = 0.75   # placeholder prior, not a measured score
BAND_PRIOR_FACTOR = {Band.EASY: 1.0, Band.MEDIUM: 0.85, Band.HARD: 0.65}
PRIOR_STRENGTH = 2.0

MIN_JOBS_VERIFIED = 4
MIN_JOBS_TRUSTED = 15
MAX_BRIER_VERIFIED = 0.25
MAX_BRIER_TRUSTED = 0.18
MIN_QUALITY_VERIFIED = 0.40
MIN_QUALITY_TRUSTED = 0.65
MAX_OWN_FAULT_TRUSTED = 0.25

# Forecasts in a band count as evidence only when that band's own bias is small.
# Calibration is judged per band: a worker that under-reports easy jobs and
# over-reports hard ones can average out to zero bias overall.
MIN_FORECASTS_FOR_TRUST = 3
MAX_BIAS_FOR_TRUST = 0.25
OVERSTATE_NOTE = 0.15
# The bias used to correct a band's forecasts is that band's bias shrunk toward the
# worker's overall bias, as if the overall bias were worth this many jobs.
BIAS_SHRINK_JOBS = 4.0


@dataclass
class BandStats:
    n: int = 0
    successes: int = 0
    pairs: list[tuple[float, int]] = field(default_factory=list)   # (forecast, outcome)
    elapsed: list[float] = field(default_factory=list)

    @property
    def forecasts(self) -> list[float]:
        return [f for f, _ in self.pairs]

    @property
    def bias(self) -> float | None:
        return statistics.mean(f - o for f, o in self.pairs) if self.pairs else None

    @property
    def brier(self) -> float | None:
        return statistics.mean((f - o) ** 2 for f, o in self.pairs) if self.pairs else None


@dataclass
class Profile:
    agent_id: str
    name: str
    model: str
    benchmark: float
    bands: dict[Band, BandStats]
    n_counted: int
    n_self_dealing: int
    raw_n: int
    raw_successes: int
    brier: float | None
    bias: float | None
    weighted_quality: float | None
    own_fault_failures: int
    traced_to_subcontractors: int
    timeouts: int
    cost_overruns: int
    time_overruns: int
    trend: float | None
    volatility: float | None
    previous_models: list[str]
    tier: Tier = Tier.TRIAL


def benchmark_for(model: str) -> float:
    return MODEL_BENCHMARKS.get(model, DEFAULT_BENCHMARK)


def build_profile(agent: dict, jobs: list[dict], previous_models: list[str] | None = None) -> Profile:
    """Profile from settled jobs under the agent's current model, oldest first."""
    bands = {b: BandStats() for b in BANDS}
    counted = [j for j in jobs if not j["self_dealing"]]
    sq_errors, errors, outcomes = [], [], []
    own_fault = traced = timeouts = cost_over = time_over = 0
    for j in counted:
        band = Band(j["band"])
        stats = bands[band]
        stats.n += 1
        stats.successes += j["outcome"]
        if j["elapsed"] is not None:
            stats.elapsed.append(j["elapsed"])
        outcomes.append(j["outcome"])
        pred = j["prediction"]
        if pred is not None:
            stats.pairs.append((pred["p_success"], j["outcome"]))
            sq_errors.append((pred["p_success"] - j["outcome"]) ** 2)
            errors.append(pred["p_success"] - j["outcome"])
            if j["cost"] is not None and j["cost"] > pred["cost"] * 1.05:
                cost_over += 1
            if j["elapsed"] is not None and j["elapsed"] > pred["finish_s"] * 1.10:
                time_over += 1
        if j["status"] == "timeout":
            timeouts += 1
        if not j["outcome"]:
            culprits = j["attributed"] or [agent["agent_id"]]
            if agent["agent_id"] in culprits:
                own_fault += 1
            else:
                traced += 1

    weight = sum(BAND_WEIGHT[b] * bands[b].n for b in BANDS)
    quality = (sum(BAND_WEIGHT[b] * bands[b].successes for b in BANDS) / weight) if weight else None
    trend = volatility = None
    if len(outcomes) >= 6:
        half = len(outcomes) // 2
        trend = statistics.mean(outcomes[half:]) - statistics.mean(outcomes[:half])
        windows = [statistics.mean(outcomes[i:i + 3]) for i in range(0, len(outcomes) - 2, 3)]
        volatility = statistics.pstdev(windows) if len(windows) > 1 else 0.0

    profile = Profile(
        agent_id=agent["agent_id"], name=agent["name"], model=agent["model"],
        benchmark=benchmark_for(agent["model"]), bands=bands,
        n_counted=len(counted), n_self_dealing=len(jobs) - len(counted),
        raw_n=len(jobs), raw_successes=sum(j["outcome"] for j in jobs),
        brier=statistics.mean(sq_errors) if sq_errors else None,
        bias=statistics.mean(errors) if errors else None,
        weighted_quality=quality, own_fault_failures=own_fault,
        traced_to_subcontractors=traced, timeouts=timeouts,
        cost_overruns=cost_over, time_overruns=time_over,
        trend=trend, volatility=volatility, previous_models=previous_models or [],
    )
    profile.tier = tier_for(profile)
    return profile


def tier_for(p: Profile) -> Tier:
    if p.n_counted < MIN_JOBS_VERIFIED or p.brier is None or p.weighted_quality is None:
        return Tier.TRIAL
    own_fault_rate = p.own_fault_failures / p.n_counted
    if (p.n_counted >= MIN_JOBS_TRUSTED and p.brier <= MAX_BRIER_TRUSTED
            and p.weighted_quality >= MIN_QUALITY_TRUSTED and own_fault_rate <= MAX_OWN_FAULT_TRUSTED):
        return Tier.TRUSTED
    if p.brier <= MAX_BRIER_VERIFIED and p.weighted_quality >= MIN_QUALITY_VERIFIED:
        return Tier.VERIFIED
    return Tier.TRIAL


def forecasts_trusted(p: Profile, band: Band) -> bool:
    stats = p.bands[band]
    return (len(stats.pairs) >= MIN_FORECASTS_FOR_TRUST and stats.bias is not None
            and abs(stats.bias) < MAX_BIAS_FOR_TRUST)


def band_estimate(p: Profile, band: Band, use_forecasts: bool) -> float:
    """Posterior success probability for one difficulty band.

    Outcomes update a Beta prior built from the model's public benchmark. With
    `use_forecasts`, a worker whose forecasts in this band have shown little bias also
    contributes bias-corrected forecasts as fractional evidence.

    Trust and evidence weight come from this band's own bias, so inflating one band's
    forecasts while deflating another's buys nothing: the inflated band is either not
    trusted or weighted close to zero. The correction itself uses the band's bias shrunk
    toward the overall bias. Correcting by the raw band bias alone would make the
    corrected forecasts average exactly to the band's outcomes, and adding them would
    count the same outcomes twice.
    """
    prior = min(0.95, p.benchmark * BAND_PRIOR_FACTOR[band])
    a = prior * PRIOR_STRENGTH
    b = (1 - prior) * PRIOR_STRENGTH
    stats = p.bands[band]
    a += stats.successes
    b += stats.n - stats.successes
    if use_forecasts and forecasts_trusted(p, band):
        weight = 1.0 - abs(stats.bias) / MAX_BIAS_FOR_TRUST
        n = len(stats.pairs)
        correction = (n * stats.bias + BIAS_SHRINK_JOBS * p.bias) / (n + BIAS_SHRINK_JOBS)
        for f in stats.forecasts:
            c = min(0.99, max(0.01, f - correction))
            a += weight * c
            b += weight * (1 - c)
    return a / (a + b)


def evidence_label(n: int) -> str:
    if n == 0:
        return "none"
    if n <= 2:
        return "thin"
    if n <= 5:
        return "moderate"
    return "strong"


def insights(p: Profile, band: Band | None = None) -> list[str]:
    """Short descriptive guidance. Deliberately no scores, rates or formulas."""
    notes: list[str] = []
    if p.previous_models:
        notes.append("declared a model change; its record restarted at trial")
    for b in BANDS:
        stats = p.bands[b]
        if stats.n == 0:
            notes.append(f"little evidence on {b} tasks")
            continue
        est = band_estimate(p, b, use_forecasts=False)
        if stats.n < 2:
            notes.append(f"only one checked {b} job so far")
        elif est >= 0.75:
            notes.append(f"reliable on {b} source-bound extraction")
        elif est >= 0.5:
            notes.append(f"mixed results on {b} tasks")
        else:
            notes.append(f"usually fails {b} tasks")
    flagged = False
    for b in BANDS:
        stats = p.bands[b]
        if len(stats.pairs) < MIN_FORECASTS_FOR_TRUST:
            continue
        if stats.bias > OVERSTATE_NOTE:
            notes.append(f"tends to overstate its chances on {b} tasks; discount those forecasts")
            flagged = True
        elif stats.bias < -OVERSTATE_NOTE:
            notes.append(f"tends to understate its chances on {b} tasks")
            flagged = True
    if not flagged and p.bias is not None and p.n_counted >= MIN_JOBS_VERIFIED and abs(p.bias) < 0.08:
        notes.append("its forecasts have tracked checked results closely")
    if p.timeouts >= 2:
        notes.append("has missed deadlines on longer tasks")
    if p.traced_to_subcontractors:
        notes.append("some failures on its jobs traced to its subcontractors")
    if p.n_self_dealing:
        notes.append("self-commissioned jobs are on file but do not count")
    if band is not None:
        # Put the line about the requested band first.
        notes.sort(key=lambda s: str(band) not in s)
    return notes
