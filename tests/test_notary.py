import sqlite3

import pytest

from referral.notary import Notary, Store


def make_notary():
    store = Store()
    keys = {"alice": "k-alice", "bob": "k-bob"}
    return store, Notary(store, keys.__getitem__)


def test_chain_verifies_and_links_entries():
    store, notary = make_notary()
    a = notary.append("contract", "alice", {"x": 1}, "job-1", 1.0)
    b = notary.append("prediction", "bob", {"p": 0.6}, "job-1", 2.0)
    assert b["prev_hash"] == a["hash"]
    assert notary.verify_chain() == (True, [])
    assert [e["kind"] for e in notary.entries("job-1")] == ["contract", "prediction"]


def test_log_is_append_only():
    store, notary = make_notary()
    notary.append("contract", "alice", {"x": 1}, "job-1", 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE notary_log SET payload = '{}'")
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("DELETE FROM notary_log")


def test_tampering_is_detected():
    store, notary = make_notary()
    notary.append("prediction", "bob", {"p": 0.6}, "job-1", 1.0)
    notary.append("verdict", "alice", {"status": "failed"}, "job-1", 2.0)
    store.db.execute("DROP TRIGGER notary_no_update")
    store.db.execute("UPDATE notary_log SET payload = '{\"status\":\"passed\"}' WHERE kind = 'verdict'")
    ok, problems = notary.verify_chain()
    assert not ok
    assert "contents changed" in problems[0]


def test_forged_signature_is_detected():
    store, notary = make_notary()
    notary.append("prediction", "bob", {"p": 0.6}, "job-1", 1.0)
    store.db.execute("DROP TRIGGER notary_no_update")
    store.db.execute("UPDATE notary_log SET sig = 'forged'")
    ok, problems = notary.verify_chain()
    assert not ok and "bad signature" in problems[0]
