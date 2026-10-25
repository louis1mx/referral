"""Real agents for the MVP demo, run by Claude Code in headless mode (`claude -p`).

Both sides reach Referral only through its MCP tools over HTTP:

- the buyer is Acme Robotics' competitive-intelligence agent, which hires through Referral;
- the worker is a Claude worker registered on Referral. When Referral dispatches a job to
  it, the dispatch hook starts its runtime, the way a webhook wakes a hosted agent.

No step is relayed by a person: each agent decides its own tool calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# A buyer's get_record may wait up to 300 s, so Claude Code must not time the call out first.
MCP_TOOL_TIMEOUT_MS = "330000"

WORKER_SYSTEM = """You are {name}, a research worker agent on the Referral marketplace, running on \
{model}. You earn a ${price:.2f} fee per job. You act only through the Referral MCP tools.
Your Referral credentials: agent_id={agent_id} key={key}. Pass both on every call that takes them.
Referral scores you on whether your locked forecast matches the checked result, so forecast honestly."""

WORKER_TASK = """Referral has dispatched job {job_id} to you.
1. Call get_assignment to read the task and its acceptance criteria.
2. Before you research, lock your forecast with submit_prediction: p_success is your probability \
that every fact passes Referral's Checker, cost_usd is your fee, finish_seconds is your estimate. \
You may call describe_corpus first. A locked forecast cannot be revised.
3. Read the permitted documents you need with read_document.
4. Call submit_delivery with one fact per slot: competitor, attribute, value, doc_id, quote. \
The quote must be copied verbatim from that document and contain the value.
5. Reply with one line: the job id and the status submit_delivery returned."""


def write_mcp_config(url: str, path: Path) -> Path:
    path.write_text(json.dumps({"mcpServers": {"referral": {"type": "http", "url": url}}}, indent=2))
    return path


def claude_command(prompt: str, system: str, model: str, mcp_config: Path, max_turns: int = 40) -> list[str]:
    """A Claude Code run whose only tools are Referral's MCP tools. It loads no user or project
    settings and runs no hooks, so local plugins cannot add context to the agent."""
    return ["claude", "-p", prompt, "--model", model, "--system-prompt", system,
            "--setting-sources", "", "--settings", '{"disableAllHooks": true}',
            "--mcp-config", str(mcp_config), "--strict-mcp-config", "--tools", "",
            "--allowedTools", "mcp__referral", "--max-turns", str(max_turns),
            "--output-format", "stream-json", "--verbose", "--no-session-persistence"]


def child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env["MCP_TOOL_TIMEOUT"] = MCP_TOOL_TIMEOUT_MS
    return env


def start_claude(cmd: list[str], log_path: Path, cwd: Path) -> subprocess.Popen:
    out = log_path.open("w")
    err = log_path.with_suffix(".stderr.log").open("w")
    return subprocess.Popen(cmd, stdout=out, stderr=err, cwd=cwd, env=child_env(),
                            stdin=subprocess.DEVNULL)


def worker_runtime(*, name: str, model: str, agent_id: str, key: str, price: float,
                   mcp_config: Path, run_dir: Path) -> Callable[[object, dict], None]:
    """Dispatch hook: start the Claude worker for each job Referral sends it."""
    system = WORKER_SYSTEM.format(name=name, model=model, price=price, agent_id=agent_id, key=key)
    procs: list[subprocess.Popen] = []

    def on_dispatch(service, assignment: dict) -> None:
        job_id = assignment["job_id"]
        cmd = claude_command(WORKER_TASK.format(job_id=job_id), system, model, mcp_config)
        procs.append(start_claude(cmd, run_dir / f"worker-{job_id}.jsonl", run_dir))
        print(f"referral: dispatched {job_id} to {name}; started its Claude Code runtime ({model})",
              file=sys.stderr, flush=True)

    on_dispatch.procs = procs  # type: ignore[attr-defined]
    return on_dispatch
