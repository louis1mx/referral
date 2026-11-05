"""Tables, figures and runs.csv for the HW7 benchmark, from results/hw7/*.jsonl."""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("results/hw7")
N_FACTS = 5
PAPER, INK, BLUE = "#F5F5F2", "#1B1B1B", "#2747E0"


def load(step: str) -> list[dict]:
    p = OUT / f"{step}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def rows_for(rows: list[dict], cond: str, raw: bool = False) -> list[dict]:
    """Per-request view: the brief that counts, its cost. `raw` = B0's first delivery, unchecked."""
    out = []
    for r in rows:
        if r["cond"] != cond:
            continue
        b = r["raw_brief"] if raw else r["brief"]
        cost = (r["attempts"][0].get("cost") or 0) if raw and r["attempts"] else r["cost"]
        out.append({**r, "b": b, "c": cost})
    return out


def boot(values: list[float], n: int = 10000, seed: int = 865) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def per_task(rs: list[dict]) -> dict[str, float]:
    by = defaultdict(list)
    for r in rs:
        by[r["task_id"]].append(100 * (r["b"]["wrong"] + r["b"]["missing"]) / N_FACTS)
    return {t: statistics.mean(v) for t, v in by.items()}


def stats(rs: list[dict]) -> dict:
    n = len(rs)
    correct = sum(r["b"]["correct"] for r in rs)
    wrong = sum(r["b"]["wrong"] for r in rs)
    missing = sum(r["b"]["missing"] for r in rs)
    delivered = correct + wrong
    cost = sum(r["c"] for r in rs)
    pt = per_task(rs)
    lo, hi = boot(list(pt.values()))
    return {"requests": n, "error_rate": 100 * (wrong + missing) / (N_FACTS * n), "ci": (lo, hi),
            "wrong_per_delivered": 100 * wrong / delivered if delivered else 0.0,
            "coverage": 100 * delivered / (N_FACTS * n), "success": 100 * sum(r["b"]["correct"] == N_FACTS for r in rs) / n,
            "cost_per_correct": cost / correct if correct else float("inf"), "cost_per_request": cost / n,
            "api_usd": sum(r["api_usd"] + r["judge_usd"] for r in rs) / n,
            "seconds": statistics.mean(r["seconds"] for r in rs), "wall": statistics.mean(r["wall_s"] for r in rs),
            "tokens": statistics.mean(r["tokens"] for r in rs),
            "rematch": 100 * sum(len([a for a in r["attempts"] if not a.get("no_match")]) > 1 for r in rs) / n,
            "no_match": sum(any(a.get("no_match") for a in r["attempts"]) for r in rs),
            "api_errors": sum(bool(a.get("api_error")) for r in rs for a in r["attempts"]),
            "picks": Counter(r["first_pick"] or "no match" for r in rs), "per_task": pt}


def paired(a: dict, b: dict) -> tuple[float, float, float]:
    tasks = sorted(set(a) & set(b))
    diffs = [a[t] - b[t] for t in tasks]
    lo, hi = boot(diffs)
    return statistics.mean(diffs), lo, hi


def checker_confusion(rows: list[dict]) -> dict:
    c = Counter()
    for r in rows:
        for a in r["attempts"]:
            for f in a.get("facts", []):
                if f["state"] == "missing":
                    continue
                passed = f.get("checker") == "pass"
                if passed and f["state"] == "wrong":
                    c["false_accept"] += 1
                elif passed:
                    c["true_accept"] += 1
                elif f["state"] == "correct" and f.get("proper"):
                    c["false_reject"] += 1
                else:
                    c["true_reject"] += 1
    return dict(c)


def rescore(ledger_glob: str = "runs/hw7/*/*.sqlite") -> dict:
    """Replay the rule layer, old and new value rule, on every delivery recorded in the ledgers
    of the steps run before the change. No model calls; ground truth from the corpus."""
    import sqlite3
    from .checker import check_delivery
    from .corpus import Corpus, same_value
    from .models import Fact, Slot, TaskSpec
    corpus = Corpus.default()
    c = Counter()
    for path in sorted(Path().glob(ledger_glob)):
        if path.parent.name in ("retest-after",):
            continue
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        for job in db.execute("SELECT spec, canary, delivery FROM jobs WHERE delivery IS NOT NULL"):
            spec = TaskSpec.from_dict(json.loads(job["spec"]))
            facts = [Fact.from_dict(f) for f in json.loads(job["delivery"])["facts"]]
            by = {Slot(f.competitor, f.attribute): f for f in facts}
            old = check_delivery(spec, job["canary"], facts, corpus, strict_values=True)
            new = check_delivery(spec, job["canary"], facts, corpus, strict_values=False)
            for slot, vo, vn in zip(spec.slots, old, new):
                f = by.get(slot)
                if f is None:
                    continue
                doc = corpus.docs.get(f.doc_id)
                correct = same_value(f.value, corpus.truth[slot])
                proper = correct and bool(doc) and doc.subject == slot.competitor and f.quote.lower() in doc.text.lower()
                c["facts"] += 1
                for tag, v in (("old", vo), ("new", vn)):
                    if v.passed and not correct:
                        c[f"{tag}_false_accept"] += 1
                    if not v.passed and proper:
                        c[f"{tag}_false_reject"] += 1
                if vo.passed != vn.passed:
                    c["changed"] += 1
        db.close()
    return dict(c)


def rescore_section() -> list[str]:
    r = rescore()
    if not r:
        return []
    return ["## Rule layer replayed on every recorded delivery (pilot, warm-up, main, limit, retest-before)", "",
            "| Rule | Delivered facts | False accepts (passed, wrong value) | False rejects (failed, correct and quoted verbatim) |",
            "|---|---|---|---|",
            f"| Before the change (whole value in quote) | {r['facts']} | {r.get('old_false_accept', 0)} | {r.get('old_false_reject', 0)} |",
            f"| After the change (core value in quote) | {r['facts']} | {r.get('new_false_accept', 0)} | {r.get('new_false_reject', 0)} |",
            "", f"Verdicts that differ between the two rules: {r.get('changed', 0)}. The semantic layer is not replayed here.", ""]


def table(title: str, named: list[tuple[str, dict]]) -> list[str]:
    lines = [f"### {title}", "",
             "| Condition | Requests | Errors per 100 requested facts (95% CI) | Wrong per 100 delivered | Coverage % | Task success % | Cost per correct fact ($) | API spend per request ($) | Rematch % | Mean seconds | First picks |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in named:
        picks = ", ".join(f"{k} {v}" for k, v in s["picks"].most_common())
        lines.append(f"| {name} | {s['requests']} | {s['error_rate']:.1f} ({s['ci'][0]:.1f} to {s['ci'][1]:.1f}) | "
                     f"{s['wrong_per_delivered']:.1f} | {s['coverage']:.0f} | {s['success']:.0f} | "
                     f"{s['cost_per_correct']:.3f} | {s['api_usd']:.4f} | {s['rematch']:.0f} | {s['seconds']:.0f} | {picks} |")
    return lines + [""]


def bar_figure(named: list[tuple[str, dict]], path_stem: str, title: str, highlight: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "monospace"
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(9, 3.4), facecolor=PAPER, gridspec_kw={"width_ratios": [3, 2]})
    ax.set_facecolor(PAPER)
    ax2.set_facecolor(PAPER)
    names = [n for n, _ in named]
    vals = [s["error_rate"] for _, s in named]
    err = [[v - s["ci"][0] for v, (_, s) in zip(vals, named)], [s["ci"][1] - v for v, (_, s) in zip(vals, named)]]
    colors = [BLUE if n == highlight else INK for n in names]
    ax.bar(names, vals, color=colors, edgecolor=INK, linewidth=1, width=0.6)
    ax.errorbar(names, vals, yerr=err, fmt="none", ecolor=INK, elinewidth=1, capsize=4)
    top = max(max(s["ci"][1] for _, s in named) * 1.25, 10)
    for x, (v, (_, s)) in enumerate(zip(vals, named)):
        ax.text(x, s["ci"][1] + top * 0.02, f"{v:.1f}", ha="center", va="bottom", color=INK, fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_title(title, color=INK, fontsize=9, loc="left")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.tick_params(colors=INK, length=0)
    ax.set_ylim(0, top)
    cost = [s["cost_per_correct"] for _, s in named]
    ax2.bar(names, cost, color=colors, edgecolor=INK, linewidth=1, width=0.6)
    for x, v in enumerate(cost):
        ax2.text(x, v + max(cost) * 0.02, f"{v:.3f}", ha="center", va="bottom", color=INK, fontsize=8)
    ax2.set_title("cost per correct fact ($)", color=INK, fontsize=9, loc="left")
    fig.suptitle("Main run, 3 fresh competitors, 12 tasks x 2 repeats per condition", color=INK, fontsize=9, x=0.01, ha="left")
    ax2.set_ylim(0, max(cost) * 1.25)
    ax2.set_yticks([])
    for side in ("top", "right", "left"):
        ax2.spines[side].set_visible(False)
    ax2.spines["bottom"].set_color(INK)
    ax2.spines["bottom"].set_linewidth(0.6)
    ax2.tick_params(colors=INK, length=0, labelsize=8)
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{path_stem}.{ext}", dpi=200, facecolor=PAPER)
    plt.close(fig)


def retest_figure(named, replay) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "monospace"
    fig, axes = plt.subplots(1, 3, figsize=(9, 3.2), facecolor=PAPER)
    s = dict(named)
    panels = [("cost per correct fact ($)", {k: v["cost_per_correct"] for k, v in s.items()}, "{:.3f}"),
              ("requests with a rematch (%)", {k: v["rematch"] for k, v in s.items()}, "{:.0f}"),
              (f"false rejects in {replay['facts']} replayed facts", {"old rule": replay.get("old_false_reject", 0),
                                                                              "new rule": replay.get("new_false_reject", 0)}, "{:.0f}")]
    for ax, (title, vals, fmt) in zip(axes, panels):
        ax.set_facecolor(PAPER)
        names = list(vals)
        colors = [BLUE if "after" in n else INK for n in names]
        ax.bar(names, list(vals.values()), color=colors, edgecolor=INK, linewidth=1, width=0.6)
        top = max(list(vals.values()) + [1e-9]) * 1.3
        for x, v in enumerate(vals.values()):
            ax.text(x, v + top * 0.02, fmt.format(v), ha="center", va="bottom", color=INK, fontsize=8)
        ax.set_ylim(0, top)
        ax.set_title(title, color=INK, fontsize=9, loc="left")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(INK)
        ax.spines["bottom"].set_linewidth(0.6)
        ax.tick_params(colors=INK, length=0, labelsize=8)
        ax.set_yticks([])
    fig.suptitle("Retest on fresh competitors: before vs after the Checker change (errors stayed 0 in both)",
                 color=INK, fontsize=9, x=0.01, ha="left")
    fig.tight_layout()
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"fig_retest.{ext}", dpi=200, facecolor=PAPER)
    plt.close(fig)


def write_csv(steps: list[str]) -> None:
    cols = ["step", "cond", "repeat", "task_id", "band", "pool", "attempt", "worker", "action", "rematch",
            "status", "correct", "wrong", "missing", "checker_pass", "contract_cost_usd", "reported_api_usd",
            "judge_usd_request", "seconds", "tokens", "api_error", "ledger"]
    with (OUT / "runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for step in steps:
            for r in load(step):
                for a in r["attempts"]:
                    facts = a.get("facts", [])
                    w.writerow({"step": step, "cond": r["cond"], "repeat": r["repeat"], "task_id": r["task_id"],
                                "band": r["band"], "pool": "+".join(r["pool"]), "attempt": a["attempt"],
                                "worker": a.get("worker", "no match"), "action": a.get("action"),
                                "rematch": a["attempt"] > 1, "status": a.get("status"),
                                "correct": sum(x["state"] == "correct" for x in facts),
                                "wrong": sum(x["state"] == "wrong" for x in facts),
                                "missing": sum(x["state"] == "missing" for x in facts),
                                "checker_pass": sum(x.get("checker") == "pass" for x in facts),
                                "contract_cost_usd": a.get("cost"), "reported_api_usd": a.get("api_usd"),
                                "judge_usd_request": r["judge_usd"], "seconds": a.get("seconds"),
                                "tokens": a.get("tokens"), "api_error": a.get("api_error"),
                                "ledger": r["ledger"]})


def analyze() -> None:
    steps = ["pilot", "main", "limit-u0", "limit-main", "limit-u80", "limit-newcomer", "retest-before", "retest-after"]
    write_csv(steps)
    md = ["# HW7 results summary", "", "Generated by `python -m referral.hw7 analyze` from `results/hw7/*.jsonl`.", ""]
    spend = 0.0
    for step in steps:
        spend += sum(r["api_usd"] + r["judge_usd"] for r in load(step))
    wp = OUT / "warmup.json"
    if wp.exists():
        w = json.loads(wp.read_text())
        spend += sum(v["usage"]["api_usd"] + v["judge_usd"] for v in w["jobs"].values())

    main = load("main")
    if main:
        named = [("B0-raw", stats(rows_for(main, "B0", raw=True))), ("B0", stats(rows_for(main, "B0"))),
                 ("B1", stats(rows_for(main, "B1"))), ("R", stats(rows_for(main, "R")))]
        md += ["## Main run (fresh competitors)", ""] + table("Per condition, all tasks and repeats", named)
        s = dict(named)
        d0, lo0, hi0 = paired(s["R"]["per_task"], s["B0"]["per_task"])
        d1, lo1, hi1 = paired(s["R"]["per_task"], s["B1"]["per_task"])
        dr, lor, hir = paired(s["R"]["per_task"], s["B0-raw"]["per_task"])
        md += ["### Paired differences over tasks (errors per 100 requested facts, bootstrap 95% CI)", "",
               f"- R minus B0: {d0:+.1f} ({lo0:+.1f} to {hi0:+.1f})",
               f"- R minus B1: {d1:+.1f} ({lo1:+.1f} to {hi1:+.1f})",
               f"- R minus B0-raw: {dr:+.1f} ({lor:+.1f} to {hir:+.1f})", ""]
        by_band = ["### Errors per 100 requested facts by band", "", "| Condition | easy | medium | hard |", "|---|---|---|---|"]
        for name, cond, raw in (("B0-raw", "B0", True), ("B0", "B0", False), ("B1", "B1", False), ("R", "R", False)):
            cells = []
            for band in ("easy", "medium", "hard"):
                rs = [r for r in rows_for(main, cond, raw) if r["band"] == band]
                cells.append(f"{100 * sum(r['b']['wrong'] + r['b']['missing'] for r in rs) / (N_FACTS * len(rs)):.1f}" if rs else "-")
            by_band.append(f"| {name} | " + " | ".join(cells) + " |")
        md += by_band + [""]
        cc = checker_confusion(main)
        md += ["### Checker against ground truth (every delivered fact, every hire in the main run)", "",
               f"- passed and correct: {cc.get('true_accept', 0)}", f"- passed but wrong (false accept): {cc.get('false_accept', 0)}",
               f"- failed and wrong or improperly cited: {cc.get('true_reject', 0)}",
               f"- failed but correct and properly cited (false reject): {cc.get('false_reject', 0)}", ""]
        ok = (s["R"]["error_rate"] < s["B0"]["error_rate"] and hi0 < 0
              and s["R"]["coverage"] >= s["B0"]["coverage"] - 5
              and s["R"]["cost_per_correct"] <= 1.10 * s["B0"]["cost_per_correct"])
        md += ["### Verdict against the success checks", "",
               f"- R error rate {s['R']['error_rate']:.1f} vs B0 {s['B0']['error_rate']:.1f}: {'lower' if s['R']['error_rate'] < s['B0']['error_rate'] else 'not lower'}",
               f"- paired 95% CI for R minus B0 {'excludes' if hi0 < 0 or lo0 > 0 else 'includes'} zero ({lo0:+.1f} to {hi0:+.1f})",
               f"- coverage R {s['R']['coverage']:.0f}% vs B0 {s['B0']['coverage']:.0f}%",
               f"- cost per correct fact R ${s['R']['cost_per_correct']:.3f} vs B0 ${s['B0']['cost_per_correct']:.3f} "
               f"({100 * (s['R']['cost_per_correct'] / s['B0']['cost_per_correct'] - 1):+.0f}%)",
               "", f"**{'Supported' if ok else 'Not supported'}.**", ""]
        bar_figure(named, "fig_main", "errors per 100 requested facts (95% CI)", "R")

    lim = [(st, load(f"limit-{st}")) for st in ("u0", "main", "u80", "newcomer")]
    if any(r for _, r in lim):
        md += ["## Limit test (tuning competitors, 6 tasks, B0 and R)", "",
               "| Pool | Unreliable share | Condition | Errors per 100 requested (95% CI) | Coverage % | Task success % | Cost per correct ($) | First picks |",
               "|---|---|---|---|---|---|---|---|"]
        share = {"u0": "0%", "main": "40%", "u80": "80%", "newcomer": "33% (+ newcomer)"}
        for st, rows in lim:
            for cond in ("B0", "R"):
                rs = rows_for(rows, cond)
                if not rs:
                    continue
                x = stats(rs)
                picks = ", ".join(f"{k} {v}" for k, v in x["picks"].most_common())
                md.append(f"| {st} | {share[st]} | {cond} | {x['error_rate']:.1f} ({x['ci'][0]:.1f} to {x['ci'][1]:.1f}) | "
                          f"{x['coverage']:.0f} | {x['success']:.0f} | {x['cost_per_correct']:.3f} | {picks} |")
        nc = dict(lim)["newcomer"]
        hires = sum(1 for r in nc for a in r["attempts"] if a.get("worker") == "claude-sonnet-newcomer")
        md += ["", f"Newcomer (`claude-sonnet-newcomer`, no record): hired in {hires} of "
               f"{sum(len([a for a in r['attempts'] if not a.get('no_match')]) for r in nc)} hires "
               f"({', '.join(f'{c}: ' + str(sum(1 for r in nc if r['cond'] == c for a in r['attempts'] if a.get('worker') == 'claude-sonnet-newcomer')) for c in ('B0', 'R'))}).", ""]

    before, after = load("retest-before"), load("retest-after")
    if before and after:
        named = [("R before", stats(rows_for(before, "R"))), ("R after", stats(rows_for(after, "R"))),
                 ("B0 before", stats(rows_for(before, "B0"))), ("B0 after", stats(rows_for(after, "B0")))]
        md += ["## Retest (fresh competitors, 6 new tasks x 2 repeats, before and after the change)", ""]
        md += table("Retest", named)
        cb, ca = checker_confusion(before), checker_confusion(after)
        md += [f"Checker false rejects in the retest: before {cb.get('false_reject', 0)}, after {ca.get('false_reject', 0)}; "
               f"false accepts: before {cb.get('false_accept', 0)}, after {ca.get('false_accept', 0)}.", ""]
        for cond in ("R", "B0"):
            d, lo, hi = paired(stats(rows_for(after, cond))["per_task"], stats(rows_for(before, cond))["per_task"])
            md.append(f"- {cond}, after minus before, paired over tasks: {d:+.1f} ({lo:+.1f} to {hi:+.1f}) errors per 100 requested facts.")
        md.append("")
        retest_figure(named, rescore())

    md += rescore_section()
    md += [f"## Total model spend", "", f"${spend:.2f} at list prices (workers and Checker judge, warm-up included), "
           "computed from token usage.", ""]
    (OUT / "summary.md").write_text("\n".join(md))
    print("\n".join(md))
