"""Does the semantic layer catch what the rule layer misses? A fixed suite, scored on ground truth.

For every competitor, ten facts that all pass the rule layer (real quote, right firm,
value inside the quote):

- 5 correct: the three static attributes and the two current dynamic ones;
- 2 stale: last round and headcount from the 2024 profile, superseded by the 2026 update;
- 3 wrong attribute: the headcount given as the funding round, the funding round given as
  the headcount, and the founding year given as the headquarters city.

The rule layer runs without the hidden check, which covers only one slot per job, so this
measures what public checking alone lets through. The judge then sees the same facts in
shuffled order, one call per competitor, and never sees the labels or the ground truth.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from .checker import check_fact
from .claude_agents import MODELS
from .corpus import Corpus, slug
from .models import Fact, Slot
from .semantic import Claim, ClaudeJudge, JudgeError


def build_cases(corpus: Corpus) -> list[dict]:
    cases = []

    def add(kind: str, slot: Slot, value: str, doc_id: str) -> None:
        quote = corpus.sentence_with(corpus.docs[doc_id], value)
        cases.append({"kind": kind, "slot": slot, "fact": Fact(slot.competitor, slot.attribute, value, doc_id, quote),
                      "correct": kind == "correct"})

    for c in corpus.competitors:
        old, new = f"{slug(c)}-profile-2024", f"{slug(c)}-update-2026"
        for attr in ("hq_city", "founded_year", "flagship_product", "latest_funding", "headcount"):
            slot = Slot(c, attr)
            add("correct", slot, corpus.truth[slot], corpus.source_doc(slot).doc_id)
        for attr in ("latest_funding", "headcount"):
            add("stale", Slot(c, attr), corpus.stale[Slot(c, attr)], old)
        add("wrong_attribute", Slot(c, "latest_funding"), corpus.truth[Slot(c, "headcount")], new)
        add("wrong_attribute", Slot(c, "headcount"), corpus.truth[Slot(c, "latest_funding")], new)
        add("wrong_attribute", Slot(c, "hq_city"), corpus.truth[Slot(c, "founded_year")], old)
    return cases


def run(model: str, out: str, seed: int = 0) -> int:
    corpus = Corpus.default()
    cases = build_cases(corpus)
    for case in cases:
        case["rules_pass"] = check_fact(case["fact"], case["slot"], 0, corpus, set(corpus.docs), False).passed
    judge = ClaudeJudge(MODELS.get(model, model))
    rng = random.Random(seed)
    print(f"Semantic-layer check: {len(cases)} facts that pass the rules, judged by {judge.model}")
    for c in corpus.competitors:
        batch = [case for case in cases if case["slot"].competitor == c]
        rng.shuffle(batch)
        claims = [Claim(i, case["slot"], case["fact"].value, case["fact"].doc_id, case["fact"].quote)
                  for i, case in enumerate(batch)]
        try:
            judgments = judge.judge(claims, corpus)
        except JudgeError as e:
            print(f"  {c}: judge unavailable ({e})")
            for case in batch:
                case["semantic_pass"], case["reason"] = None, f"unavailable: {e}"
            continue
        for case, j in zip(batch, judgments):
            case["semantic_pass"], case["reason"] = j.passed, j.reason
        print(f"  {c}: judged {len(batch)}")

    def tally(key: str) -> Counter:
        t = Counter()
        for case in cases:
            verdict = case[key]
            if verdict is None:
                t["unavailable"] += 1
            elif verdict and not case["correct"]:
                t["false_pass"] += 1
            elif not verdict and case["correct"]:
                t["false_reject"] += 1
        return t

    n_wrong = sum(not c["correct"] for c in cases)
    rules, both = tally("rules_pass"), tally("semantic_pass")
    print(f"\n{'':<28}{'rules only':>14}{'rules + semantic':>20}")
    for kind in ("stale", "wrong_attribute"):
        n = sum(c["kind"] == kind for c in cases)
        r = sum(c["kind"] == kind and c["rules_pass"] for c in cases)
        s = sum(c["kind"] == kind and bool(c["semantic_pass"]) for c in cases)
        print(f"{kind + ' facts passed':<28}{f'{r}/{n}':>14}{f'{s}/{n}':>20}")
    n_ok = len(cases) - n_wrong
    r_rej, s_rej = f"{rules['false_reject']}/{n_ok}", f"{both['false_reject']}/{n_ok}"
    print(f"{'correct facts rejected':<28}{r_rej:>14}{s_rej:>20}")
    if both["unavailable"]:
        print(f"judge unavailable on {both['unavailable']} facts")
    for case in cases:
        if case["semantic_pass"] is not None and case["semantic_pass"] != case["correct"]:
            print(f"  judge error: {case['kind']} {case['slot'].competitor} {case['slot'].attribute}="
                  f"{case['fact'].value!r}: {case['reason']}")

    rows = [{"kind": c["kind"], "competitor": c["slot"].competitor, "attribute": c["slot"].attribute,
             "value": c["fact"].value, "doc_id": c["fact"].doc_id, "quote": c["fact"].quote,
             "correct": c["correct"], "rules_pass": c["rules_pass"], "semantic_pass": c["semantic_pass"],
             "judge_reason": c["reason"]} for c in cases]
    report = {"model": judge.model, "n": len(cases), "n_wrong": n_wrong,
              "rules_only": {"false_passes": rules["false_pass"], "false_rejects": rules["false_reject"]},
              "rules_plus_semantic": {"false_passes": both["false_pass"], "false_rejects": both["false_reject"],
                                      "unavailable": both["unavailable"]},
              "cases": rows}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}")
    return 0 if both["unavailable"] == 0 else 1
