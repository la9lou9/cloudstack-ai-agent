"""Read-only CloudStack tools.

Every function returns compact, JSON-serialisable dicts — not the full
CloudStack payloads. That keeps the LLM's context small and stable, and makes
the tool contract easy to test without an LLM.
"""
from __future__ import annotations

from typing import Any

from ..cloudstack.client import CloudStackClient, CloudStackConfig
from ..config import load_settings

_client: CloudStackClient | None = None


def build_client() -> CloudStackClient:
    settings = load_settings()
    return CloudStackClient(
        CloudStackConfig(
            url=settings.url,
            api_key=settings.api_key,
            secret_key=settings.secret_key,
            verify_tls=settings.verify_tls,
            timeout=settings.timeout,
            mock=settings.mock,
            allow_write=settings.allow_write,
        )
    )


def get_client() -> CloudStackClient:
    global _client
    if _client is None:
        _client = build_client()
    return _client


def set_client(client: CloudStackClient | None) -> None:
    """Test/dependency-injection hook."""
    global _client
    _client = client


def _pick(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item.get(field) for field in fields if item.get(field) is not None}


def _pct(used: Any, total: Any) -> float | None:
    try:
        used_f, total_f = float(used), float(total)
        if total_f <= 0:
            return None
        return round(used_f / total_f * 100, 1)
    except (TypeError, ValueError):
        return None


def list_zones() -> list[dict[str, Any]]:
    """List CloudStack zones with their state and network type."""
    items = get_client().list("listZones", "listzonesresponse", "zone")
    return [
        _pick(z, ("id", "name", "state", "type", "networktype", "allocationstate"))
        for z in items
    ]


def list_hosts(zone_id: str | None = None) -> list[dict[str, Any]]:
    """List hosts (hypervisors and storage) with CPU/memory utilisation."""
    items = get_client().list("listHosts", "listhostsresponse", "host", zoneid=zone_id)
    hosts: list[dict[str, Any]] = []
    for h in items:
        row = _pick(h, ("id", "name", "state", "resourcestate", "type", "zoneid", "zonename"))
        cpu_pct = _pct(h.get("cpuused"), h.get("cputotal"))
        mem_pct = _pct(h.get("memoryused"), h.get("memorytotal"))
        if cpu_pct is not None:
            row["cpu_used_pct"] = cpu_pct
        if mem_pct is not None:
            row["memory_used_pct"] = mem_pct
        hosts.append(row)
    return hosts


def list_virtual_machines(
    state: str | None = None,
    name: str | None = None,
    zone_id: str | None = None,
) -> list[dict[str, Any]]:
    """List user virtual machines, optionally filtered by state/name/zone."""
    items = get_client().list(
        "listVirtualMachines",
        "listvirtualmachinesresponse",
        "virtualmachine",
        state=state,
        name=name,
        zoneid=zone_id,
    )
    return [
        _pick(vm, ("id", "name", "state", "zoneid", "zonename", "hostid", "templatename", "ipaddress", "cpunumber", "memory", "instancename"))
        for vm in items
    ]


def get_virtual_machine(vm_id: str) -> dict[str, Any] | None:
    """Fetch one VM by id (None if it does not exist)."""
    items = get_client().list(
        "listVirtualMachines", "listvirtualmachinesresponse", "virtualmachine", id=vm_id
    )
    return _pick(items[0], ("id", "name", "state", "zoneid", "zonename", "hostid", "templatename", "ipaddress", "cpunumber", "memory")) if items else None


def list_system_vms(state: str | None = None) -> list[dict[str, Any]]:
    """List CloudStack system VMs (SSVM, console proxy, router)."""
    items = get_client().list(
        "listSystemVms", "listsystemvmsresponse", "systemvm", state=state
    )
    return [_pick(vm, ("id", "name", "systemvmtype", "state", "zoneid", "zonename")) for vm in items]


def list_networks(zone_id: str | None = None) -> list[dict[str, Any]]:
    """List guest networks with their CIDR and gateway."""
    items = get_client().list("listNetworks", "listnetworksresponse", "network", zoneid=zone_id)
    return [_pick(n, ("id", "name", "type", "state", "zoneid", "zonename", "cidr", "gateway")) for n in items]


def list_alerts(level: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List active CloudStack alerts, newest first, optionally by level."""
    items = get_client().list(
        "listAlerts", "listalertsresponse", "alert", level=level, pagesize=limit
    )
    return [_pick(a, ("id", "description", "alerttype", "level", "created", "state")) for a in items]


def list_events(level: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List recent CloudStack events, optionally filtered by level."""
    items = get_client().list(
        "listEvents", "listeventsresponse", "event", level=level, pagesize=limit
    )
    return [_pick(e, ("id", "description", "level", "state", "created")) for e in items]


def list_templates(hypervisor: str = "KVM") -> list[dict[str, Any]]:
    """List ready templates for a hypervisor."""
    items = get_client().list(
        "listTemplates", "listtemplatesresponse", "template", hypervisor=hypervisor
    )
    return [_pick(t, ("id", "name", "format", "hypervisor", "isready", "ostypename")) for t in items]


def list_service_offerings() -> list[dict[str, Any]]:
    """List compute service offerings (CPU/RAM profiles)."""
    items = get_client().list(
        "listServiceOfferings", "listserviceofferingsresponse", "serviceoffering"
    )
    return [_pick(o, ("id", "name", "cpunumber", "memory")) for o in items]


def list_volumes() -> list[dict[str, Any]]:
    """List volumes with their state, size and attached VM."""
    items = get_client().list("listVolumes", "listvolumesresponse", "volume")
    return [_pick(v, ("id", "name", "type", "state", "size", "virtualmachineid")) for v in items]


def cloud_health() -> dict[str, Any]:
    """One-call health summary: hosts, system VMs, alerts and capacity.

    This is the tool the agent should reach for first on vague questions
    like "is my cloud healthy?" — it is cheap and avoids dumping every raw
    object into the model's context.
    """
    zones = list_zones()
    hosts = list_hosts()
    system_vms = list_system_vms()
    alerts = list_alerts(limit=50)

    down_hosts = [h["name"] for h in hosts if str(h.get("state", "")).lower() != "up"]
    unhealthy_system_vms = [
        vm for vm in system_vms if str(vm.get("state", "")).lower() != "running"
    ]
    warning_alerts = [a for a in alerts if str(a.get("level", "")).upper() == "WARNING"]
    critical_alerts = [a for a in alerts if str(a.get("level", "")).upper() == "CRITICAL"]

    issues: list[str] = []
    if down_hosts:
        issues.append(f"{len(down_hosts)} host(s) not Up: {', '.join(down_hosts)}")
    for vm in unhealthy_system_vms:
        issues.append(
            f"System VM {vm.get('name')} ({vm.get('systemvmtype')}) is {vm.get('state')}, not Running"
        )
    for alert in alerts:
        issues.append(f"{alert.get('level')} alert: {alert.get('description')}")
    for host in hosts:
        cpu = host.get("cpu_used_pct")
        mem = host.get("memory_used_pct")
        if cpu is not None and cpu >= 90:
            issues.append(f"Host {host.get('name')} CPU at {cpu}%")
        if mem is not None and mem >= 90:
            issues.append(f"Host {host.get('name')} memory at {mem}%")

    return {
        "healthy": not issues,
        "zones": {"total": len(zones), "names": [z.get("name") for z in zones]},
        "hosts": {"total": len(hosts), "down": len(down_hosts)},
        "system_vms": {
            "total": len(system_vms),
            "unhealthy": len(unhealthy_system_vms),
        },
        "alerts": {
            "total": len(alerts),
            "warning": len(warning_alerts),
            "critical": len(critical_alerts),
        },
        "issues": issues,
    }
