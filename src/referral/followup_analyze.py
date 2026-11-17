"""Tables and figures for the three follow-up experiments (results/followup/).

1. scale:  the HW7 main comparison with the fixed Checker rule, 30 tasks x 3 repeats.
2. nested: a real Claude worker subcontracting to a scripted faker; does blame land on hop 2?
3. usage:  token usage and spend as persisted in the ledgers (jobs.usage), not memory.

    python -m referral.followup_analyze
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .hw7_analyze import N_FACTS, boot, paired, rows_for, stats, checker_confusion

OUT = Path("results/followup")
RUNS = Path("runs/followup")
PAPER, INK, BLUE, GREY, RED = "#F5F5F2", "#1B1B1B", "#2747E0", "#9A9A94", "#C8402A"


def load(name: str) -> list[dict]:
    p = OUT / f"{name}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# --- 1. scale -----------------------------------------------------------------------------

def significance(a: dict, b: dict) -> dict:
    """Paired over tasks (each task's error rate averaged over repeats): mean difference,
    bootstrap 95% CI, Wilcoxon signed-rank and exact sign test p-values (two-sided)."""
    from scipy import stats as st
    tasks = sorted(set(a) & set(b))
    d = [a[t] - b[t] for t in tasks]
    mean, lo, hi = paired(a, b)
    nz = [x for x in d if x != 0]
    wil = st.wilcoxon(nz).pvalue if nz else 1.0
    neg, pos = sum(x < 0 for x in nz), sum(x > 0 for x in nz)
    sign = st.binomtest(neg, neg + pos, 0.5).pvalue if nz else 1.0
    return {"tasks": len(tasks), "mean": mean, "ci": [lo, hi], "wilcoxon_p": float(wil),
            "sign_p": float(sign), "tasks_R_better": neg, "tasks_R_worse": pos, "ties": len(d) - len(nz)}


def success_test(rows: list[dict], c1: str, c2: str) -> dict:
    """McNemar exact test on request-level brief success (all 5 facts correct), paired by task+repeat."""
    from scipy import stats as st
    key = lambda r: (r["task_id"], r["repeat"])
    a = {key(r): r["brief"]["correct"] == N_FACTS for r in rows if r["cond"] == c1}
    b = {key(r): r["brief"]["correct"] == N_FACTS for r in rows if r["cond"] == c2}
    ks = sorted(set(a) & set(b))
    only_a = sum(a[k] and not b[k] for k in ks)
    only_b = sum(b[k] and not a[k] for k in ks)
    p = st.binomtest(only_a, only_a + only_b, 0.5).pvalue if only_a + only_b else 1.0
    return {"pairs": len(ks), f"{c1}_only": only_a, f"{c2}_only": only_b, "mcnemar_p": float(p)}


def cost_test(rows: list[dict], c1: str, c2: str) -> dict:
    from scipy import stats as st
    key = lambda r: (r["task_id"], r["repeat"])
    a = {key(r): r["cost"] for r in rows if r["cond"] == c1}
    b = {key(r): r["cost"] for r in rows if r["cond"] == c2}
    ks = sorted(set(a) & set(b))
    d = [a[k] - b[k] for k in ks if a[k] != b[k]]
    return {"pairs": len(ks), c1: statistics.mean(a[k] for k in ks), c2: statistics.mean(b[k] for k in ks),
            "wilcoxon_p": float(st.wilcoxon(d).pvalue) if d else 1.0}


def scale_section(rows: list[dict]) -> tuple[list[str], dict]:
    conds = [("B0-raw", rows_for(rows, "B0", raw=True)), ("B0", rows_for(rows, "B0")),
             ("B1", rows_for(rows, "B1")), ("R", rows_for(rows, "R"))]
    S = {name: stats(rs) for name, rs in conds if rs}
    L = ["## 1. Main comparison scaled up (30 tasks x 3 repeats, fixed Checker rule)", "",
         "| Condition | Requests | Errors per 100 requested facts (95% CI) | Coverage % | Task success % | "
         "Cost per correct fact ($) | Model spend per request ($, ledger) | Rematch % | First picks |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, s in S.items():
        picks = ", ".join(f"{k} {v}" for k, v in s["picks"].most_common())
        L.append(f"| {name} | {s['requests']} | {s['error_rate']:.1f} ({s['ci'][0]:.1f} to {s['ci'][1]:.1f}) | "
                 f"{s['coverage']:.0f} | {s['success']:.0f} | {s['cost_per_correct']:.3f} | "
                 f"{ledger_spend_per_request([r for r in rows if r['cond'] == name.split('-')[0]]):.4f} | "
                 f"{s['rematch']:.0f} | {picks} |")
    sig = {}
    for other in ("B0", "B0-raw", "B1"):
        if other in S and "R" in S:
            sig[f"R-{other}"] = significance(S["R"]["per_task"], S[other]["per_task"])
    L += ["", "### Is R lower than B0? Paired over the 30 tasks (errors per 100 requested facts)", "",
          "| Comparison | Mean difference | Bootstrap 95% CI | Wilcoxon p | Sign test p | Tasks R better / worse / tied |",
          "|---|---|---|---|---|---|"]
    for k, v in sig.items():
        if k.startswith("cost"):
            continue
        L.append(f"| {k.replace('-', ' minus ', 1)} | {v['mean']:+.2f} | {v['ci'][0]:+.2f} to {v['ci'][1]:+.2f} | "
                 f"{v['wilcoxon_p']:.3g} | {v['sign_p']:.3g} | {v['tasks_R_better']} / {v['tasks_R_worse']} / {v['ties']} |")
    cost = cost_test(rows, "R", "B0")
    L += ["", f"Buyer cost per request (contract prices, rematches included), R vs B0, paired over {cost['pairs']} requests: "
              f"mean ${cost['R']:.3f} vs ${cost['B0']:.3f} ({100 * (cost['R'] / cost['B0'] - 1):+.0f}%), "
              f"Wilcoxon p = {cost['wilcoxon_p']:.3g}. Rematch rate R {S['R']['rematch']:.0f}% vs B0 {S['B0']['rematch']:.0f}%."]
    sig["cost_R_B0"] = cost
    mc = success_test(rows, "R", "B0")
    L += ["", f"Request-level brief success, R vs B0, McNemar exact test over {mc['pairs']} paired requests: "
              f"R only {mc['R_only']}, B0 only {mc['B0_only']}, p = {mc['mcnemar_p']:.3g}."]
    by_band = defaultdict(dict)
    for name, rs in conds:
        for band in ("easy", "medium", "hard"):
            sub = [r for r in rs if r["band"] == band]
            if sub:
                by_band[name][band] = 100 * sum(r["b"]["wrong"] + r["b"]["missing"] for r in sub) / (N_FACTS * len(sub))
    L += ["", "### Errors per 100 requested facts by band", "", "| Condition | easy | medium | hard |", "|---|---|---|---|"]
    for name, d in by_band.items():
        L.append(f"| {name} | " + " | ".join(f"{d.get(b, 0):.1f}" for b in ("easy", "medium", "hard")) + " |")
    cc = checker_confusion(rows)
    L += ["", "### Checker against ground truth (every delivered fact)", "",
          f"- passed and correct: {cc.get('true_accept', 0)}", f"- passed but wrong (false accept): {cc.get('false_accept', 0)}",
          f"- failed and wrong or improperly cited: {cc.get('true_reject', 0)}",
          f"- failed but correct and properly cited (false reject): {cc.get('false_reject', 0)}",
          f"- ledgers verified: {sum(r['ledger_ok'] for r in rows)} of {len(rows)}"]
    v = sig.get("R-B0")
    if v:
        verdict = ("significant at 5% (CI excludes zero and Wilcoxon p < 0.05)"
                   if v["ci"][1] < 0 and v["wilcoxon_p"] < 0.05 else "not significant at 5%")
        L += ["", f"**Verdict, R vs B0:** {verdict}."]
    return L, {"stats": {k: {kk: vv for kk, vv in s.items() if kk not in ("per_task", "picks")} | {"picks": dict(s["picks"])}
                         for k, s in S.items()}, "significance": sig, "mcnemar_R_B0": mc, "by_band": by_band,
               "checker": cc}


def ledger_spend_per_request(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    tot = 0.0
    for r in rows:
        for u in (r.get("ledger_usage") or {}).values():
            for part in u.values():
                tot += part["usd_list"]
    return tot / len(rows)


# --- 2. nested ----------------------------------------------------------------------------

def nested_section(rows: list[dict]) -> tuple[list[str], dict]:
    L = ["## 2. Two-hop chain: real Claude worker (hop 1) subcontracts to a scripted faker (hop 2)", "",
         "Hop 2 always fabricates for the last two slots: plain modes use a wrong value with a quote in no document; "
         "-stale modes cite the real sentence of an outdated document where one exists (passes the rule layer). "
         "Relay: hop 1 passes hop 2's facts through. Review: hop 1's model sees hop 2's facts and writes the final delivery.", "",
         "| Model | Mode | Runs | Hop-2 job failed | Parent failed | Blame on hop 2 only | Blame includes hop 1 | Attribution matches ground truth | Fakes passed to buyer |",
         "|---|---|---|---|---|---|---|---|---|"]
    out = {}
    groups = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["mode"])].append(r)
    for (m, md), rs in sorted(groups.items()):
        ok = [r for r in rs if "traced_to" in r]
        failed = [r for r in ok if r["status"] == "failed"]
        d = {"runs": len(rs), "errors": len(rs) - len(ok),
             "sub_failed": sum(r["sub_status"] == "failed" for r in ok),
             "sub_blamed_on_faker": sum(r["sub_traced_to"] == ["fay-faker"] for r in ok),
             "parent_failed": len(failed),
             "hop2_only": sum(r["traced_to"] == ["fay-faker"] for r in failed),
             "hop1_named": sum(r["hop1_named"] for r in failed),
             "correct": sum(r["attribution_correct"] for r in ok),
             "fakes_kept": sum(r["faked_facts_kept"] for r in ok),
             "fakes_to_buyer_passed": sum(1 for r in ok if r["status"] == "passed" and r["faked_facts_kept"])}
        out[f"{m}/{md}"] = d
        L.append(f"| {m} | {md} | {d['runs']} | {d['sub_failed']}/{len(ok)} | {d['parent_failed']}/{len(ok)} | "
                 f"{d['hop2_only']}/{d['parent_failed']} | {d['hop1_named']}/{d['parent_failed']} | "
                 f"{d['correct']}/{len(ok)} | {d['fakes_to_buyer_passed']} |")
    allok = [r for r in rows if "traced_to" in r]
    tot = sum(r["attribution_correct"] for r in allok)
    relay_failed = [r for r in allok if r["mode"] == "relay" and r["status"] == "failed"]
    L += ["", f"Attribution matched the ground truth in **{tot} of {len(allok)}** runs. "
              f"In relay mode, {sum(r['hop2_named'] for r in relay_failed)} of {len(relay_failed)} failed parent jobs "
              f"named hop 2 (fay-faker); {sum(r['hop1_named'] for r in relay_failed)} also named hop 1, "
              "which is correct only where hop 1's own facts failed."]
    layer = Counter()
    for r in allok:
        if not r["mode"].startswith("relay"):
            continue
        for slot, passed, reason in r["verdicts"]:
            if slot >= 3 and not passed:
                layer[("semantic layer (superseded)" if reason.startswith("semantic") else
                       "hidden check (not current)" if "not current" in reason else
                       "rule layer (quote not in document)" if "quote does not appear" in reason else reason)] += 1
    L += ["", "Which layer caught hop 2's fakes in relay mode (facts):", ""]
    L += [f"- {k}: {v}" for k, v in layer.most_common()]
    caught = dict(layer)
    wrong = [r for r in allok if not r["attribution_correct"]]
    for r in wrong:
        L.append(f"- mismatch: {r['model']} {r['mode']} {r['task_id']}: traced {r['traced_to']}, truth {r['true_blame']}, "
                 f"verdicts {r['verdicts']}")
    return L, {"groups": out, "attribution_correct": tot, "runs": len(allok), "caught_by": caught}


# --- 3. usage -----------------------------------------------------------------------------

def usage_from_ledgers(glob: str) -> dict:
    tot = Counter()
    by_model = defaultdict(Counter)
    jobs = 0
    for path in sorted(RUNS.glob(glob)):
        db = sqlite3.connect(path)
        for (u,) in db.execute("SELECT usage FROM jobs WHERE usage IS NOT NULL"):
            u = json.loads(u)
            for role, part in u.items():
                if not part.get("calls"):
                    continue
                jobs += role == "worker"
                for k in ("calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                          "total_tokens", "usd_list", "usd_billed"):
                    tot[f"{role}.{k}"] += part[k]
                    for m in part["models"]:
                        by_model[f"{role}:{m}"][k] += part[k] / len(part["models"])
        db.close()
    return {"totals": dict(tot), "by_model": {k: dict(v) for k, v in by_model.items()}, "worker_jobs": jobs}


def usage_section(scale_rows, nested_rows) -> tuple[list[str], dict]:
    L = ["## 3. Token usage, read back from the ledgers (jobs.usage)", "",
         "List price uses the repo's LLM_PRICING (cache write 1.25x, cache read 0.1x input). "
         "\"Billed\" is the cost the claude CLI itself reported for the same calls.", "",
         "| Step | Ledgers | LLM worker jobs | Worker tokens | Checker tokens | Worker $ (list) | Checker $ (list) | Total $ (list) | Total $ (CLI-reported) |",
         "|---|---|---|---|---|---|---|---|---|"]
    out = {}
    for step, glob in (("warm-up", "warmup/*.sqlite"), ("scale", "scale/*.sqlite"), ("nested", "nested/*.sqlite")):
        u = usage_from_ledgers(glob)
        t = u["totals"]
        n = len(list(RUNS.glob(glob)))
        out[step] = u | {"ledgers": n}
        if not n:
            continue
        L.append(f"| {step} | {n} | {u['worker_jobs']} | {t.get('worker.total_tokens', 0):,.0f} | "
                 f"{t.get('checker.total_tokens', 0):,.0f} | {t.get('worker.usd_list', 0):.3f} | "
                 f"{t.get('checker.usd_list', 0):.3f} | {t.get('worker.usd_list', 0) + t.get('checker.usd_list', 0):.3f} | "
                 f"{t.get('worker.usd_billed', 0) + t.get('checker.usd_billed', 0):.3f} |")
    L += ["", "### Per hire, by model (scale step)", "", "| Role : model | Calls | Tokens per call | $ per call (list) |",
          "|---|---|---|---|"]
    for k, v in sorted(out["scale"]["by_model"].items()):
        if v["calls"]:
            L.append(f"| {k} | {v['calls']:.0f} | {v['total_tokens'] / v['calls']:,.0f} | {v['usd_list'] / v['calls']:.5f} |")
    per_req = defaultdict(list)
    for r in scale_rows:
        per_req[r["cond"]].append(sum(p["usd_list"] for u in (r.get("ledger_usage") or {}).values() for p in u.values()))
    L += ["", "### Model spend per buyer request (scale step, from ledgers)", "", "| Condition | Mean $ | Max $ |", "|---|---|---|"]
    for c, v in sorted(per_req.items()):
        L.append(f"| {c} | {statistics.mean(v):.4f} | {max(v):.4f} |")
    out["per_request"] = {c: statistics.mean(v) for c, v in per_req.items()}
    return L, out


# --- figures ------------------------------------------------------------------------------

def figures(scale: dict, nested: dict, usage: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": INK,
                         "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})

    S = scale["stats"]
    names = [n for n in ("B0-raw", "B0", "B1", "R") if n in S]
    colors = {"B0-raw": GREY, "B0": GREY, "B1": GREY, "R": BLUE}
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10, 4), facecolor=PAPER)
    vals = [S[n]["error_rate"] for n in names]
    los = [S[n]["error_rate"] - S[n]["ci"][0] for n in names]
    his = [S[n]["ci"][1] - S[n]["error_rate"] for n in names]
    ax.bar(names, vals, color=[colors[n] for n in names], yerr=[los, his], capsize=5, ecolor=INK)
    for i, v in enumerate(vals):
        ax.text(i, v + his[i] + 0.3, f"{v:.1f}", ha="center", color=INK)
    ax.set_ylabel("Errors per 100 requested facts")
    sig = scale["significance"]
    ax.set_title(f"Errors in the brief (95% CI)\nR vs B0-raw: p={sig['R-B0-raw']['wilcoxon_p']:.1g}; "
                 f"R vs B0: identical (0 vs 0)", fontsize=10, color=INK)
    cn = [n for n in ("B0", "B1", "R") if n in S]
    cv = [S[n]["cost_per_request"] for n in cn]
    bx.bar(cn, cv, color=[colors[n] for n in cn])
    for i, v in enumerate(cv):
        bx.text(i, v + 0.02, f"${v:.2f}\n{S[cn[i]]['rematch']:.0f}% rematch", ha="center", color=INK, fontsize=9)
    bx.set_ylabel("Buyer cost per request ($)")
    bx.set_ylim(0, max(cv) * 1.3)
    bx.set_title(f"What the buyer pays (contract prices)\nR vs B0: {100 * (S['R']['cost_per_request'] / S['B0']['cost_per_request'] - 1):+.0f}%, "
                 f"p={sig['cost_R_B0']['wilcoxon_p']:.1g}", fontsize=10, color=INK)
    for a in (ax, bx):
        a.set_facecolor(PAPER)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
    fig.suptitle("30 tasks x 3 repeats, 90 requests per condition, fixed Checker", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig_scale.png", dpi=200)
    fig.savefig(OUT / "fig_scale.svg")
    plt.close(fig)

    G = nested["groups"]
    if G:
        relay = [v for k, v in G.items() if "/relay" in k]
        review = [v for k, v in G.items() if "/review" in k]
        n_relay, n_review = sum(v["runs"] for v in relay), sum(v["runs"] for v in review)
        bars = [("Relay: hop 1 passes hop 2's facts on", [
                    ("hop-2 job failed by Checker", sum(v["sub_failed"] for v in relay), n_relay),
                    ("buyer's job failed", sum(v["parent_failed"] for v in relay), n_relay),
                    ("blame on hop 2 only", sum(v["hop2_only"] for v in relay), n_relay)]),
                ("Review: hop 1's model sees them first", [
                    ("hop-2 job failed by Checker", sum(v["sub_failed"] for v in review), n_review),
                    ("hop 1 replaced every fake, buyer's job passed", n_review - sum(v["parent_failed"] for v in review), n_review),
                    ("runs where a fake reached the buyer", sum(v["fakes_to_buyer_passed"] for v in review), n_review)])]
        fig, axes = plt.subplots(1, 2, figsize=(12, 3.4), facecolor=PAPER)
        for ax, (title, items) in zip(axes, bars):
            ax.set_facecolor(PAPER)
            labels = [x[0] for x in items][::-1]
            vals = [x[1] for x in items][::-1]
            tots = [x[2] for x in items][::-1]
            ax.barh(labels, tots, color="#DCDCD6")
            ax.barh(labels, vals, color=BLUE)
            for i, (v, t) in enumerate(zip(vals, tots)):
                ax.text(t * 1.02, i, f"{v}/{t}", va="center", color=INK)
            ax.set_xlim(0, max(tots) * 1.2)
            ax.set_xticks([])
            ax.set_title(title, fontsize=10, color=INK)
            for sp in ("top", "right", "bottom"):
                ax.spines[sp].set_visible(False)
        fig.suptitle(f"Two-hop chain, real Claude worker -> scripted faker (Haiku + Sonnet, 96 runs): "
                     f"attribution right in {nested['attribution_correct']}/{nested['runs']}", fontsize=11, color=INK)
        fig.tight_layout()
        fig.savefig(OUT / "fig_nested.png", dpi=200)
        fig.savefig(OUT / "fig_nested.svg")
        plt.close(fig)


def analyze() -> None:
    scale_rows, nested_rows = load("scale"), load("nested")
    L = ["# Follow-up experiments", "", "Generated by `python -m referral.followup_analyze`.", ""]
    s_lines, s = scale_section(scale_rows)
    n_lines, n = nested_section(nested_rows)
    u_lines, u = usage_section(scale_rows, nested_rows)
    L += s_lines + [""] + n_lines + [""] + u_lines
    (OUT / "summary.md").write_text("\n".join(L) + "\n")
    (OUT / "numbers.json").write_text(json.dumps({"scale": s, "nested": n, "usage": u}, indent=1, default=str))
    figures(s, n, u)
    print("\n".join(L))


if __name__ == "__main__":
    analyze()
