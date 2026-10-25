import copy

import pytest

from referral.credentials import Issuer, verify_credential


@pytest.fixture
def issued(service, worker):
    return service.get_credential(worker[0])


def test_credential_verifies(service, issued):
    key = service.get_issuer_key()["jwk"]
    assert verify_credential(issued, key) == (True, "valid")
    assert service.verify_credential(issued)["valid"]


@pytest.mark.parametrize("path, value", [
    (("credentialSubject", "tier"), "trusted"),
    (("credentialSubject", "id"), "agt-someone-else"),
    (("credentialSubject", "notaryHead"), "0" * 64),
    (("validUntil",), "2099-01-01T00:00:00Z"),
    (("issuer", "id"), "not-referral"),
])
def test_any_change_breaks_the_signature(service, issued, path, value):
    forged = copy.deepcopy(issued)
    target = forged
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    ok, reason = verify_credential(forged, service.get_issuer_key()["jwk"])
    assert not ok and "signature" in reason


def test_other_issuer_key_is_rejected(issued):
    ok, _ = verify_credential(issued, Issuer().public_jwk)
    assert not ok


def test_expired_credential_is_rejected(service, issued):
    service.clock.advance(8 * 24 * 3600)
    assert service.verify_credential(issued) == {"valid": False, "reason": "credential has expired"}


def test_credential_has_no_raw_scores(issued):
    subject = issued["credentialSubject"]
    assert set(subject) == {"id", "name", "model", "domain", "tier", "evidence", "notaryHead"}
    assert all(isinstance(v, str) for v in subject.values())


def test_issuance_is_logged(service, issued):
    kinds = [e["kind"] for e in service.notary.entries()]
    assert "credential_issued" in kinds and service.verify_ledger()["ok"]
