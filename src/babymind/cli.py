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
