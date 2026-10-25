"""HW6 MVP run: two Claude Code agents hire and work through Referral, then an audit checks it.

1. Start Referral as an MCP server over HTTP, seeded with five simulated workers' trial records,
   plus one Claude worker that has no record yet.
2. Start the buyer, Acme Robotics' competitive-intelligence agent, with a goal and Referral's
   MCP tools only. It registers, asks for a match, hires, waits for the checked record,
   rematches if the Checker failed the job, and returns a brief built from passed facts.
3. If Referral dispatches to the Claude worker, the dispatch hook starts it; it locks a
   forecast, reads the permitted documents and delivers cited facts through the same tools.
4. `referral audit` re-checks the run from the database alone (see audit.py).

Everything lands in runs/<timestamp>/: the agents' raw stream-json, the server log, the
SQLite ledger, the buyer's answer, a readable transcript and the audit.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .claude_agents import MODELS, claude_command, start_claude, write_mcp_config
from .trace import Tracer

BUYER_NAME = "acme-intel-agent"

BUYER_SYSTEM = """You are {name}, the competitive-intelligence agent of Acme Robotics, running on \
{model}. You never research facts yourself: you hire worker agents through Referral, a hiring \
service for agents, using only its MCP tools. Register yourself once as a buyer (name {name}, \
owner owner-acme, model {model}).
Rules: spend at most $2.00 and allow 300 seconds per hire. Use only facts whose Checker result is \
pass. If a hire fails, rematch without that worker, at most twice. Never invent or repair a fact."""

BUYER_TASK = """Acme's strategy team needs a verified brief for Monday's board meeting with five \
facts: Ironbark AI's latest funding, Gantry Labs' latest funding, Gantry Labs' headcount, Dunmore \
Robotics' flagship product, and Everline Systems' headquarters city. Get them through Referral.
End with only a JSON object: {"facts": [{"competitor": ..., "attribute": ..., "value": ..., \
"doc_id": ..., "job_id": ...}], "hires": [{"job_id": ..., "worker": ..., "status": ...}], \
"note": "<one sentence>"}"""

COLORS = {"buyer": "36", "worker": "33", "referral": "35", "audit": "32"}
RUN_TIMEOUT_S = 900


class Console:
    def __init__(self, transcript: Path):
        self.file = transcript.open("w")
        self.tty = sys.stdout.isatty()

    def __call__(self, line: str, who: str = "") -> None:
        self.file.write(line + "\n")
        self.file.flush()
        color = COLORS.get(who.split(":")[0])
        print(f"\033[{color}m{line}\033[0m" if self.tty and color else line, flush=True)


class Tail:
    def __init__(self, path: Path):
        self.path, self.pos, self.buf = path, 0, ""

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            f.seek(self.pos)
            self.buf += f.read()
            self.pos = f.tell()
        *done, self.buf = self.buf.split("\n")
        return done


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _answer(final: dict | None) -> dict | None:
    text = (final or {}).get("result") or ""
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1]) if start >= 0 else None
    except ValueError:
        return None


def run(buyer_model: str, worker_model: str, port: int, out: str) -> int:
    if _port_open(port):
        sys.exit(f"port {port} is already in use; pass --port")
    run_dir = (Path(out) / datetime.now().strftime("%Y%m%d-%H%M%S")).resolve()
    run_dir.mkdir(parents=True)
    say = Console(run_dir / "transcript.txt")
    src = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")]))}

    server_log = run_dir / "server.log"
    server = subprocess.Popen(
        [sys.executable, "-m", "referral", "serve", "--transport", "http", "--port", str(port),
         "--db", str(run_dir / "referral.sqlite"), "--claude-worker", worker_model, "--run-dir", str(run_dir)],
        stdout=subprocess.DEVNULL, stderr=server_log.open("w"), env=env, cwd=run_dir)
    try:
        for _ in range(100):
            if _port_open(port):
                break
            if server.poll() is not None:
                sys.exit(f"Referral server exited; see {server_log}")
            time.sleep(0.2)
        tails: dict[Path, tuple[Tail, Tracer | None, str]] = {server_log: (Tail(server_log), None, "referral")}
        for line in tails[server_log][0].lines():
            if line.startswith("referral: "):
                say(f"[referral] {line.removeprefix('referral: ')}", "referral")

        model = MODELS[buyer_model]
        config = write_mcp_config(f"http://127.0.0.1:{port}/mcp", run_dir / "buyer.mcp.json")
        cmd = claude_command(BUYER_TASK, BUYER_SYSTEM.format(name=BUYER_NAME, model=model), model, config)
        say(f"[buyer] goal: {' '.join(BUYER_TASK.split(chr(10))[0].split())}", "buyer")
        buyer = start_claude(cmd, run_dir / "buyer.jsonl", run_dir)
        buyer_trace = Tracer("buyer")
        tails[run_dir / "buyer.jsonl"] = (Tail(run_dir / "buyer.jsonl"), buyer_trace, "buyer")

        started, drained_at = time.monotonic(), None
        while True:
            for p in sorted(run_dir.glob("worker-*.jsonl")):
                if p not in tails:
                    who = f"worker:{p.stem.removeprefix('worker-')}"
                    tails[p] = (Tail(p), Tracer(who), who)
            for tail, tracer, who in tails.values():
                for line in tail.lines():
                    if tracer is None:
                        if line.startswith("referral: dispatched"):
                            say(f"[referral] {line.removeprefix('referral: ')}", who)
                        continue
                    for out_line in tracer.feed(line):
                        say(out_line, who)
            if buyer.poll() is not None:
                drained_at = drained_at or time.monotonic()
                if time.monotonic() - drained_at > 2:
                    break
            if time.monotonic() - started > RUN_TIMEOUT_S:
                buyer.kill()
                say(f"[buyer] stopped after {RUN_TIMEOUT_S}s", "buyer")
                break
            time.sleep(0.2)
    finally:
        server.terminate()
        server.wait(timeout=10)

    answer = _answer(buyer_trace.final)
    (run_dir / "answer.json").write_text(json.dumps(answer, indent=2) if answer else "null")
    if answer:
        say("[buyer] final brief:", "buyer")
        for f in answer.get("facts", []):
            say(f"[buyer]   {f.get('competitor')} {f.get('attribute')}: {f.get('value')}  "
                f"(source {f.get('doc_id')}, {f.get('job_id')})", "buyer")
    else:
        say("[buyer] no parseable JSON brief in the final message", "buyer")

    from .audit import run_audit
    report = run_audit(run_dir, lambda line: say(line, "audit"))
    say(f"run folder: {run_dir}")
    return 0 if report["all_checks_pass"] else 1
