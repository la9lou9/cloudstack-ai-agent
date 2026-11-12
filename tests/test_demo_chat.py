import pytest

from cloudstack_agent import demo_chat
from cloudstack_agent.cloudstack.client import CloudStackClient, CloudStackConfig
from cloudstack_agent.tools import read


@pytest.fixture(autouse=True)
def mock_client():
    read.set_client(CloudStackClient(CloudStackConfig(mock=True)))
    yield
    read.set_client(None)


def test_health_question_uses_cloud_health():
    result = demo_chat.reply("is my cloud healthy?")
    assert result["mode"] == "demo"
    assert result["tools_used"] == ["cloud_health"]
    assert "Cloud health" in result["answer"]
    assert "consoleproxy" in result["answer"]


def test_drift_question_uses_drift_report():
    result = demo_chat.reply("show the drift against the deployment contract")
    assert result["tools_used"] == ["drift_report"]
    assert "Drift check" in result["answer"]
    assert "system_vm_not_running" in result["answer"]


def test_stopped_vm_question_filters_vms():
    result = demo_chat.reply("which VMs are stopped?")
    assert result["tools_used"] == ["list_virtual_machines"]
    assert "db-01" in result["answer"]
    assert "web-01" not in result["answer"]


def test_system_vm_question():
    result = demo_chat.reply("how are the system VMs?")
    assert result["tools_used"] == ["list_system_vms"]
    assert "v-2-VM" in result["answer"]


def test_host_question_includes_utilisation():
    result = demo_chat.reply("which hosts are close to full?")
    assert result["tools_used"] == ["list_hosts"]
    assert "kvm2" in result["answer"]
    assert "CPU 90.6%" in result["answer"]


def test_alert_question():
    result = demo_chat.reply("show me the alerts")
    assert result["tools_used"] == ["list_alerts"]
    assert "Storage pool near capacity" in result["answer"]


def test_french_health_question():
    result = demo_chat.reply("est-ce que le cloud est en bonne santé ?")
    assert result["tools_used"] == ["cloud_health"]


def test_unknown_question_falls_back_to_health_summary():
    result = demo_chat.reply("hello there")
    assert result["tools_used"] == ["cloud_health"]
    assert "Cloud health" in result["answer"]
