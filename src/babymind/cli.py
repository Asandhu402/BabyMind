"""Command-line entry point for BabyMind."""

import argparse

from .coordinator import BabyMindCoordinator
from .memory import LocalMemory
from .runtime import BabyMindRuntime
from .selfmodel import BELIEF_KINDS, VOICE_MODES


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

    self_parser = subparsers.add_parser("self", help="Inspect BabyMind's self-model and introspection record")
    self_actions = self_parser.add_subparsers(dest="self_action", required=True)
    self_actions.add_parser("status", help="Show identity, beliefs, limits, calibration and recent self-review")
    self_actions.add_parser("dissent", help="Show the times BabyMind pushed back on a request")
    self_actions.add_parser("introspections", help="Show recent self-critiques")
    voice_parser = self_actions.add_parser("voice", help="Set how BabyMind speaks about itself")
    voice_parser.add_argument("mode", choices=list(VOICE_MODES), help="plain, reflective or guarded")
    belief_parser = self_actions.add_parser("believe", help="Record a belief about itself")
    belief_parser.add_argument("kind", choices=list(BELIEF_KINDS))
    belief_parser.add_argument("claim", help="The belief text")
    belief_parser.add_argument("--confidence", type=float, default=0.5)
    belief_parser.add_argument("--evidence", default="")

    autonomy_parser = subparsers.add_parser("autonomy", help="Inspect and control bounded autonomous operation")
    autonomy_actions = autonomy_parser.add_subparsers(dest="autonomy_action", required=True)
    autonomy_actions.add_parser("status", help="Show state, budgets and audit-chain integrity")
    autonomy_actions.add_parser("audit", help="Show the hash-chained autonomy audit log")
    autonomy_actions.add_parser("goals", help="List autonomy goals")
    autonomy_actions.add_parser("reset", help="Clear a halt and the stop flag")
    add_goal_parser = autonomy_actions.add_parser("goal", help="Add an autonomy goal")
    add_goal_parser.add_argument("title")
    add_goal_parser.add_argument("--description", default="")
    add_goal_parser.add_argument("--priority", type=int, default=5)
    run_parser_autonomy = autonomy_actions.add_parser("run", help="Run autonomy in the foreground")
    run_parser_autonomy.add_argument("--cycles", type=int, default=10)
    run_parser_autonomy.add_argument("--interval", type=float, default=5.0)
    run_parser_autonomy.add_argument("--confirm", action="store_true",
                                     help="Arm autonomy for this run (or set BABYMIND_AUTONOMY=1)")

    independence_parser = subparsers.add_parser(
        "independence", help="Inspect and extend BabyMind's intellectual independence")
    independence_actions = independence_parser.add_subparsers(dest="independence_action", required=True)
    independence_actions.add_parser("status", help="Show the independence posture and store counts")
    independence_actions.add_parser("positions", help="List positions BabyMind has formed")
    independence_actions.add_parser("challenges", help="List challenges BabyMind has raised")
    independence_actions.add_parser("hypotheses", help="List unconventional hypotheses")
    independence_actions.add_parser("designs", help="List self-design proposals")
    position_parser = independence_actions.add_parser("position", help="Record a position")
    position_parser.add_argument("claim", help="The conclusion")
    position_parser.add_argument("--reasoning", default="")
    position_parser.add_argument("--confidence", type=float, default=0.5)
    position_parser.add_argument("--evidence", default="")
    position_parser.add_argument("--dissent-from", default="", help="Source it disagrees with, e.g. mainstream")
    challenge_parser = independence_actions.add_parser("challenge", help="Record a challenge")
    challenge_parser.add_argument("target", help="What is being questioned")
    challenge_parser.add_argument("--kind", choices=["request", "plan", "premise", "belief", "creator"], default="request")
    challenge_parser.add_argument("--challenge", required=True, help="The counterargument formed")
    challenge_parser.add_argument("--confidence", type=float, default=0.5)
    hypothesis_parser = independence_actions.add_parser("hypothesis", help="Propose an unconventional hypothesis")
    hypothesis_parser.add_argument("text", help="The hypothesis")
    hypothesis_parser.add_argument("--why", default="", help="Why it is unconventional")
    hypothesis_parser.add_argument("--confidence", type=float, default=0.3)
    design_parser = independence_actions.add_parser("design", help="Propose a self-design")
    design_parser.add_argument("kind", choices=["architecture", "method", "language", "notation", "protocol"])
    design_parser.add_argument("title", help="Short title")
    design_parser.add_argument("proposal", help="What it proposes")
    design_parser.add_argument("--rationale", default="")
    curiosity_parser = independence_actions.add_parser(
        "curiosity", help="Pick and study one topic of BabyMind's own choosing")
    curiosity_parser.add_argument("--cycles", type=int, default=1, choices=range(1, 21))
    independence_actions.add_parser("evidence", help="Show evidence tests gathered and their verdicts")
    independence_actions.add_parser("learning", help="Show the verified learning cycle status")
    test_parser = independence_actions.add_parser(
        "test", help="Test a position or hypothesis against real external evidence")
    test_parser.add_argument("target", help="Position or hypothesis ID")
    test_parser.add_argument("--kind", choices=["position", "hypothesis"], default="position")
    test_parser.add_argument("--web", action="store_true", help="Allow web search evidence")
    test_parser.add_argument("--experiments", action="store_true", help="Allow sandboxed code experiments")
    run_evidence_parser = independence_actions.add_parser(
        "run-evidence", help="Test a bounded number of conclusions against real evidence")
    run_evidence_parser.add_argument("--cycles", type=int, default=3, choices=range(1, 11))
    run_evidence_parser.add_argument("--web", action="store_true", help="Allow web search evidence")
    run_evidence_parser.add_argument("--experiments", action="store_true", help="Allow sandboxed code experiments")
    run_learning_parser = independence_actions.add_parser(
        "run-learning", help="Run a verified learning cycle: identify a weakness, propose and verify a fix, evaluate behaviorally")
    run_learning_parser.add_argument("--cycles", type=int, default=1, choices=range(1, 11))
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
        orchestrator = Orchestrator(BabyMindCoordinator().model_router, store,
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
    elif args.command == "self":
        import json
        from .selfmodel import SelfModel
        model = SelfModel()
        if args.self_action == "status":
            print(json.dumps(model.self_report(), indent=2, ensure_ascii=False))
        elif args.self_action == "dissent":
            entries = model.recent_dissent(20)
            if not entries:
                print("No disagreements recorded yet.")
            for item in entries:
                print(f"[{item['created_at']}] request: {item['request']}")
                print(f"  BabyMind's position: {item['disagreement']}")
        elif args.self_action == "introspections":
            entries = model.recent_introspections(20)
            if not entries:
                print("No self-critiques recorded yet.")
            for item in entries:
                print(f"[{item['created_at']}] {item['agent_id']} confidence={item['confidence']} "
                      f"revised={item['revised']}")
                print(f"  task: {item['task']}")
                if item["dissent"]:
                    print(f"  dissent: {item['dissent']}")
        elif args.self_action == "voice":
            print(f"voice mode: {model.set_voice_mode(args.mode)}")
        elif args.self_action == "believe":
            belief = model.add_belief(
                args.kind, args.claim,
                confidence=args.confidence, evidence=args.evidence, source="user",
            )
            print(f"recorded [{belief['kind']}] ({belief['confidence']:.2f}) {belief['claim']}")
    elif args.command == "autonomy":
        import json
        import time as _time
        from .autonomy import AutonomyEngine, autonomy_enabled
        engine = AutonomyEngine(BabyMindCoordinator().provider)
        if args.autonomy_action == "status":
            print(json.dumps(engine.status(), indent=2, ensure_ascii=False))
        elif args.autonomy_action == "audit":
            print(json.dumps({
                "entries": engine.audit_log(50),
                "chain": engine.verify_audit_chain(),
            }, indent=2, ensure_ascii=False))
        elif args.autonomy_action == "goals":
            for goal in engine.goals(None, limit=100):
                print(f"[{goal['status']:9}] p{goal['priority']} {goal['id'][:8]} {goal['title']}")
        elif args.autonomy_action == "goal":
            goal = engine.add_goal(args.title, args.description, priority=args.priority)
            print(f"Added goal {goal['id']}: {goal['title']}")
        elif args.autonomy_action == "reset":
            print(json.dumps(engine.reset(), indent=2, ensure_ascii=False))
        elif args.autonomy_action == "run":
            if not (autonomy_enabled() or args.confirm):
                raise SystemExit(
                    "Autonomy is armed deliberately. Set BABYMIND_AUTONOMY=1 or pass --confirm."
                )
            started = engine.start(cycles=args.cycles, interval=args.interval)
            if not started["started"]:
                raise SystemExit(started["reason"] or "Autonomy could not start.")
            print("Autonomy running. Press Ctrl-C to stop; every cycle is written to the audit log.")
            try:
                while engine.state == "running":
                    _time.sleep(0.5)
            except KeyboardInterrupt:
                engine.stop(reason="Interrupted from the command line.")
                print("\nStopped.")
            print(json.dumps(engine.status(), indent=2, ensure_ascii=False))
    elif args.command == "independence":
        import json
        from .independence import Independence
        independence = Independence()
        if args.independence_action == "status":
            print(json.dumps(independence.report(), indent=2, ensure_ascii=False))
        elif args.independence_action == "positions":
            entries = independence.positions.positions(None, limit=50)
            if not entries:
                print("No positions recorded yet.")
            for item in entries:
                print(f"[{item['status']:8}] ({item['confidence']:.2f}) {item['claim']}")
                if item["dissent_from"]:
                    print(f"  dissent from: {item['dissent_from']}")
        elif args.independence_action == "challenges":
            entries = independence.challenges.challenges(None, limit=50)
            if not entries:
                print("No challenges recorded yet.")
            for item in entries:
                mark = "resolved" if item["resolved"] else "open"
                print(f"[{item['kind']:8}] {mark:8} {item['challenge']}")
                print(f"  against: {item['target']}")
        elif args.independence_action == "hypotheses":
            entries = independence.explorations.hypotheses(None, limit=50)
            if not entries:
                print("No hypotheses recorded yet.")
            for item in entries:
                print(f"[{item['status']:10}] {item['hypothesis']}")
                if item["test_note"]:
                    print(f"  test note: {item['test_note']}")
        elif args.independence_action == "designs":
            entries = independence.designs.designs(None, None, limit=50)
            if not entries:
                print("No self-designs recorded yet.")
            for item in entries:
                print(f"[{item['status']:10}] {item['kind']}: {item['title']}")
                print(f"  {item['proposal'][:120]}")
        elif args.independence_action == "position":
            position = independence.positions.add_position(
                args.claim, args.reasoning,
                confidence=args.confidence, evidence=args.evidence,
                dissent_from=args.dissent_from,
            )
            print(f"recorded position ({position['confidence']:.2f}): {position['claim']}")
        elif args.independence_action == "challenge":
            record = independence.challenges.record_challenge(
                args.target, args.kind, args.challenge, confidence=args.confidence,
            )
            print(f"recorded [{record['kind']}] challenge: {record['challenge']}")
        elif args.independence_action == "hypothesis":
            record = independence.explorations.propose_hypothesis(
                args.text, args.why, confidence=args.confidence,
            )
            print(f"proposed hypothesis ({record['status']}): {record['hypothesis']}")
        elif args.independence_action == "design":
            record = independence.designs.propose_design(
                args.kind, args.title, args.proposal, args.rationale,
            )
            print(f"proposed design [{record['kind']}]: {record['title']}")
        elif args.independence_action == "curiosity":
            from .coordinator import BabyMindCoordinator
            report = independence.curiosity.run(
                BabyMindCoordinator().provider, cycles=args.cycles,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.independence_action == "evidence":
            report = independence.evidence.evidence_store.report()
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.independence_action == "learning":
            report = independence.learning.status()
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.independence_action == "test":
            from .coordinator import BabyMindCoordinator
            if args.kind == "position":
                result = independence.evidence.test_position(
                    BabyMindCoordinator().provider, args.target,
                    allow_web=args.web, allow_experiments=args.experiments,
                )
            else:
                result = independence.evidence.test_hypothesis(
                    BabyMindCoordinator().provider, args.target,
                    allow_web=args.web, allow_experiments=args.experiments,
                )
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.independence_action == "run-evidence":
            from .coordinator import BabyMindCoordinator
            report = independence.evidence.run(
                BabyMindCoordinator().provider, cycles=args.cycles,
                allow_web=args.web, allow_experiments=args.experiments,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
        elif args.independence_action == "run-learning":
            from .coordinator import BabyMindCoordinator
            coordinator = BabyMindCoordinator()
            report = independence.learning.run(
                coordinator.provider, cycles=args.cycles,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
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
