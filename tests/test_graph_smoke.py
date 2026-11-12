"""Optional smoke test for the LangGraph wiring.

Skipped automatically when the agent extras are not installed, so the core
suite still passes with only pytest + the stdlib.
"""
import asyncio
import os

import pytest

pytest.importorskip("langchain_mcp_adapters")
pytest.importorskip("langgraph")
pytest.importorskip("langchain")
pytest.importorskip("langchain_openai")


def test_graph_builds_and_loads_mcp_tools():
    # init_chat_model needs a provider key, but building the graph does not
    # make any network call. A dummy value is enough for this smoke test.
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")

    from cloudstack_agent.agent.graph import build_graph

    graph = asyncio.run(build_graph("openai:gpt-4o-mini"))
    nodes = set(graph.get_graph().nodes)
    assert {"agent", "tools"} <= nodes
