"""CloudStack MCP server.

Exposes the typed tool layer over the Model Context Protocol. Any MCP client
(Claude Desktop, Cursor, the LangGraph agent in this repo, ...) can call these
tools. Read tools are always available; write tools are only registered when
CLOUDSTACK_AGENT_ALLOW_WRITE=true, and each one still requires confirm=true.

Run with:
    python -m cloudstack_agent.mcp_server
"""
from __future__ import annotations

from typing import Any

from . import tools
from .config import load_settings

try:
    # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ImportError:  # pragma: no cover - depends on the installed SDK major
    try:
        # MCP Python SDK 2.x renamed FastMCP to MCPServer; the decorator and
        # run() API used below are the same.
        from mcp.server.mcpserver import MCPServer as _MCPServer
    except ImportError as exc:
        raise SystemExit(
            "The MCP server needs the 'mcp' package. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from exc


mcp = _MCPServer("cloudstack")


@mcp.tool()
def list_zones() -> list[dict[str, Any]]:
    """List CloudStack zones with state and network type."""
    return tools.read.list_zones()


@mcp.tool()
def list_hosts(zone_id: str | None = None) -> list[dict[str, Any]]:
    """List hosts (hypervisors/storage) with CPU and memory utilisation."""
    return tools.read.list_hosts(zone_id=zone_id)


@mcp.tool()
def list_virtual_machines(
    state: str | None = None,
    name: str | None = None,
    zone_id: str | None = None,
) -> list[dict[str, Any]]:
    """List user VMs, optionally filtered by state, name or zone id."""
    return tools.read.list_virtual_machines(state=state, name=name, zone_id=zone_id)


@mcp.tool()
def get_virtual_machine(vm_id: str) -> dict[str, Any] | None:
    """Fetch one VM by its CloudStack id."""
    return tools.read.get_virtual_machine(vm_id)


@mcp.tool()
def list_system_vms(state: str | None = None) -> list[dict[str, Any]]:
    """List CloudStack system VMs (SSVM, console proxy, virtual router)."""
    return tools.read.list_system_vms(state=state)


@mcp.tool()
def list_networks(zone_id: str | None = None) -> list[dict[str, Any]]:
    """List guest networks with CIDR and gateway."""
    return tools.read.list_networks(zone_id=zone_id)


@mcp.tool()
def list_alerts(level: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List active alerts, optionally filtered by level (WARNING/CRITICAL)."""
    return tools.read.list_alerts(level=level, limit=limit)


@mcp.tool()
def list_events(level: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List recent CloudStack events, optionally filtered by level."""
    return tools.read.list_events(level=level, limit=limit)


@mcp.tool()
def list_templates(hypervisor: str = "KVM") -> list[dict[str, Any]]:
    """List templates available for a hypervisor."""
    return tools.read.list_templates(hypervisor=hypervisor)


@mcp.tool()
def list_service_offerings() -> list[dict[str, Any]]:
    """List compute service offerings (CPU/RAM profiles)."""
    return tools.read.list_service_offerings()


@mcp.tool()
def list_volumes() -> list[dict[str, Any]]:
    """List volumes with state, size and attached VM."""
    return tools.read.list_volumes()


@mcp.tool()
def cloud_health() -> dict[str, Any]:
    """Summarise cloud health: hosts, system VMs, alerts and capacity issues."""
    return tools.read.cloud_health()


def _register_write_tools() -> None:
    """Register write tools only when the operator opted in."""
    if not load_settings().allow_write:
        return

    @mcp.tool()
    def start_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
        """Start a stopped VM. Requires confirm=true."""
        return tools.write.start_virtual_machine(vm_id, confirm=confirm)

    @mcp.tool()
    def stop_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
        """Stop a running VM. Requires confirm=true."""
        return tools.write.stop_virtual_machine(vm_id, confirm=confirm)

    @mcp.tool()
    def reboot_virtual_machine(vm_id: str, confirm: bool = False) -> dict[str, Any]:
        """Reboot a VM. Requires confirm=true."""
        return tools.write.reboot_virtual_machine(vm_id, confirm=confirm)


_register_write_tools()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
