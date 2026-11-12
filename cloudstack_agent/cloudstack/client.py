"""Minimal CloudStack API client.

Deliberately stdlib-only (urllib + hmac). The tool layer must be testable
without installing an HTTP client, and the CloudStack API is a simple
signed-GET API. Mock mode returns fixed, realistic fixtures so the agent and
the MCP server can be demoed without a real cluster.

Signing note: this implements CloudStack's classic ("v2") request signature:
sort + URL-encode the parameters, lowercase the canonical string, HMAC-SHA1
with the secret key, base64. Newer clusters also accept signatureVersion=3;
that is intentionally not enabled here so the same client works against the
widest range of CloudStack versions.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class CloudStackError(RuntimeError):
    """A CloudStack API error response (errorresponse.errortext)."""


def _quote(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="")


def sign_params(params: dict[str, Any], secret_key: str) -> str:
    """Return the base64 CloudStack signature for a parameter dict."""
    canonical = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items()))
    digest = hmac.new(secret_key.encode("utf-8"), canonical.lower().encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


@dataclass(frozen=True)
class CloudStackConfig:
    url: str = ""
    api_key: str = ""
    secret_key: str = ""
    verify_tls: bool = True
    timeout: float = 30.0
    mock: bool = False
    allow_write: bool = False

    @property
    def endpoint(self) -> str:
        base = self.url.rstrip("/")
        return base if base.endswith("/client/api") else f"{base}/client/api"

    def require_credentials(self) -> None:
        if not (self.url and self.api_key and self.secret_key):
            raise CloudStackError(
                "CloudStack credentials are not configured "
                "(CLOUDSTACK_URL / CLOUDSTACK_API_KEY / CLOUDSTACK_SECRET_KEY)"
            )


class CloudStackClient:
    def __init__(self, config: CloudStackConfig):
        self.config = config

    def request(self, command: str, **params: Any) -> dict[str, Any]:
        if self.config.mock:
            return _mock_response(command, params)
        self.config.require_credentials()

        payload: dict[str, Any] = {
            "command": command,
            "response": "json",
            "apikey": self.config.api_key,
        }
        payload.update({k: v for k, v in params.items() if v is not None})
        payload["signature"] = sign_params(payload, self.config.secret_key)

        query = urllib.parse.urlencode(payload, quote_via=urllib.parse.quote, safe="")
        url = f"{self.config.endpoint}?{query}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})

        kwargs: dict[str, Any] = {"timeout": self.config.timeout}
        if url.startswith("https://"):
            context = ssl.create_default_context()
            if not self.config.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            kwargs["context"] = context

        try:
            with urllib.request.urlopen(request, **kwargs) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CloudStackError(f"CloudStack HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise CloudStackError(f"CloudStack unreachable: {exc.reason}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CloudStackError(f"CloudStack returned non-JSON: {body[:300]}") from exc

        if isinstance(data, dict) and "errorresponse" in data:
            error = data["errorresponse"] or {}
            raise CloudStackError(error.get("errortext") or error.get("errorcode") or "CloudStack API error")
        return data

    def list(self, command: str, response_key: str, item_key: str, **params: Any) -> list[dict[str, Any]]:
        """Return the list from a standard CloudStack list* response."""
        data = self.request(command, **params)
        section = data.get(response_key) or {}
        items = section.get(item_key) or []
        return items if isinstance(items, list) else [items]


# ─── Mock backend ────────────────────────────────────────────────────────────
# Fixed data that exercises the interesting states: a stopped system VM and a
# warning alert, so "what is unhealthy?" produces a useful demo answer.

_MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "listZones": {
        "listzonesresponse": {
            "count": 1,
            "zone": [
                {
                    "id": "zone-1",
                    "name": "lab-zone",
                    "state": "Enabled",
                    "type": "Core",
                    "networktype": "Advanced",
                    "allocationstate": "Enabled",
                }
            ],
        }
    },
    "listHosts": {
        "listhostsresponse": {
            "count": 3,
            "host": [
                {
                    "id": "host-1",
                    "name": "kvm1",
                    "state": "Up",
                    "resourcestate": "Enabled",
                    "type": "Routing",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "cputotal": 3200,
                    "cpuused": 1800,
                    "memorytotal": 17179869184,
                    "memoryused": 6442450944,
                },
                {
                    "id": "host-2",
                    "name": "kvm2",
                    "state": "Up",
                    "resourcestate": "Enabled",
                    "type": "Routing",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "cputotal": 3200,
                    "cpuused": 2900,
                    "memorytotal": 17179869184,
                    "memoryused": 10737418240,
                },
                {
                    "id": "host-3",
                    "name": "storage-server",
                    "state": "Up",
                    "resourcestate": "Enabled",
                    "type": "Storage",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                },
            ],
        }
    },
    "listVirtualMachines": {
        "listvirtualmachinesresponse": {
            "count": 2,
            "virtualmachine": [
                {
                    "id": "vm-1",
                    "name": "web-01",
                    "state": "Running",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "hostid": "host-1",
                    "templatename": "ubuntu-22.04",
                    "ipaddress": "10.200.243.100",
                    "cpunumber": 2,
                    "memory": 2048,
                    "instancename": "i-2-3-VM",
                },
                {
                    "id": "vm-2",
                    "name": "db-01",
                    "state": "Stopped",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "templatename": "ubuntu-22.04",
                    "cpunumber": 4,
                    "memory": 8192,
                    "instancename": "i-2-4-VM",
                },
            ],
        }
    },
    "listSystemVms": {
        "listsystemvmsresponse": {
            "count": 2,
            "systemvm": [
                {
                    "id": "sysvm-1",
                    "name": "s-1-VM",
                    "systemvmtype": "secondarystoragevm",
                    "state": "Running",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                },
                {
                    "id": "sysvm-2",
                    "name": "v-2-VM",
                    "systemvmtype": "consoleproxy",
                    "state": "Starting",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                },
            ],
        }
    },
    "listNetworks": {
        "listnetworksresponse": {
            "count": 2,
            "network": [
                {
                    "id": "net-1",
                    "name": "guest-default",
                    "type": "Isolated",
                    "state": "Implemented",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "cidr": "10.200.243.0/24",
                    "gateway": "10.200.243.1",
                },
                {
                    "id": "net-2",
                    "name": "shared-lab",
                    "type": "Shared",
                    "state": "Implemented",
                    "zoneid": "zone-1",
                    "zonename": "lab-zone",
                    "cidr": "10.200.240.0/22",
                    "gateway": "10.200.240.1",
                },
            ],
        }
    },
    "listAlerts": {
        "listalertsresponse": {
            "count": 1,
            "alert": [
                {
                    "id": "alert-1",
                    "description": "Storage pool near capacity on host-3",
                    "alerttype": 33,
                    "level": "WARNING",
                    "created": "2026-01-01T10:00:00+0000",
                    "state": "Active",
                }
            ],
        }
    },
    "listEvents": {
        "listeventsresponse": {
            "count": 3,
            "event": [
                {
                    "id": "evt-1",
                    "description": "VM web-01 started",
                    "level": "INFO",
                    "state": "Completed",
                    "created": "2026-01-01T10:05:00+0000",
                },
                {
                    "id": "evt-2",
                    "description": "VM db-01 stopped by admin",
                    "level": "INFO",
                    "state": "Completed",
                    "created": "2026-01-01T10:06:00+0000",
                },
                {
                    "id": "evt-3",
                    "description": "Console proxy VM failed to start",
                    "level": "WARN",
                    "state": "Completed",
                    "created": "2026-01-01T10:07:00+0000",
                },
            ],
        }
    },
    "listTemplates": {
        "listtemplatesresponse": {
            "count": 2,
            "template": [
                {"id": "tpl-1", "name": "ubuntu-22.04", "format": "QCOW2", "hypervisor": "KVM", "isready": True, "ostypename": "Ubuntu 22.04"},
                {"id": "tpl-2", "name": "rocky-9", "format": "QCOW2", "hypervisor": "KVM", "isready": True, "ostypename": "Rocky Linux 9"},
            ],
        }
    },
    "listServiceOfferings": {
        "listserviceofferingsresponse": {
            "count": 2,
            "serviceoffering": [
                {"id": "off-1", "name": "Small Instance", "cpunumber": 2, "memory": 2048},
                {"id": "off-2", "name": "Large Instance", "cpunumber": 4, "memory": 8192},
            ],
        }
    },
    "listVolumes": {
        "listvolumesresponse": {
            "count": 2,
            "volume": [
                {"id": "vol-1", "name": "ROOT-1", "type": "ROOT", "state": "Ready", "size": 21474836480, "virtualmachineid": "vm-1"},
                {"id": "vol-2", "name": "ROOT-2", "type": "ROOT", "state": "Ready", "size": 21474836480, "virtualmachineid": "vm-2"},
            ],
        }
    },
    # Async CloudStack commands return a job id; these keep write-mode demos
    # runnable without a real cluster.
    "startVirtualMachine": {"startvirtualmachineresponse": {"jobid": "job-start-1"}},
    "stopVirtualMachine": {"stopvirtualmachineresponse": {"jobid": "job-stop-1"}},
    "rebootVirtualMachine": {"rebootvirtualmachineresponse": {"jobid": "job-reboot-1"}},
}


def _filter_items(items: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    ignored = {"command", "response", "apikey", "signature", "page", "pagesize"}
    result = items
    for key, value in params.items():
        if key in ignored or value is None:
            continue
        if key == "keyword":
            needle = str(value).lower()
            result = [item for item in result if needle in json.dumps(item).lower()]
        else:
            result = [item for item in result if str(item.get(key, "")).lower() == str(value).lower()]
    return result


def _mock_response(command: str, params: dict[str, Any]) -> dict[str, Any]:
    template = _MOCK_RESPONSES.get(command)
    if template is None:
        # Unknown command: behave like a successful empty response instead of
        # inventing data, so a missing mock is obvious rather than misleading.
        return {}
    data = copy.deepcopy(template)
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for item_key, items in list(section.items()):
            if isinstance(items, list):
                filtered = _filter_items(items, params)
                section[item_key] = filtered
                if "count" in section:
                    section["count"] = len(filtered)
    return data
