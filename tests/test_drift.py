import copy

import pytest

from cloudstack_agent.cloudstack.client import CloudStackClient, CloudStackConfig
from cloudstack_agent.drift import detect_drift, format_report, load_contract
from cloudstack_agent.tools import read


def _clean_client() -> CloudStackClient:
    """Mock client with healthy system VMs (the default mock has one Starting)."""
    client = CloudStackClient(CloudStackConfig(mock=True))
    original = client.list

    def patched(command, response_key, item_key, **params):
        items = original(command, response_key, item_key, **params)
        if command == "listSystemVms":
            items = [{**vm, "state": "Running"} for vm in items]
        return items

    client.list = patched  # type: ignore[method-assign]
    return client


def _contract() -> dict:
    return load_contract("examples/deployment.yaml")


@pytest.fixture(autouse=True)
def reset_client():
    yield
    read.set_client(None)


def test_no_drift_when_contract_matches_cloudstack():
    read.set_client(_clean_client())
    report = detect_drift(_contract())
    assert report["ok"] is True
    assert report["summary"]["errors"] == 0
    assert report["scope"]["zoneId"] == "zone-1"


def test_missing_host_is_an_error():
    read.set_client(_clean_client())
    contract = _contract()
    contract["hosts"].append(
        {"name": "kvm9", "role": "hypervisor", "ip": "10.200.243.199", "sshUser": "root", "bridgeSlaveIface": "eth0"}
    )
    report = detect_drift(contract)
    assert report["ok"] is False
    assert any(f["kind"] == "host_missing" for f in report["findings"])


def test_unhealthy_system_vm_is_an_error():
    read.set_client(CloudStackClient(CloudStackConfig(mock=True)))
    report = detect_drift(_contract())
    assert any(f["kind"] == "system_vm_not_running" for f in report["findings"])


def test_public_vlan_mismatch_is_an_error():
    read.set_client(_clean_client())
    contract = _contract()
    contract["network"]["publicVlanTag"] = 200
    report = detect_drift(contract)
    assert any(f["kind"] == "public_vlan_mismatch" for f in report["findings"])


def test_missing_zone_is_reported_without_guessing():
    read.set_client(_clean_client())
    contract = _contract()
    contract["cloudstack"]["zoneName"] = "other-zone"
    report = detect_drift(contract)
    assert report["ok"] is False
    assert [f["kind"] for f in report["findings"]] == ["zone_missing"]


def test_changed_ip_range_is_an_error():
    read.set_client(_clean_client())
    contract = _contract()
    contract["cloudstack"]["ipRanges"]["guest"]["endIp"] = "10.200.243.99"
    report = detect_drift(contract)
    assert any(f["kind"] == "ip_range_missing" for f in report["findings"])


def test_every_resource_query_is_scoped_to_the_contract_zone():
    client = _clean_client()
    seen: list[tuple[str, str | None]] = []
    original = client.list

    def recording(command, response_key, item_key, **params):
        seen.append((command, params.get("zoneid")))
        return original(command, response_key, item_key, **params)

    client.list = recording  # type: ignore[method-assign]
    read.set_client(client)
    detect_drift(_contract())

    scoped = [(command, zone) for command, zone in seen if command != "listZones"]
    assert scoped, "expected resource queries"
    assert all(zone == "zone-1" for _, zone in scoped), scoped


def test_text_report_is_human_readable():
    read.set_client(CloudStackClient(CloudStackConfig(mock=True)))
    text = format_report(detect_drift(_contract()))
    assert "DRIFT DETECTED" in text
    assert "system_vm_not_running" in text
