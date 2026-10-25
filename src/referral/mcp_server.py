"""Referral as an MCP server (stdio). Buyer and worker agents call these tools directly."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

from .models import ReferralError
from .service import ReferralService

INSTRUCTIONS = """Referral keeps verified track records for agents that hire agents.

Buyer flow: register_agent(role="buyer") once and keep the key -> describe_corpus ->
request_match -> hire -> get_record (pass wait_seconds while the worker is still working). Accept when recommendation is "accept"; otherwise
call request_match again with exclude_workers set to the worker that failed.

Worker flow: register_agent(role="worker", price_usd=...) -> get_assignment ->
read_document -> submit_prediction (locks your forecast; it cannot be revised) ->
submit_delivery with one fact per slot, each quoting its source verbatim.

Referral returns tiers and short guidance, never raw scores."""

# Longest a buyer's get_record call may wait for a worker that is still working.
MAX_WAIT_S = 300.0


def _call(fn: Callable, *args, **kwargs) -> dict[str, Any]:
    try:
        result = fn(*args, **kwargs)
    except ReferralError as e:
        return {"error": str(e)}
    return result if isinstance(result, dict) else {"result": result}


def create_server(service: ReferralService) -> MCPServer:
    mcp = MCPServer("referral", instructions=INSTRUCTIONS)

    @mcp.tool()
    def register_agent(name: str, role: str, owner: str, model: str,
                       price_usd: float | None = None, typical_seconds: float | None = None) -> dict[str, Any]:
        """Register once before anything else. role is "buyer" or "worker"; workers must set
        price_usd. Returns agent_id and key; pass both on every later call."""
        return _call(service.register_agent, name, role, owner, model, price_usd, typical_seconds)

    @mcp.tool()
    def declare_model_change(agent_id: str, key: str, model: str) -> dict[str, Any]:
        """Workers: declare a new underlying model. The record restarts at the trial tier."""
        return _call(service.declare_model_change, agent_id, key, model)

    @mcp.tool()
    def describe_corpus() -> dict[str, Any]:
        """The permitted source corpus: target company, competitors, attributes, documents."""
        return service.describe_corpus()

    @mcp.tool()
    def read_document(doc_id: str) -> dict[str, Any]:
        """Full text of one corpus document."""
        return _call(service.read_document, doc_id)

    @mcp.tool()
    def request_match(agent_id: str, key: str, company: str, slots: list[dict[str, str]],
                      budget_usd: float = 2.0, deadline_seconds: float = 120.0,
                      acceptance: str | None = None, corpus_ids: list[str] | None = None,
                      exclude_workers: list[str] | None = None,
                      min_success: float | None = None) -> dict[str, Any]:
        """Buyers: ask for a worker. slots is a list of {"competitor": ..., "attribute": ...}
        (see describe_corpus). Returns a candidate with tier, evidence strength and guidance,
        and an action: hire, bounded_trial or no_eligible_match. min_success (0-1) is the
        lowest chance of success worth paying for; below it Referral answers no match.
        exclude_workers takes agent ids or names, e.g. a worker whose job failed."""
        task = {"company": company, "slots": slots, "budget": budget_usd,
                "deadline_s": deadline_seconds, "acceptance": acceptance, "corpus_ids": corpus_ids}
        return _call(service.request_match, agent_id, key, task,
                     exclude=tuple(exclude_workers or ()), min_success=min_success)

    @mcp.tool()
    def hire(agent_id: str, key: str, match_id: str) -> dict[str, Any]:
        """Buyers: lock a contract with the matched worker and dispatch the task."""
        return _call(service.hire, agent_id, key, match_id)

    @mcp.tool()
    def get_assignment(agent_id: str, key: str) -> dict[str, Any]:
        """Workers: list jobs waiting for you."""
        return _call(lambda: {"assignments": service.get_assignment(agent_id, key)})

    @mcp.tool()
    def submit_prediction(agent_id: str, key: str, job_id: str, p_success: float,
                          cost_usd: float, finish_seconds: float) -> dict[str, Any]:
        """Workers: lock your forecast (probability that every fact passes, cost, time to
        finish) before you start. It is scored against the checked result and cannot change."""
        return _call(service.submit_prediction, agent_id, key, job_id, p_success, cost_usd,
                     finish_seconds)

    @mcp.tool()
    def submit_delivery(agent_id: str, key: str, job_id: str, facts: list[dict[str, str]],
                        cost_usd: float | None = None) -> dict[str, Any]:
        """Workers: deliver one fact per slot as {"competitor", "attribute", "value", "doc_id",
        "quote"}. The quote must appear verbatim in doc_id and contain the value."""
        return _call(service.submit_delivery, agent_id, key, job_id, facts, cost_usd)

    @mcp.tool()
    def subcontract(agent_id: str, key: str, parent_job_id: str, worker_id: str,
                    slot_indices: list[int], budget_usd: float | None = None) -> dict[str, Any]:
        """Workers: hand some slots of your job to another worker under its own contract.
        Read the result with get_record and mark reused facts with via_job."""
        return _call(service.subcontract, agent_id, key, parent_job_id, worker_id, slot_indices,
                     budget_usd)

    @mcp.tool()
    async def get_record(agent_id: str, key: str, job_id: str, wait_seconds: float = 0.0) -> dict[str, Any]:
        """Buyers: the checked result of one of your own jobs and a recommendation. While the
        worker is still working the recommendation is "wait"; pass wait_seconds (up to 300)
        to block until the Checker has a verdict or the time runs out."""
        deadline = time.monotonic() + min(max(wait_seconds, 0.0), MAX_WAIT_S)
        while True:
            record = _call(service.get_record, agent_id, key, job_id)
            if record.get("recommendation") != "wait" or time.monotonic() >= deadline:
                return record
            await anyio.sleep(1.0)

    @mcp.tool()
    def get_insight(worker_id: str) -> dict[str, Any]:
        """Tier and descriptive guidance for a worker. No raw scores."""
        return _call(service.get_insight, worker_id)

    @mcp.tool()
    def get_credential(worker_id: str, domain: str | None = None) -> dict[str, Any]:
        """A signed credential stating a worker's tier and evidence strength in a domain,
        for other registries (e.g. ERC-8004, NANDA AgentFacts) to carry. Verify it with
        the key from get_issuer_key; it contains no raw scores."""
        return _call(service.get_credential, worker_id, domain)

    @mcp.tool()
    def get_issuer_key() -> dict[str, Any]:
        """Referral's public Ed25519 key (JWK) for verifying credentials offline."""
        return service.get_issuer_key()

    @mcp.tool()
    def verify_credential(credential: dict[str, Any]) -> dict[str, Any]:
        """Convenience check of a Referral credential's signature and validity window."""
        return _call(service.verify_credential, credential)

    return mcp
