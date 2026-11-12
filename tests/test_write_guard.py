import pytest

from cloudstack_agent.cloudstack.client import CloudStackClient, CloudStackConfig
from cloudstack_agent.tools import read, write


def _use(allow_write: bool):
    read.set_client(CloudStackClient(CloudStackConfig(mock=True, allow_write=allow_write)))


@pytest.fixture(autouse=True)
def reset():
    yield
    read.set_client(None)


def test_write_disabled_by_default():
    _use(allow_write=False)
    result = write.stop_virtual_machine("vm-1", confirm=True)
    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_write_requires_confirmation():
    _use(allow_write=True)
    result = write.stop_virtual_machine("vm-1", confirm=False)
    assert result["status"] == "confirmation_required"
    assert result["target"] == "vm-1"


def test_confirmed_write_runs():
    _use(allow_write=True)
    result = write.stop_virtual_machine("vm-1", confirm=True)
    assert result["ok"] is True
    assert result["job_id"] == "job-stop-1"
