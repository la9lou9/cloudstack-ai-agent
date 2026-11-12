"""Small web chat UI for the CloudStack agent.

FastAPI + a static HTML/CSS/JS page. No frontend build step.

- Works immediately in demo mode (rule-based answers + mock data), with no
  LLM key and no CloudStack cluster.
- Switches to the real LangGraph agent automatically when a provider API key
  is present (or force it with CLOUDSTACK_AGENT_USE_LLM=always).
- Read-only: the write tools are not exposed here unless the MCP server was
  started with CLOUDSTACK_AGENT_ALLOW_WRITE=true, and even then they need
  confirm=true.

Run:
    python -m cloudstack_agent.web
    # http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import demo_chat
from . import drift as drift_tools
from .config import load_settings
from .tools import read

STATIC_DIR = Path(__file__).resolve().parent / "web_static"
EXAMPLE_CONTRACT = Path(__file__).resolve().parents[1] / "examples" / "deployment.yaml"

app = FastAPI(title="CloudStack AI Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


def _llm_enabled() -> bool:
    mode = os.environ.get("CLOUDSTACK_AGENT_USE_LLM", "auto").strip().lower()
    if mode in {"0", "false", "no", "off", "never"}:
        return False
    if mode in {"1", "true", "yes", "on", "always"}:
        return True
    # auto: use the agent only when a common provider key is present.
    return any(
        os.environ.get(key)
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GROQ_API_KEY",
            "MISTRAL_API_KEY",
        )
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config() -> dict[str, Any]:
    settings = load_settings()
    return {
        "mock": settings.mock,
        "llm": _llm_enabled(),
        "allow_write": settings.allow_write,
        "model": os.environ.get("CLOUDSTACK_AGENT_MODEL", "openai:gpt-4o-mini"),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    return read.cloud_health()


@app.get("/api/drift")
def drift(contract: str | None = None) -> dict[str, Any]:
    path = contract or str(EXAMPLE_CONTRACT)
    try:
        return drift_tools.detect_drift_from_path(path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    if _llm_enabled():
        try:
            from .agent.graph import ask

            answer = await ask(message, thread_id=request.thread_id)
            return {"answer": answer, "mode": "agent", "tools_used": []}
        except Exception as exc:  # noqa: BLE001 - a demo must never 500 on a missing provider
            result = demo_chat.reply(message)
            result["note"] = (
                f"LLM unavailable ({type(exc).__name__}: {exc}). "
                "Falling back to demo mode."
            )
            return result

    return demo_chat.reply(message)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CloudStack AI Agent web UI")
    parser.add_argument("--host", default=os.environ.get("CLOUDSTACK_AGENT_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLOUDSTACK_AGENT_WEB_PORT", "8080")))
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("The web UI needs FastAPI + uvicorn. Run: pip install -r requirements.txt") from exc

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
