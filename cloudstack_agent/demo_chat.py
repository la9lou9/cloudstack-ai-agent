"""Rule-based demo replies used by the chat UI when no LLM is configured.

This is deliberately small and deterministic: it lets the web interface be
demoed with the built-in mock backend before any API key is involved. The real
agent (LangGraph) is used automatically when a provider key is present.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import drift as drift_tools
from .tools import read

EXAMPLE_CONTRACT = Path(__file__).resolve().parents[1] / "examples" / "deployment.yaml"


def _format_health(health: dict[str, Any]) -> str:
    hosts = health["hosts"]
    system_vms = health["system_vms"]
    alerts = health["alerts"]
    zones = health["zones"]
    lines = [
        "**Cloud health**",
        f"- Zones: {zones['total']} ({', '.join(zones['names']) or 'none'})",
        f"- Hosts: {hosts['total']} total, {hosts['down']} down",
        f"- System VMs: {system_vms['total']} total, {system_vms['unhealthy']} unhealthy",
        f"- Alerts: {alerts['total']} total ({alerts['warning']} warning, {alerts['critical']} critical)",
    ]
    if health["issues"]:
        lines.append("")
        lines.append("**Issues**")
        lines.extend(f"- {issue}" for issue in health["issues"])
    else:
        lines.append("")
        lines.append("No issues detected.")
    return "\n".join(lines)


def _format_drift(report: dict[str, Any]) -> str:
    scope = report["scope"]
    summary = report["summary"]
    lines = [
        f"**Drift check — {scope.get('deploymentId')}**",
        f"Zone `{scope.get('zoneName')}` (`{scope.get('zoneId')}`), "
        f"{summary['checks']} checks, {summary['errors']} error(s), {summary['warnings']} warning(s)",
        "",
    ]
    if report["ok"]:
        lines.append("No drift detected: the live zone matches the contract.")
    else:
        lines.append("**Findings**")
        for finding in report["findings"]:
            icon = "✘" if finding["severity"] == "error" else "▲"
            lines.append(f"- {icon} **{finding['kind']}** — {finding['message']}")
    return "\n".join(lines)


def _format_vms(vms: list[dict[str, Any]]) -> str:
    if not vms:
        return "No VMs match that state."
    lines = [f"**{len(vms)} VM(s)**"]
    for vm in vms:
        lines.append(
            f"- `{vm.get('name')}` — {vm.get('state')} "
            f"(id `{vm.get('id')}`, zone {vm.get('zonename') or vm.get('zoneid')})"
        )
    return "\n".join(lines)


def _format_system_vms(vms: list[dict[str, Any]]) -> str:
    if not vms:
        return "No system VMs found."
    lines = ["**System VMs**"]
    for vm in vms:
        state = vm.get("state")
        icon = "✔" if str(state).lower() == "running" else "✘"
        lines.append(f"- {icon} `{vm.get('name')}` ({vm.get('systemvmtype')}) — {state}")
    return "\n".join(lines)


def _format_hosts(hosts: list[dict[str, Any]]) -> str:
    if not hosts:
        return "No hosts found."
    lines = ["**Hosts**"]
    for host in hosts:
        cpu = host.get("cpu_used_pct")
        mem = host.get("memory_used_pct")
        extras = []
        if cpu is not None:
            extras.append(f"CPU {cpu}%")
        if mem is not None:
            extras.append(f"RAM {mem}%")
        suffix = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"- `{host.get('name')}` — {host.get('state')}, {host.get('type')}{suffix}")
    return "\n".join(lines)


def _format_alerts(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return "No active alerts."
    lines = [f"**{len(alerts)} active alert(s)**"]
    for alert in alerts:
        lines.append(f"- {alert.get('level')}: {alert.get('description')} (`{alert.get('id')}`)")
    return "\n".join(lines)


def reply(message: str) -> dict[str, Any]:
    """Return a deterministic demo answer plus the tools that produced it."""
    text = message.lower()

    if any(word in text for word in ("drift", "contract", "contrat", "dérive", "derive", "écart", "ecart")):
        try:
            report = drift_tools.detect_drift_from_path(EXAMPLE_CONTRACT)
        except Exception as exc:  # noqa: BLE001 - surface a readable demo error
            return {
                "answer": f"I could not run the drift check: {exc}",
                "mode": "demo",
                "tools_used": ["drift_report"],
            }
        return {"answer": _format_drift(report), "mode": "demo", "tools_used": ["drift_report"]}

    if any(word in text for word in ("health", "healthy", "status", "état", "etat", "santé", "sante", "forme")):
        return {"answer": _format_health(read.cloud_health()), "mode": "demo", "tools_used": ["cloud_health"]}

    if any(word in text for word in ("stopped", "stopped vm", "arrêt", "arret", "arrêtée", "arretee", "éteint", "eteint")):
        vms = read.list_virtual_machines(state="Stopped")
        return {"answer": _format_vms(vms), "mode": "demo", "tools_used": ["list_virtual_machines"]}

    if "system" in text or "système" in text or "systeme" in text or "ssvm" in text or "console" in text:
        return {
            "answer": _format_system_vms(read.list_system_vms()),
            "mode": "demo",
            "tools_used": ["list_system_vms"],
        }

    if any(word in text for word in ("host", "hôte", "hote", "cpu", "mémoire", "memoire", "ram")):
        return {"answer": _format_hosts(read.list_hosts()), "mode": "demo", "tools_used": ["list_hosts"]}

    if any(word in text for word in ("alert", "alerte", "warning", "problème", "probleme")):
        return {"answer": _format_alerts(read.list_alerts()), "mode": "demo", "tools_used": ["list_alerts"]}

    if any(word in text for word in ("vm", "vms", "machine", "instance", "virtual")):
        return {
            "answer": _format_vms(read.list_virtual_machines()),
            "mode": "demo",
            "tools_used": ["list_virtual_machines"],
        }

    return {
        "answer": "I can inspect the cloud for you. Here is the current summary:\n\n"
        + _format_health(read.cloud_health()),
        "mode": "demo",
        "tools_used": ["cloud_health"],
    }
