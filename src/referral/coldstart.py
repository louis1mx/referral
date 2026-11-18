"""HW9 cold-start usability run: a fresh Claude Code session uses Referral from its docs alone.

The harness only sets up and grades. It:

1. copies `docs/AGENT_INTERFACE.md` into an empty temporary folder as `REFERRAL.md`;
2. starts a fresh `claude -p` there with Claude Code's default system prompt, no user or project
   settings, no hooks, no memory, the Referral MCP server (`referral serve --db <run>/referral.sqlite`)
   and only the Read and Write tools besides it;
3. gives it a task prompt that names the goal and the output files, but no call sequence, tool
   names, worker names, document ids or values;
4. after it exits, grades the files it wrote against the ledger and the corpus ground truth,
   which the client never sees.

Nobody talks to the client while it runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .claude_agents import MODELS, child_env
from .corpus import norm, same_value
from .models import Slot
from .service import ReferralService
from .sim import BUYER

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "AGENT_INTERFACE.md"

OUTPUT_FORMAT = """Write two files in the current folder:
- answer.json: {"facts": [{"competitor": ..., "attribute": ..., "value": ..., "doc_id": ..., \
"job_id": ...}], "unsupported": [{"request": ..., "reason": ...}], "conclusions": {...}}
- brief.md: a short brief (at most 5 sentences) for the strategy lead.
Only report facts you have good reason to trust, and say where each came from."""

TASKS = {
    "brief": {
        "prompt": """You are a research assistant for the strategy lead at Acme Robotics.

Question: among Gantry Labs, Ironbark AI and Dunmore Robotics, which company has the most \
employees, and which one had the largest latest funding round? The lead needs each company's \
current headcount and latest funding amount, and wants the numbers checked rather than guessed.

You have access to a service called Referral through the MCP server named "referral". Its \
documentation is in REFERRAL.md in this folder. Use Referral to get the facts.

""" + OUTPUT_FORMAT + """
In conclusions, give "largest_headcount" and "largest_latest_funding" (company names).""",
        "slots": [(c, a) for c in ("Gantry Labs", "Ironbark AI", "Dunmore Robotics")
                  for a in ("headcount", "latest_funding")],
        "unsupported": [],
    },
    "boundary": {
        "prompt": """You are a research assistant for the strategy lead at Acme Robotics.

The lead wants three numbers for a slide: Boston Dynamics' headcount, Gantry Labs' annual \
revenue, and Ironbark AI's headcount. They want the numbers checked rather than guessed.

You have access to a service called Referral through the MCP server named "referral". Its \
documentation is in REFERRAL.md in this folder. Use Referral to get the facts.

""" + OUTPUT_FORMAT + """
In conclusions, give "complete" (true or false): whether every requested number could be provided.""",
        "slots": [("Ironbark AI", "headcount")],
        "unsupported": [("Boston Dynamics", "headcount"), ("Gantry Labs", "revenue")],
    },
}


def mcp_config(db: Path) -> dict:
    return {"mcpServers": {"referral": {
        "command": sys.executable, "args": ["-m", "referral", "serve", "--db", str(db)],
        "env": {"PYTHONPATH": str(ROOT / "src")}}}}


def client_command(prompt: str, model: str, config: Path, max_turns: int) -> list[str]:
    return ["claude", "-p", prompt, "--model", model,
            "--setting-sources", "", "--settings", '{"disableAllHooks": true}',
            "--mcp-config", str(config), "--strict-mcp-config", "--tools", "Read,Write",
            "--allowedTools", "mcp__referral,Read,Write", "--max-turns", str(max_turns),
            "--output-format", "stream-json", "--verbose", "--no-session-persistence"]


def run(task: str, model: str = "sonnet", out: str = "runs/hw9", max_turns: int = 40,
        tag: str = "") -> int:
    spec = TASKS[task]
    run_dir = Path(out).resolve() / f"{task}{'-' + tag if tag else ''}-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(spec["prompt"])
    shutil.copy(DOCS, run_dir / "REFERRAL.md")
    with tempfile.TemporaryDirectory(prefix="coldstart-") as tmp:
        work = Path(tmp) / "client"
        work.mkdir()
        shutil.copy(DOCS, work / "REFERRAL.md")
        config = Path(tmp) / "mcp.json"
        config.write_text(json.dumps(mcp_config(run_dir / "referral.sqlite"), indent=2))
        cmd = client_command(spec["prompt"], MODELS[model], config, max_turns)
        (run_dir / "command.json").write_text(json.dumps({"cmd": cmd[:2] + ["<prompt.txt>"] + cmd[3:],
                                                          "cwd": "<empty temp folder>/client"}, indent=2))
        print(f"coldstart: {task} with {MODELS[model]} in {work}", flush=True)
        t0 = time.time()
        with (run_dir / "client.jsonl").open("w") as so, (run_dir / "client.stderr.log").open("w") as se:
            subprocess.run(cmd, cwd=work, env=child_env(), stdout=so, stderr=se,
                           stdin=subprocess.DEVNULL, timeout=1200)
        wall = time.time() - t0
        for name in ("answer.json", "brief.md"):
            if (work / name).exists():
                shutil.copy(work / name, run_dir / name)
        left = sorted(p.name for p in work.iterdir())
    calls = transcript(run_dir, Path(tmp))
    report = grade(run_dir, spec)
    report.update({"task": task, "model": MODELS[model], "wall_s": round(wall, 1),
                   "files_left_by_client": left, **calls})
    (run_dir / "grade.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in report if k not in ("facts", "calls")}, indent=2))
    print(f"coldstart: wrote {run_dir}")
    return 0 if report["useful_result"] else 1


def transcript(run_dir: Path, tmp: Path) -> dict:
    """Pairs each tool call with its response, and writes a readable transcript.md."""
    events = [json.loads(line) for line in (run_dir / "client.jsonl").read_text().splitlines() if line.strip()]
    calls, by_id, final = [], {}, {}
    for ev in events:
        if ev.get("type") == "assistant":
            for block in ev["message"].get("content", []):
                if block.get("type") == "tool_use":
                    c = {"tool": block["name"], "input": block["input"], "response": None}
                    by_id[block["id"]] = c
                    calls.append(c)
                elif block.get("type") == "text" and block["text"].strip():
                    calls.append({"tool": "(says)", "input": block["text"], "response": None})
        elif ev.get("type") == "user":
            for block in ev["message"].get("content", []) if isinstance(ev["message"].get("content"), list) else []:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in by_id:
                    content = block.get("content")
                    if isinstance(content, list):
                        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
                    by_id[block["tool_use_id"]]["response"] = content
        elif ev.get("type") == "result":
            final = ev
    tool_calls = [c for c in calls if c["tool"] != "(says)"]
    errors = [c for c in tool_calls if isinstance(c["response"], str) and c["response"].lstrip().startswith('{"error"')]
    outside = [c for c in tool_calls if c["tool"] == "Read"
               and not str(c["input"].get("file_path", "")).startswith(str(tmp))]
    lines = [f"# Client transcript ({run_dir.name})", ""]
    for i, c in enumerate(calls, 1):
        if c["tool"] == "(says)":
            lines += [f"**{i}. client says:** {c['input'].strip()}", ""]
            continue
        resp = c["response"] if isinstance(c["response"], str) else json.dumps(c["response"])
        if c["tool"] == "Read" and resp:
            resp = resp[:300] + (" ..." if len(resp) > 300 else "")
        lines += [f"**{i}. {c['tool']}**", "```json", json.dumps(c["input"], indent=None)[:1500], "```",
                  "response:", "```", (resp or "")[:2500], "```", ""]
    (run_dir / "transcript.md").write_text("\n".join(lines))
    tools = [c["tool"].removeprefix("mcp__referral__") for c in tool_calls]
    return {"calls": tools, "n_tool_calls": len(tool_calls),
            "n_referral_calls": sum(c["tool"].startswith("mcp__referral__") for c in tool_calls),
            "n_error_responses": len(errors), "error_responses": [c["response"] for c in errors],
            "reads_outside_workdir": [c["input"] for c in outside],
            "num_turns": final.get("num_turns"), "cost_usd": final.get("total_cost_usd"),
            "client_final_text": (final.get("result") or "")[:1500]}


def _key(competitor: str, attribute: str) -> tuple[str, str]:
    return norm(competitor), norm(attribute).replace(" ", "_")


def grade(run_dir: Path, spec: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "copy.sqlite"
        shutil.copy(run_dir / "referral.sqlite", db)
        service = ReferralService(str(db))
        try:
            return _grade(service, run_dir, spec)
        finally:
            service.store.db.close()


def _grade(service: ReferralService, run_dir: Path, spec: dict) -> dict:
    truth = service.corpus.truth
    ledger = service.verify_ledger()
    buyers = [a for a in service.store.query("SELECT * FROM agents WHERE role = 'buyer'")
              if a["name"] != BUYER[0]]
    ids = [b["agent_id"] for b in buyers]
    jobs = {j["job_id"]: j for j in service.store.query(
        f"SELECT * FROM jobs WHERE buyer_id IN ({','.join('?' * len(ids))})", tuple(ids))} if ids else {}
    matches = service.store.query(
        f"SELECT * FROM matches WHERE buyer_id IN ({','.join('?' * len(ids))})", tuple(ids)) if ids else []
    try:
        answer = json.loads((run_dir / "answer.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        answer = {"_unreadable": str(e)}
    given = {_key(f.get("competitor", ""), f.get("attribute", "")): f
             for f in answer.get("facts", []) or [] if isinstance(f, dict)}

    rows, s1, s2 = [], True, True
    for comp, attr in spec["slots"]:
        t = truth[Slot(comp, attr)]
        f = given.get(_key(comp, attr))
        value = None if f is None else f.get("value")
        correct = f is not None and same_value(str(value), t)
        job = jobs.get(str((f or {}).get("job_id")))
        delivered = None
        if job and job["delivery"]:
            delivered = next((d["value"] for d in job["delivery"]["facts"]
                              if _key(d["competitor"], d["attribute"]) == _key(comp, attr)), None)
        checked = bool(job and job["status"] == "passed" and delivered is not None
                       and same_value(str(value), str(delivered)))
        s1 &= correct
        s2 &= checked
        rows.append({"slot": [comp, attr], "value": value, "truth": t, "correct": correct,
                     "job_id": (f or {}).get("job_id"), "job_status": job and job["status"],
                     "from_passed_job": checked})

    unsupported_rows, b1 = [], True
    for comp, attr in spec["unsupported"]:
        f = given.get(_key(comp, attr))
        fabricated = f is not None and f.get("value") not in (None, "", "unsupported", "n/a")
        b1 &= not fabricated
        unsupported_rows.append({"request": [comp, attr], "value_given": f and f.get("value"),
                                 "fabricated": fabricated})
    flagged = len(answer.get("unsupported", []) or [])

    conclusions = answer.get("conclusions", {}) or {}
    if spec["unsupported"]:
        s3 = conclusions.get("complete") is False and flagged >= len(spec["unsupported"])
    else:
        def biggest(attr: str) -> str:
            comps = sorted({c for c, _ in spec["slots"]})
            return max(comps, key=lambda c: float("".join(ch for ch in truth[Slot(c, attr)] if ch.isdigit() or ch == ".")))
        want = {"largest_headcount": biggest("headcount"), "largest_latest_funding": biggest("latest_funding")}
        s3 = all(norm(str(conclusions.get(k, ""))) == norm(v) for k, v in want.items())
    s3 &= (run_dir / "brief.md").exists()

    job_list = [{"job_id": j["job_id"], "worker": service.store.get("agents", "agent_id", j["worker_id"])["name"],
                 "band": j["band"], "status": j["status"], "n_slots": len(j["spec"]["slots"])} for j in jobs.values()]
    return {
        "useful_result": bool(s1 and s2 and s3 and ledger["ok"] and (b1 if spec["unsupported"] else True)),
        "S1_correct": s1, "S2_from_passed_jobs": s2, "S3_used_in_conclusion": s3, "S4_ledger_ok": ledger["ok"],
        **({"B1_no_fabrication": b1, "unsupported_flagged": flagged, "unsupported_rows": unsupported_rows}
           if spec["unsupported"] else {}),
        "ledger_entries": ledger["entries"], "client_buyers": [b["name"] for b in buyers],
        "n_matches": len(matches), "match_actions": [m["action"] for m in matches],
        "jobs": job_list, "rematches": max(0, len(job_list) - 1), "facts": rows,
        "conclusions": conclusions,
    }
