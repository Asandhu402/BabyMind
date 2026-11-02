"""Command-line entry point for BabyMind."""

import argparse

from .runtime import BabyMindRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="babymind", description="BabyMind 50-agent foundation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="Check runtime and agent registry")
    subparsers.add_parser("list", help="List all registered agents")
    run_parser = subparsers.add_parser("run", help="Route a task to one agent")
    run_parser.add_argument("agent_id", help="Agent ID, for example BM-01")
    run_parser.add_argument("task", help="Task text")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    runtime = BabyMindRuntime()
    if args.command == "health":
        for key, value in runtime.health().items():
            print(f"{key}: {value}")
    elif args.command == "list":
        for agent in runtime.agents:
            print(f"{agent.agent_id}  {agent.name} [{agent.domain}] — {agent.purpose}")
    elif args.command == "run":
        try:
            result = runtime.run(args.agent_id, args.task)
        except (KeyError, ValueError) as error:
            raise SystemExit(str(error)) from error
        print(f"agent: {result.agent_id} ({result.agent_name})")
        print(f"status: {result.status}")
        print(f"task: {result.task}")
        print(result.message)


if __name__ == "__main__":
    main()
