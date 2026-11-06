"""Command-line entry point for BabyMind."""

import argparse

from .coordinator import BabyMindCoordinator
from .memory import LocalMemory
from .runtime import BabyMindRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="babymind", description="BabyMind 50-agent personal AI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="Check runtime and agent registry")
    subparsers.add_parser("doctor", help="Run non-destructive installation and security diagnostics")
    subparsers.add_parser("list", help="List all registered agents")
    subparsers.add_parser("integrations", help="Show availability of optional integrations")
    subparsers.add_parser("roles", help="List the 50 development roles and their mission phase")
    subparsers.add_parser("hardware", help="Detect hardware and recommend local model settings")
    subparsers.add_parser("selfdev", help="Report the self-development engine's real state")

    cognitive_parser = subparsers.add_parser("cognitive", help="Inspect or run BabyMind's bounded cognitive core")
    cognitive_actions = cognitive_parser.add_subparsers(dest="cognitive_action", required=True)
    cognitive_actions.add_parser("status", help="Show persistent identity, observed environment, goals, and cycle metrics")
    cognitive_actions.add_parser("evaluate", help="Run deterministic local checks of operational self-awareness")
    cognitive_actions.add_parser("benchmark", help="Run repeatable operational capability benchmarks")
    autonomy_parser = cognitive_actions.add_parser("autonomy", help="Run bounded autonomous cycles with environment drift checks")
    autonomy_parser.add_argument("--cycles", type=int, default=5, choices=range(1, 26), help="Number of cycles (1-25)")
    autonomy_parser.add_argument("--interval", type=float, default=0, help="Seconds between cycles (0-3600)")
    autonomy_parser.add_argument("--agent", default="BM-02", help="Existing role ID used for each cycle")
    goal_parser = cognitive_actions.add_parser("goal", help="Execute one existing goal in bounded verified steps")
    goal_parser.add_argument("goal_id", help="ID of an active local goal")
    goal_parser.add_argument("--max-steps", type=int, default=5, choices=range(1, 11), help="Maximum steps (1-10)")
    goal_parser.add_argument("--agent", default="BM-02", help="Existing role ID used for each step")
    cycle_parser = cognitive_actions.add_parser("cycle", help="Run one observe-to-learn cognitive cycle")
    cycle_parser.add_argument("--agent", default="BM-02", help="Existing role ID to run this cycle through")
    autonomous_parser = cognitive_actions.add_parser("run", help="Run a bounded number of autonomous cognitive cycles")
    autonomous_parser.add_argument("--cycles", type=int, default=5, choices=range(1, 101), help="Number of cycles (1-100)")
    autonomous_parser.add_argument("--interval", type=float, default=0, help="Seconds between cycles (0-3600)")
    autonomous_parser.add_argument("--agent", default="BM-02", help="Existing role ID used for each cycle")
    service_parser = cognitive_actions.add_parser("service", help="Run the persistent Linux cognitive background service")
    service_parser.add_argument("--interval", type=float, default=60, help="Seconds between cycles (5-3600)")
    service_parser.add_argument("--agent", default="BM-02", help="Specialist role used for each cycle")
    cognitive_actions.add_parser("routing", help="Show configured per-agent model routes without exposing secrets")

    mission_parser = subparsers.add_parser("mission", help="Run a mission across all 50 roles")
    mission_parser.add_argument("brief", help="Mission brief")
    mission_parser.add_argument("--max-seconds", type=int, default=900,
                               help="Time budget for the whole mission (default 900)")

    develop_parser = subparsers.add_parser("develop", help="Inspect and verify changes to BabyMind's configured source checkout")
    develop_parser.add_argument("task", help="Description of the source change")
    develop_parser.add_argument("--attempts", type=int, default=2, choices=range(1, 4),
                                help="Maximum patch attempts (default 2)")

    github_parser = subparsers.add_parser("github", help="Search public GitHub repositories")
    github_parser.add_argument("query", help="Search text")
    github_parser.add_argument("--limit", type=int, default=5)

    run_parser = subparsers.add_parser("run", help="Route a task without model inference")
    run_parser.add_argument("agent_id", help="Agent ID, for example BM-01")
    run_parser.add_argument("task", help="Task text")

    ask_parser = subparsers.add_parser("ask", help="Ask the local AI through one agent role")
    ask_parser.add_argument("agent_id", help="Agent ID, for example BM-01")
    ask_parser.add_argument("task", help="Task text")
    ask_parser.add_argument("--remember", action="store_true", help="Save this task and answer to local memory")
    ask_parser.add_argument("--use-memory", action="store_true", help="Include relevant saved memories in this request")

    memory_parser = subparsers.add_parser("memory", help="Inspect or clear local memory")
    memory_actions = memory_parser.add_subparsers(dest="memory_action", required=True)
    memory_actions.add_parser("list", help="List saved local memories")
    memory_actions.add_parser("clear", help="Delete all saved local memories")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "health":
        for key, value in BabyMindRuntime().health().items():
            print(f"{key}: {value}")
    elif args.command == "doctor":
        from .diagnostics import run_diagnostics
        results = run_diagnostics()
        for item in results:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")
        if any(item["status"] == "FAIL" for item in results):
            raise SystemExit(1)
    elif args.command == "integrations":
        from .integrations.catalog import integration_status
        for item in integration_status():
            state = "AVAILABLE" if item["available"] else "NOT INSTALLED"
            print(f"{state}: {item['name']} — {item['purpose']}")
            if not item["available"]:
                print(f"  Install: {item['install_hint']}")
    elif args.command == "roles":
        from .agents import AGENTS
        for agent in AGENTS:
            print(f"{agent.agent_id}  {agent.name:38} {agent.phase:15} {agent.purpose}")
    elif args.command == "hardware":
        from .hardware import hardware_report
        report = hardware_report()
        print(f"cpu: {report['cpu']}")
        print(f"logical cores: {report['logical_cores']}  ram: {report['ram_gb']} GB  free disk: {report['free_disk_gb']} GB")
        print(f"recommended: {report['recommended']['parameter_class']} @ {report['recommended']['context_size']} context")
        print(f"flags: {' '.join(report['llama_cpp_flags'])}")
        print(f"gpu: {report['gpu']}")
    elif args.command == "selfdev":
        from .selfdev import status
        report = status()
        print(f"enabled: {report['enabled']}  root: {report['root']}")
        print(f"can write source: {report['can_write_source']}  auto-verify: {report['automatic_verification']}  auto-rollback: {report['automatic_rollback']}")
        print(f"audit log valid: {report['audit']['valid']}  checkpoints: {len(report['checkpoints'])}")
        if report["problem"]:
            print(f"problem: {report['problem']}")
    elif args.command == "mission":
        from .coordinator import BabyMindCoordinator
        from .orchestrator import MissionStore, Orchestrator
        from .server import DATA_HOME
        store = MissionStore(DATA_HOME)
        orchestrator = Orchestrator(BabyMindCoordinator().provider, store,
                                    max_seconds=args.max_seconds)
        mission = orchestrator.run_now(args.brief)
        for run in mission["runs"]:
            print(f"[{run['status']:11}] {run['agent_id']} {run['agent_name']:38} {run['phase']}")
        print(f"\n{mission['summary']}")
    elif args.command == "develop":
        import json
        from .coding_engine import develop
        try:
            result = develop(BabyMindCoordinator().provider, args.task, attempts=args.attempts)
        except (ValueError, RuntimeError) as error:
            raise SystemExit(str(error)) from error
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result["status"] != "applied":
            raise SystemExit(1)
    elif args.command == "github":
        from .research import github_search
        for item in github_search(args.query, limit=args.limit):
            licence = item["license"]["spdx"] or "no licence"
            print(f"{item['name']}  ★{item['stars']}  {licence}  {item['url']}")
    elif args.command == "list":
        for agent in BabyMindRuntime().agents:
            print(f"{agent.agent_id}  {agent.name} [{agent.domain}] — {agent.purpose}")
    elif args.command == "run":
        try:
            result = BabyMindRuntime().run(args.agent_id, args.task)
        except (KeyError, ValueError) as error:
            raise SystemExit(str(error)) from error
        print(f"agent: {result.agent_id} ({result.agent_name})")
        print(f"status: {result.status}")
        print(f"task: {result.task}")
        print(result.message)
    elif args.command == "ask":
        try:
            result = BabyMindCoordinator().ask(
                args.agent_id, args.task,
                use_memory=args.use_memory, remember=args.remember,
            )
        except (KeyError, ValueError, RuntimeError) as error:
            raise SystemExit(str(error)) from error
        print(f"BabyMind / {result.agent_id} {result.agent_name}")
        print(result.response)
        print(f"memories used: {result.memories_used}")
        print(f"saved to local memory: {result.remembered}")
    elif args.command == "cognitive":
        import json
        import time
        from .cognitive_core import CognitiveCore
        core = CognitiveCore()
        if args.cognitive_action == "status":
            print(json.dumps(core.status(), indent=2, ensure_ascii=False))
        elif args.cognitive_action == "evaluate":
            from .self_evaluation import run_self_evaluation
            report = run_self_evaluation(core)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if not report["all_passed"]:
                raise SystemExit(1)
        elif args.cognitive_action == "benchmark":
            from .benchmarks import run_benchmarks
            report = run_benchmarks(core)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if not report["all_passed"]:
                raise SystemExit(1)
        elif args.cognitive_action == "routing":
            from .model_router import ModelRouter
            print(json.dumps(ModelRouter().routing_status(), indent=2, ensure_ascii=False))
        elif args.cognitive_action == "service":
            from .background import BackgroundService
            try:
                report = BackgroundService(interval=args.interval, agent_id=args.agent, core=core).run()
            except (KeyError, ValueError, RuntimeError) as error:
                raise SystemExit(str(error)) from error
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if report["status"] == "stopped_after_errors":
                raise SystemExit(1)
        elif args.cognitive_action == "autonomy":
            from .autonomy import AutonomyController
            if not 0 <= args.interval <= 3600:
                raise SystemExit("Interval must be between 0 and 3600 seconds.")
            coordinator = BabyMindCoordinator()
            report = AutonomyController(core).run(
                coordinator.model_router,
                cycles=args.cycles, interval=args.interval, agent_id=args.agent,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if report["status"] != "completed" or report["verified_cycles"] != report["completed_cycles"]:
                raise SystemExit(1)
        elif args.cognitive_action == "goal":
            from .autonomy import AutonomyController
            coordinator = BabyMindCoordinator()
            report = AutonomyController(core).execute_goal(
                coordinator.model_router, args.goal_id,
                max_steps=args.max_steps, agent_id=args.agent,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            if report["status"] != "completed":
                raise SystemExit(1)
        else:
            if args.cognitive_action == "run" and not 0 <= args.interval <= 3600:
                raise SystemExit("Interval must be between 0 and 3600 seconds.")
            provider = BabyMindCoordinator().model_router
            count = 1 if args.cognitive_action == "cycle" else args.cycles
            for index in range(count):
                try:
                    result = core.run_cycle(provider, agent_id=args.agent)
                except (KeyError, ValueError, RuntimeError) as error:
                    raise SystemExit(str(error)) from error
                print(json.dumps(result, indent=2, ensure_ascii=False))
                if index + 1 < count and args.interval:
                    time.sleep(args.interval)
    elif args.command == "memory":
        memory = LocalMemory()
        if args.memory_action == "list":
            entries = memory.recent(limit=100)
            if not entries:
                print("No saved memories.")
            for item in entries:
                print(f"[{item['created_at']}] {item['agent_id']}: {item['task']}")
                print(item["response"])
        elif args.memory_action == "clear":
            count = memory.clear()
            print(f"Deleted {count} saved memories.")


if __name__ == "__main__":
    main()
