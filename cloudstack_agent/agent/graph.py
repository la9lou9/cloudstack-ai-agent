"""LangGraph agent over the CloudStack MCP server.

The graph is deliberately the standard tool-calling loop:

    START → agent ─┬─(tool calls)─→ tools → agent
                   └─(final answer)─→ END

The agent never talks to CloudStack directly. It only sees the MCP tools, so
the safety policy (read-only by default, write tools opt-in, confirm=true) is
enforced one layer down, in the MCP server — not in the prompt.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = """You are a CloudStack operations assistant.

Rules:
- Use the provided tools to inspect the cloud. Never invent hosts, VMs, IDs,
  IPs or alert text.
- For a vague question like "is the cloud healthy?", call cloud_health first,
  then drill down with the specific list tools.
- When you report a problem, include the concrete object name and id, and
  the evidence (state, alert level, utilisation) that supports it.
- If a write tool is available, explain the change first and only call it
  with confirm=true after the user explicitly agrees. Never batch destructive
  actions.
- If a tool returns an error, report it plainly instead of guessing.
- Keep answers short and operational.
"""

_graph: Any | None = None
_graph_lock = asyncio.Lock()


def _mcp_server_config() -> dict[str, Any]:
    # Ensure the spawned MCP server can import this package regardless of the
    # caller's current working directory.
    project_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return {
        "command": sys.executable,
        "args": ["-m", "cloudstack_agent.mcp_server"],
        "transport": "stdio",
        "env": env,
    }


async def build_graph(model_name: str | None = None) -> Any:
    """Build the LangGraph graph and load tools from the MCP server."""
    try:
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import SystemMessage
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import START, MessagesState, StateGraph
        from langgraph.prebuilt import ToolNode, tools_condition
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise SystemExit(
            "The agent needs the LangGraph/LangChain extras. Install them with:\n"
            "    pip install -r requirements.txt\n"
            "and install the provider package for your model (e.g. langchain-openai)."
        ) from exc

    mcp_client = MultiServerMCPClient({"cloudstack": _mcp_server_config()})
    tool_list = await mcp_client.get_tools()

    model = init_chat_model(
        model_name or os.environ.get("CLOUDSTACK_AGENT_MODEL", "openai:gpt-4o-mini")
    )
    model_with_tools = model.bind_tools(tool_list)

    async def call_model(state: MessagesState) -> dict[str, Any]:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tool_list))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=MemorySaver())


async def _get_graph(model_name: str | None = None) -> Any:
    global _graph
    if _graph is None:
        async with _graph_lock:
            if _graph is None:
                _graph = await build_graph(model_name)
    return _graph


async def ask(question: str, thread_id: str = "default", model_name: str | None = None) -> str:
    """Ask the agent a question and return its final text answer."""
    from langchain_core.messages import HumanMessage

    graph = await _get_graph(model_name)
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config,
    )
    content = result["messages"][-1].content
    if isinstance(content, str):
        return content
    # Some providers return a list of content blocks.
    parts = [block.get("text", "") for block in content if isinstance(block, dict)]
    return "\n".join(part for part in parts if part)
