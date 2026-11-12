"""Drift detector: compare a deployment contract with the live CloudStack state.

This is the "desired vs actual" reconciler, not a metrics system. It is
read-only: it never creates, changes or deletes anything.

Scope matters: a contract names one tenant, one deployment and one CloudStack
zone. Every query below is filtered by that zone's id (and resources are
matched by name/IP inside it), so two clients with similarly named zones or
hosts cannot be confused.

Usage:
    python -m cloudstack_agent.drift --contract deployment.yaml
    python -m cloudstack_agent.drift --contract deployment.yaml --json
Exit code: 0 = no drift, 1 = drift detected, 2 = usage/contract error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .tools.read import get_client


def _norm(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def _get(data: dict[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _finding(severity: str, kind: str, message: str, expected: Any = None, actual: Any = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"severity": severity, "kind": kind, "message": message}
    if expected is not None:
        finding["expected"] = expected
    if actual is not None:
        finding["actual"] = actual
    return finding


def _host_matches(actual: dict[str, Any], desired: dict[str, Any]) -> bool:
    actual_values = {_norm(actual.get("name")), _norm(actual.get("ipaddress"))} - {""}
    desired_values = {_norm(desired.get("name")), _norm(desired.get("ip"))} - {""}
    return bool(actual_values & desired_values)


def _report(contract: dict[str, Any], zone_id: str | None, checks: int, findings: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    return {
        "ok": not errors,
        "scope": {
            "tenantId": _get(contract, "tenantId"),
            "deploymentId": _get(contract, "deploymentId"),
            "zoneName": _get(contract, "cloudstack", "zoneName"),
            "zoneId": zone_id,
        },
        "summary": {
            "checks": checks,
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "findings": findings,
    }


def detect_drift(contract: dict[str, Any], client=None, zone_id: str | None = None) -> dict[str, Any]:
    """Compare one contract with one zone. Returns a JSON-serialisable report."""
    client = client or get_client()
    findings: list[dict[str, Any]] = []
    checks = 0

    zone_name = _get(contract, "cloudstack", "zoneName")
    if not zone_name:
        findings.append(_finding("error", "contract_invalid", "cloudstack.zoneName is missing from the contract"))
        return _report(contract, zone_id, checks, findings)

    # ── Resolve the one zone this contract owns ─────────────────────────────
    zones = client.list("listZones", "listzonesresponse", "zone")
    checks += 1
    matches = [z for z in zones if _norm(z.get("name")) == _norm(zone_name)]
    if not matches:
        findings.append(
            _finding(
                "error",
                "zone_missing",
                f"zone '{zone_name}' from the contract does not exist",
                expected=zone_name,
                actual=[z.get("name") for z in zones],
            )
        )
        return _report(contract, zone_id, checks, findings)
    if len(matches) > 1:
        findings.append(
            _finding(
                "error",
                "zone_ambiguous",
                f"more than one zone is named '{zone_name}'; refusing to guess",
                expected=zone_name,
                actual=[z.get("id") for z in matches],
            )
        )
        return _report(contract, zone_id, checks, findings)

    zone = matches[0]
    resolved_zone_id = zone_id or zone.get("id")
    scope = {"zoneid": resolved_zone_id}

    checks += 1
    if _norm(zone.get("state")) != "enabled":
        findings.append(
            _finding("error", "zone_not_enabled", f"zone '{zone_name}' is {zone.get('state')}, not Enabled")
        )

    expected_network_type = _get(contract, "cloudstack", "networkType", default="Advanced")
    checks += 1
    if zone.get("networktype") and _norm(zone.get("networktype")) != _norm(expected_network_type):
        findings.append(
            _finding(
                "warning",
                "zone_network_type",
                f"zone '{zone_name}' is {zone.get('networktype')}, contract says {expected_network_type}",
                expected=expected_network_type,
                actual=zone.get("networktype"),
            )
        )

    # ── Pod and cluster ─────────────────────────────────────────────────────
    pod_name = _get(contract, "cloudstack", "podName")
    pods = client.list("listPods", "listpodsresponse", "pod", **scope)
    checks += 1
    if not any(_norm(p.get("name")) == _norm(pod_name) for p in pods):
        findings.append(
            _finding(
                "error",
                "pod_missing",
                f"pod '{pod_name}' from the contract does not exist in zone '{zone_name}'",
                expected=pod_name,
                actual=[p.get("name") for p in pods],
            )
        )

    cluster_name = _get(contract, "cloudstack", "clusterName")
    clusters = client.list("listClusters", "listclustersresponse", "cluster", **scope)
    checks += 1
    if not any(_norm(c.get("name")) == _norm(cluster_name) for c in clusters):
        findings.append(
            _finding(
                "error",
                "cluster_missing",
                f"cluster '{cluster_name}' from the contract does not exist in zone '{zone_name}'",
                expected=cluster_name,
                actual=[c.get("name") for c in clusters],
            )
        )

    # ── Hosts ───────────────────────────────────────────────────────────────
    desired_hosts = contract.get("hosts") or []
    actual_hosts = client.list("listHosts", "listhostsresponse", "host", **scope)
    for desired in desired_hosts:
        checks += 1
        match = next((h for h in actual_hosts if _host_matches(h, desired)), None)
        if match is None:
            findings.append(
                _finding(
                    "error",
                    "host_missing",
                    f"host '{desired.get('name')}' ({desired.get('ip')}) from the contract was not found in zone '{zone_name}'",
                    expected={"name": desired.get("name"), "ip": desired.get("ip")},
                    actual=[h.get("name") for h in actual_hosts],
                )
            )
            continue
        if _norm(match.get("state")) != "up":
            findings.append(
                _finding(
                    "error",
                    "host_not_up",
                    f"host '{match.get('name')}' is {match.get('state')}, not Up",
                    expected="Up",
                    actual=match.get("state"),
                )
            )
        if match.get("resourcestate") and _norm(match.get("resourcestate")) != "enabled":
            findings.append(
                _finding(
                    "warning",
                    "host_disabled",
                    f"host '{match.get('name')}' resource state is {match.get('resourcestate')}",
                    expected="Enabled",
                    actual=match.get("resourcestate"),
                )
            )

    for actual in actual_hosts:
        if not any(_host_matches(actual, desired) for desired in desired_hosts):
            findings.append(
                _finding(
                    "warning",
                    "host_unexpected",
                    f"host '{actual.get('name')}' exists in zone '{zone_name}' but is not in the contract",
                    actual=actual.get("name"),
                )
            )

    # ── System VMs ──────────────────────────────────────────────────────────
    system_vms = client.list("listSystemVms", "listsystemvmsresponse", "systemvm", **scope)
    checks += 1
    if not system_vms:
        findings.append(_finding("warning", "no_system_vms", f"no system VMs found in zone '{zone_name}'"))
    for vm in system_vms:
        if _norm(vm.get("state")) != "running":
            findings.append(
                _finding(
                    "error",
                    "system_vm_not_running",
                    f"system VM '{vm.get('name')}' ({vm.get('systemvmtype')}) is {vm.get('state')}, not Running",
                    expected="Running",
                    actual=vm.get("state"),
                )
            )

    # ── IP ranges ───────────────────────────────────────────────────────────
    desired_ranges = _get(contract, "cloudstack", "ipRanges", default={}) or {}
    actual_ranges = client.list("listVlanIpRanges", "listvlaniprangesresponse", "vlaniprange", **scope)
    for label, desired in desired_ranges.items():
        checks += 1
        match = next(
            (
                r
                for r in actual_ranges
                if _norm(r.get("startip")) == _norm(desired.get("startIp"))
                and _norm(r.get("endip")) == _norm(desired.get("endIp"))
            ),
            None,
        )
        if match is None:
            findings.append(
                _finding(
                    "error",
                    "ip_range_missing",
                    f"ipRanges.{label} ({desired.get('startIp')}–{desired.get('endIp')}) from the contract was not found in zone '{zone_name}'",
                    expected={"startIp": desired.get("startIp"), "endIp": desired.get("endIp")},
                    actual=[{"startIp": r.get("startip"), "endIp": r.get("endip")} for r in actual_ranges],
                )
            )
            continue
        if label == "public":
            expected_vlan = _get(contract, "network", "publicVlanTag")
            if expected_vlan is not None:
                actual_vlan = match.get("vlan") or "untagged"
                if _norm(actual_vlan) != _norm(expected_vlan):
                    findings.append(
                        _finding(
                            "error",
                            "public_vlan_mismatch",
                            f"public IP range is on VLAN {actual_vlan}, contract says {expected_vlan}",
                            expected=expected_vlan,
                            actual=actual_vlan,
                        )
                    )

    for actual in actual_ranges:
        if not any(
            _norm(actual.get("startip")) == _norm(d.get("startIp"))
            and _norm(actual.get("endip")) == _norm(d.get("endIp"))
            for d in desired_ranges.values()
        ):
            findings.append(
                _finding(
                    "warning",
                    "ip_range_unexpected",
                    f"IP range {actual.get('startip')}–{actual.get('endip')} exists but is not in the contract",
                )
            )

    # ── Storage ─────────────────────────────────────────────────────────────
    storage = contract.get("storage") or {}
    pools = client.list("listStoragePools", "liststoragepoolsresponse", "storagepool", **scope)
    for field, default in (("nfsPrimaryPath", "/export/primary"), ("nfsSecondaryPath", "/export/secondary")):
        checks += 1
        expected_path = storage.get(field, default)
        if not any(_norm(p.get("path")) == _norm(expected_path) for p in pools):
            findings.append(
                _finding(
                    "error",
                    "storage_pool_missing",
                    f"storage.{field} '{expected_path}' was not found on any storage pool",
                    expected=expected_path,
                    actual=[p.get("path") for p in pools],
                )
            )

    expected_paths = {
        _norm(storage.get("nfsPrimaryPath", "/export/primary")),
        _norm(storage.get("nfsSecondaryPath", "/export/secondary")),
    }
    for pool in pools:
        if _norm(pool.get("path")) not in expected_paths:
            findings.append(
                _finding(
                    "warning",
                    "storage_pool_unexpected",
                    f"storage pool '{pool.get('path')}' exists but is not in the contract",
                )
            )

    # ── CloudStack version ──────────────────────────────────────────────────
    expected_version = _get(contract, "cloudstack", "version")
    capabilities = client.request("listCapabilities").get("listcapabilitiesresponse") or {}
    actual_version = capabilities.get("cloudstackversion")
    checks += 1
    if expected_version and actual_version and not _norm(actual_version).startswith(_norm(expected_version)):
        findings.append(
            _finding(
                "warning",
                "cloudstack_version_mismatch",
                f"CloudStack is {actual_version}, contract says {expected_version}",
                expected=expected_version,
                actual=actual_version,
            )
        )

    return _report(contract, resolved_zone_id, checks, findings)


def load_contract(path: str | os.PathLike) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise SystemExit("Reading a contract needs PyYAML. Install it with: pip install PyYAML") from exc

    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def _check_contract_path(path: str | os.PathLike) -> Path:
    resolved = Path(path).resolve()
    allowed_root = os.environ.get("CLOUDSTACK_AGENT_CONTRACT_DIR")
    if allowed_root:
        root = Path(allowed_root).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"contract path must stay inside {root}")
    return resolved


def detect_drift_from_path(path: str | os.PathLike, zone_id: str | None = None) -> dict[str, Any]:
    contract = load_contract(_check_contract_path(path))
    return detect_drift(contract, zone_id=zone_id)


def format_report(report: dict[str, Any]) -> str:
    scope = report["scope"]
    summary = report["summary"]
    status = "DRIFT DETECTED" if not report["ok"] else "NO DRIFT"
    lines = [
        f"{status} — {scope.get('tenantId')} / {scope.get('deploymentId')} "
        f"(zone {scope.get('zoneName')}, id {scope.get('zoneId')})",
        f"{summary['checks']} checks, {summary['errors']} error(s), {summary['warnings']} warning(s)",
    ]
    for finding in report["findings"]:
        icon = "✘" if finding["severity"] == "error" else "▲"
        lines.append(f"  {icon} {finding['kind']}: {finding['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a deployment contract with CloudStack")
    parser.add_argument("--contract", required=True, help="path to deployment.yaml")
    parser.add_argument("--zone-id", default=None, help="override the resolved CloudStack zone id")
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    args = parser.parse_args(argv)

    try:
        report = detect_drift_from_path(args.contract, zone_id=args.zone_id)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
