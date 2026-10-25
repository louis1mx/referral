"""One-line summaries of Claude Code stream-json events, for watching agents use Referral live."""

from __future__ import annotations

import json

PREFIX = "mcp__referral__"


def _short(text: str, n: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _parse(content) -> dict | None:
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], dict):
        data = data["result"]
    return data if isinstance(data, dict) else None


def call_line(name: str, args: dict) -> str:
    tool = name.removeprefix(PREFIX)
    a = {k: v for k, v in args.items() if k not in ("key", "agent_id")}
    if tool == "request_match":
        slots = "; ".join(f"{s.get('competitor')} {s.get('attribute')}" for s in a.get("slots", []))
        extra = f" exclude={a['exclude_workers']}" if a.get("exclude_workers") else ""
        return f"request_match  {len(a.get('slots', []))} facts, budget ${a.get('budget_usd', 2.0)}{extra}  [{_short(slots, 90)}]"
    if tool == "submit_prediction":
        return (f"submit_prediction  job={a.get('job_id')}  p_success={a.get('p_success')}  "
                f"cost=${a.get('cost_usd')}  finish={a.get('finish_seconds')}s")
    if tool == "submit_delivery":
        facts = a.get("facts", [])
        vals = "; ".join(f"{f.get('competitor')} {f.get('attribute')}={f.get('value')}" for f in facts)
        return f"submit_delivery  job={a.get('job_id')}  {len(facts)} facts  [{_short(vals, 110)}]"
    return f"{tool}  {_short(json.dumps(a, separators=(',', ':')), 110)}"


def result_line(name: str, data: dict | None, raw) -> list[str]:
    tool = name.removeprefix(PREFIX)
    if data is None:
        return [f"  ← {_short(raw if isinstance(raw, str) else json.dumps(raw), 140)}"]
    if "error" in data:
        return [f"  ← error: {_short(data['error'])}"]
    if tool == "register_agent":
        return [f"  ← registered {data.get('agent_id')}"]
    if tool == "describe_corpus":
        return [f"  ← {len(data.get('documents', []))} permitted documents about "
                f"{len(data.get('competitors', []))} competitors, as of {data.get('as_of')}"]
    if tool == "read_document":
        return [f"  ← {data.get('doc_id')} ({data.get('subject')}, {data.get('date')})"]
    if tool == "request_match":
        c = data.get("candidate") or {}
        guide = "; ".join(c.get("guidance", [])[:2])
        return [f"  ← band={data.get('difficulty_band')}  action={data.get('action')}  "
                f"candidate={c.get('name')} [{c.get('tier')}, evidence {c.get('evidence')}]  {_short(guide, 70)}"]
    if tool == "hire":
        return [f"  ← {data.get('job_id')} dispatched to {data.get('worker')}  status={data.get('status')}"]
    if tool == "get_assignment":
        jobs = data.get("assignments", [])
        return [f"  ← {len(jobs)} assignment(s): " + ", ".join(
            f"{j['job_id']} ({j['difficulty_band']}, {len(j['task']['slots'])} slots)" for j in jobs)]
    if tool == "submit_prediction":
        return [f"  ← forecast locked={data.get('locked')}"]
    if tool == "submit_delivery":
        return [f"  ← Checker verdict: {data.get('status')}"]
    if tool == "get_record":
        lines = [f"  ← {data.get('job_id')} by {data.get('worker')}: status={data.get('status')}  "
                 f"recommendation={data.get('recommendation')}"]
        for f in data.get("facts", []):
            lines.append(f"      {f['competitor']:<20} {f['attribute']:<17} {str(f['value']):<14} {f['check']}")
        sem = data.get("semantic_check")
        if sem:
            lines.append(f"      semantic check ({sem.get('model')}): {sem.get('status')}, judged {sem.get('judged')} "
                         f"rule-passing facts, rejected {sem.get('rejected')}")
        return lines
    if tool == "get_insight":
        return [f"  ← [{data.get('tier')}] {_short('; '.join(data.get('guidance', [])), 120)}"]
    return [f"  ← {_short(json.dumps(data), 140)}"]


class Tracer:
    """Turns one agent's stream-json lines into readable lines, pairing calls with results."""

    def __init__(self, who: str):
        self.who = who
        self.pending: dict[str, str] = {}
        self.final: dict | None = None

    def feed(self, line: str) -> list[str]:
        try:
            ev = json.loads(line)
        except ValueError:
            return []
        out: list[str] = []
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    self.pending[c["id"]] = c["name"]
                    out.append(f"[{self.who}] → {call_line(c['name'], c.get('input', {}))}")
                elif c.get("type") == "text" and c.get("text", "").strip():
                    out.append(f"[{self.who}] says: {_short(c['text'], 160)}")
        elif ev.get("type") == "user":
            content = ev.get("message", {}).get("content", [])
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result":
                    name = self.pending.pop(c.get("tool_use_id"), "?")
                    raw = c.get("content")
                    out += [f"[{self.who}] {x.lstrip()}" if i == 0 else f"[{self.who}] {x}"
                            for i, x in enumerate(result_line(name, _parse(raw), raw))]
        elif ev.get("type") == "result":
            self.final = ev
            out.append(f"[{self.who}] done: {ev.get('num_turns')} turns, {ev.get('duration_ms', 0) / 1000:.0f}s, "
                       f"model cost ${ev.get('total_cost_usd', 0):.3f}")
        return out
