"""Signed track-record credentials that third parties can verify on their own.

Referral acts as an attestation issuer: a registry such as ERC-8004 or a NANDA
AgentFacts record can carry a Referral credential instead of open, farmable ratings.
The layout follows the W3C Verifiable Credential shape that AgentFacts documents
are signed as (issuer, validFrom/validUntil, credentialSubject, proof), but the proof
is our own simple scheme, not a conforming Data Integrity cryptosuite: an Ed25519
signature over the credential's canonical JSON (sorted keys, no whitespace) with
the `proof` field removed.

A credential carries a tier and an evidence label, never raw scores.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .notary import canonical

CREDENTIAL_TYPE = "ReferralTrackRecordCredential"
PROOF_TYPE = "ReferralEd25519Signature"
CRYPTOSUITE = "ed25519-canonical-json-v0"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def iso(ts: float) -> str:
    """Whole seconds, rounded down, so a credential is valid the moment it is issued."""
    return datetime.fromtimestamp(int(ts), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class Issuer:
    def __init__(self, issuer_id: str = "referral", private_key: Ed25519PrivateKey | None = None):
        self.issuer_id = issuer_id
        self._key = private_key or Ed25519PrivateKey.generate()
        raw = self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.kid = f"{issuer_id}#key-{hashlib.sha256(raw).hexdigest()[:16]}"
        self.public_jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw), "kid": self.kid}

    def issue(self, subject: dict, valid_from: float, ttl_seconds: float) -> dict:
        credential = {
            "type": ["VerifiableCredential", CREDENTIAL_TYPE],
            "issuer": {"id": self.issuer_id},
            "validFrom": iso(valid_from),
            "validUntil": iso(valid_from + ttl_seconds),
            "credentialSubject": subject,
        }
        signature = self._key.sign(canonical(credential).encode())
        credential["proof"] = {"type": PROOF_TYPE, "cryptosuite": CRYPTOSUITE,
                               "verificationMethod": self.kid, "proofValue": _b64u(signature)}
        return credential


def verify_credential(credential: dict, public_jwk: dict, now: float | None = None) -> tuple[bool, str]:
    """Check the signature (and, with `now`, the validity window). Returns (ok, reason)."""
    proof = credential.get("proof")
    if not isinstance(proof, dict) or proof.get("type") != PROOF_TYPE:
        return False, "missing or unknown proof"
    if proof.get("verificationMethod") != public_jwk.get("kid"):
        return False, "signed with a different key"
    unsigned = {k: v for k, v in credential.items() if k != "proof"}
    try:
        key = Ed25519PublicKey.from_public_bytes(_b64u_decode(public_jwk["x"]))
        key.verify(_b64u_decode(proof["proofValue"]), canonical(unsigned).encode())
    except (InvalidSignature, ValueError, KeyError):
        return False, "signature does not match the credential"
    if now is not None:
        if now < _parse_iso(credential["validFrom"]):
            return False, "credential is not valid yet"
        if now > _parse_iso(credential["validUntil"]):
            return False, "credential has expired"
    return True, "valid"
