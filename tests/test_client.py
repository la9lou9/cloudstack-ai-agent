import base64
import hashlib
import hmac

from cloudstack_agent.cloudstack.client import (
    CloudStackClient,
    CloudStackConfig,
    CloudStackError,
    sign_params,
)


def test_signature_matches_documented_v2_algorithm():
    params = {"command": "listZones", "response": "json", "apikey": "key"}
    # Independent construction of the canonical string, lowercased exactly as
    # the CloudStack server does before hashing.
    canonical = "apikey=key&command=listZones&response=json".lower()
    expected = base64.b64encode(
        hmac.new(b"secret", canonical.encode(), hashlib.sha1).digest()
    ).decode()
    assert sign_params(params, "secret") == expected


def test_signature_depends_on_secret():
    params = {"command": "listZones", "apikey": "key"}
    assert sign_params(params, "one") != sign_params(params, "two")


def test_parameter_order_does_not_change_signature():
    a = {"command": "listZones", "apikey": "key", "response": "json"}
    b = {"response": "json", "apikey": "key", "command": "listZones"}
    assert sign_params(a, "secret") == sign_params(b, "secret")


def test_real_mode_requires_credentials():
    client = CloudStackClient(CloudStackConfig(mock=False))
    try:
        client.request("listZones")
    except CloudStackError as exc:
        assert "credentials are not configured" in str(exc)
    else:  # pragma: no cover - should never happen
        raise AssertionError("expected CloudStackError")


def test_mock_mode_returns_fixtures_and_filters():
    client = CloudStackClient(CloudStackConfig(mock=True))

    zones = client.list("listZones", "listzonesresponse", "zone")
    assert [z["name"] for z in zones] == ["lab-zone"]

    stopped = client.list(
        "listVirtualMachines", "listvirtualmachinesresponse", "virtualmachine", state="Stopped"
    )
    assert [vm["name"] for vm in stopped] == ["db-01"]


def test_mock_mode_returns_job_id_for_async_writes():
    client = CloudStackClient(CloudStackConfig(mock=True))
    data = client.request("stopVirtualMachine", id="vm-1")
    assert data["stopvirtualmachineresponse"]["jobid"] == "job-stop-1"
