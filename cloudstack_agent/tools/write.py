"""Write tools — disabled unless CLOUDSTACK_AGENT_ALLOW_WRITE=true.

Even when enabled, every call must pass confirm=true. This gives the agent a
single, auditable safety gate: it can *propose* an action, but a human (or a
deliberate second call) has to confirm it. The MCP server only registers
these tools when the setting is enabled, so a read-only deployment cannot
even see them.
"""
from __future__ import annotations

from typing import Any

from .read import get_client


def _guard(confirm: bool, action: str, target: str) -> dict[str, Any] | None:
    client = get_client()
    if not client.config.allow_write:
        return {
            "ok": False,
            "error": "write tools are disabled",
            "hint": "Set CLOUDSTACK_AGENT_ALLOW_WRITE=true to enable them.",
        }
    if not confirm:
        return {
            "ok": True,
            "status": "confirmation_required",
            "action": action,
            "target": target,
            "message": f"Re-run with confirm=true to {action} {target}.",
        }
    return None


def _job_id(data: dict[str, Any], response_key: str) -> str | None:
    return (data.get(response_key) or {}).get("jobid")


def start_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
    """Start a stopped VM. Requires confirm=true and write tools enabled."""
    blocked = _guard(confirm, "start", vm_id)
    if blocked:
        return blocked
    data = get_client().request("startVirtualMachine", id=vm_id)
    return {"ok": True, "action": "start", "vm_id": vm_id, "job_id": _job_id(data, "startvirtualmachineresponse")}


def stop_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
    """Stop a running VM. Requires confirm=true and write tools enabled."""
    blocked = _guard(confirm, "stop", vm_id)
    if blocked:
        return blocked
    data = get_client().request("stopVirtualMachine", id=vm_id)
    return {"ok": True, "action": "stop", "vm_id": vm_id, "job_id": _job_id(data, "stopvirtualmachineresponse")}


def reboot_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
    """Reboot a VM. Requires confirm=true and write tools enabled."""
    blocked = _guard(confirm, "reboot", vm_id)
    if blocked:
        return blocked
    data = get_client().request("rebootVirtualMachine", id=vm_id)
    return {"ok": True, "action": "reboot", "vm_id": vm_id, "job_id": _job_id(data, "rebootvirtualmachineresponse")}
