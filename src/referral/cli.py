"""Command line: `referral demo | eval | live-eval | check-eval | serve | mvp | audit`."""

from __future__ import annotations

import argparse
import sys

from .models import LiveClock


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="referral", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo", help="narrated end-to-end demo")
    demo.add_argument("--seed", type=int, default=4)
    ev = sub.add_parser("eval", help="compare picking strategies")
    ev.add_argument("--seeds", type=int, default=20)
    ev.add_argument("--first-seed", type=int, default=1)
    ev.add_argument("--out", default="results/eval.json")
    live = sub.add_parser("live-eval", help="measure calibration of real Claude models (spends API credit)")
    live.add_argument("--n", type=int, default=30, help="tasks per model, balanced across bands")
    live.add_argument("--models", default="opus,sonnet,haiku")
    live.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    live.add_argument("--out", default="results/live_eval.json")
    live.add_argument("--yes", action="store_true", help="confirm spending API credit")
    live.add_argument("--use-profile", action="store_true", help="use an `ant auth login` profile")
    serve = sub.add_parser("serve", help="run the MCP server with a seeded history")
    serve.add_argument("--seed", type=int, default=4)
    serve.add_argument("--db", default=":memory:", help="SQLite path (default: in memory)")
    serve.add_argument("--transport", default="stdio", choices=["stdio", "http"])
    serve.add_argument("--port", type=int, default=8791, help="HTTP port (serves /mcp on 127.0.0.1)")
    serve.add_argument("--claude-worker", choices=["haiku", "sonnet", "opus"],
                       help="also register a Claude worker that Claude Code runs on dispatch (http only)")
    serve.add_argument("--run-dir", default="runs/serve", help="where Claude worker logs go")
    serve.add_argument("--semantic-checker", default="none", choices=["none", "haiku", "sonnet", "opus"],
                       help="model for the Checker's semantic layer on live jobs")
    serve.add_argument("--semantic-via", default="cli", choices=["cli", "api"],
                       help="run the semantic layer through the claude CLI or the Anthropic API")
    mvp = sub.add_parser("mvp", help="two Claude Code agents hire and work through Referral, then audit")
    mvp.add_argument("--buyer-model", default="sonnet", choices=["haiku", "sonnet", "opus"])
    mvp.add_argument("--worker-model", default="haiku", choices=["haiku", "sonnet", "opus"])
    mvp.add_argument("--port", type=int, default=8791)
    mvp.add_argument("--checker-model", default="haiku", choices=["none", "haiku", "sonnet", "opus"],
                     help="model for the Checker's semantic layer; none runs the rule layer only")
    mvp.add_argument("--out", default="runs", help="a timestamped run folder is created here")
    ce = sub.add_parser("check-eval", help="adversarial facts through the rule layer vs. rules + semantic layer (runs the claude CLI)")
    ce.add_argument("--model", default="haiku", choices=["haiku", "sonnet", "opus"])
    ce.add_argument("--out", default="results/semantic_check.json")
    aud = sub.add_parser("audit", help="independently check a run: ledger, Checker vs ground truth, answer")
    aud.add_argument("run_dir")
    args = parser.parse_args(argv)

    if args.cmd == "demo":
        from .sim import run_demo
        run_demo(args.seed)
    elif args.cmd == "eval":
        from .evaluate import run
        run(args.seeds, args.out, first_seed=args.first_seed)
    elif args.cmd == "live-eval":
        from .live_eval import main as live_main
        sys.exit(live_main(args.n, args.models.split(","), args.out, args.yes, args.use_profile, args.effort))
    elif args.cmd == "serve":
        serve_main(args)
    elif args.cmd == "mvp":
        from .mvp import run
        sys.exit(run(args.buyer_model, args.worker_model, args.port, args.out, args.checker_model))
    elif args.cmd == "check-eval":
        from .check_eval import run as check_eval
        sys.exit(check_eval(args.model, args.out))
    elif args.cmd == "audit":
        from .audit import main as audit_main
        sys.exit(audit_main(args.run_dir))


def serve_main(args) -> None:
    from pathlib import Path

    from .mcp_server import create_server
    from .sim import build_world, run_trials
    world = build_world(args.seed, clock=LiveClock(), db_path=args.db, live=True)
    run_trials(world)
    service = world.service
    print(f"referral: seeded {service.store.count('jobs')} trial jobs for {len(world.workers)} "
          "simulated workers (rule layer only)", file=sys.stderr, flush=True)
    if args.semantic_checker != "none":
        from .claude_agents import MODELS
        from .semantic import ApiRunner, ClaudeJudge
        runner = {"runner": ApiRunner()} if args.semantic_via == "api" else {}
        service.judge = ClaudeJudge(MODELS[args.semantic_checker], **runner)
        print(f"referral: Checker semantic layer on for live jobs ({service.judge.model})",
              file=sys.stderr, flush=True)
    if args.claude_worker:
        if args.transport != "http":
            sys.exit("--claude-worker needs --transport http: the worker connects as its own MCP client")
        from .claude_agents import MODELS, worker_runtime, write_mcp_config
        run_dir = Path(args.run_dir).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        model = MODELS[args.claude_worker]
        name, price = f"claude-{args.claude_worker}-worker", 0.80
        me = service.register_agent(name, "worker", "owner-claude-workers", model, price, 60)
        config = write_mcp_config(f"http://127.0.0.1:{args.port}/mcp", run_dir / "worker.mcp.json")
        service.attach_worker(me["agent_id"], worker_runtime(
            name=name, model=model, agent_id=me["agent_id"], key=me["key"], price=price,
            mcp_config=config, run_dir=run_dir))
        print(f"referral: registered {name} ({model}), no record yet", file=sys.stderr, flush=True)
    server = create_server(service)
    if args.transport == "http":
        print(f"referral: serving MCP at http://127.0.0.1:{args.port}/mcp", file=sys.stderr, flush=True)
        server.run("streamable-http", port=args.port)
    else:
        print("referral: serving MCP on stdio", file=sys.stderr, flush=True)
        server.run("stdio")


if __name__ == "__main__":
    main()
