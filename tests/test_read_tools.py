import pytest

from cloudstack_agent.cloudstack.client import CloudStackClient, CloudStackConfig
from cloudstack_agent.tools import read


@pytest.fixture(autouse=True)
def mock_client():
    read.set_client(CloudStackClient(CloudStackConfig(mock=True)))
    yield
    read.set_client(None)


def test_list_zones():
    zones = read.list_zones()
    assert zones and zones[0]["name"] == "lab-zone"


def test_list_virtual_machines_filters_state():
    vms = read.list_virtual_machines(state="Stopped")
    assert [vm["name"] for vm in vms] == ["db-01"]


def test_host_utilisation_is_computed():
    hosts = read.list_hosts()
    kvm2 = next(h for h in hosts if h["name"] == "kvm2")
    assert kvm2["cpu_used_pct"] == 90.6
    assert kvm2["memory_used_pct"] == 62.5


def test_cloud_health_reports_system_vm_and_alert_issues():
    health = read.cloud_health()
    assert health["healthy"] is False
    assert health["system_vms"]["unhealthy"] == 1
    assert health["alerts"]["warning"] == 1
    assert any("consoleproxy" in issue.lower() for issue in health["issues"])
    assert any("storage pool near capacity" in issue.lower() for issue in health["issues"])


def test_health_is_clean_when_nothing_is_wrong():
    responses = {
        "listZones": {"listzonesresponse": {"zone": [{"id": "z", "name": "z1", "state": "Enabled"}]}},
        "listHosts": {"listhostsresponse": {"host": [{"id": "h", "name": "h1", "state": "Up"}]}},
        "listSystemVms": {
            "listsystemvmsresponse": {
                "systemvm": [
                    {"id": "s", "name": "s1", "state": "Running", "systemvmtype": "consoleproxy"}
                ]
            }
        },
        "listAlerts": {"listalertsresponse": {"alert": []}},
    }
    clean = CloudStackClient(CloudStackConfig(mock=True))
    clean.request = lambda command, **params: responses[command]
    read.set_client(clean)
    health = read.cloud_health()
    assert health["healthy"] is True
    assert health["issues"] == []
