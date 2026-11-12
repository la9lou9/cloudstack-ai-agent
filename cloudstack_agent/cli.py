"""Small CLI for demos and smoke tests.

    python -m cloudstack_agent.cli --check
    python -m cloudstack_agent.cli "which system VMs are unhealthy?"
"""
from __future__ import annotations

import argparse
import asyncio
import json

from .tools import read


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudStack AI agent")
    parser.add_argument("question", nargs="*", help="question for the agent")
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the cloud health summary directly (no LLM needed)",
    )
    parser.add_argument("--model", default=None, help="provider:model, e.g. openai:gpt-4o-mini")
    parser.add_argument("--thread", default="default", help="conversation thread id")
    args = parser.parse_args()

    if args.check:
        print(json.dumps(read.cloud_health(), indent=2))
        return

    if not args.question:
        parser.error("provide a question, or use --check")

    from .agent.graph import ask

    print(asyncio.run(ask(" ".join(args.question), thread_id=args.thread, model_name=args.model)))


if __name__ == "__main__":
    main()
