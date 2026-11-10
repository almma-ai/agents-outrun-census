"""
Signed charter attestations (format charter-attestation/0).

An attestation says: this charter file (by SHA-256) scored this, by this
scorer, and the holder of this Ed25519 key, on behalf of this accountable
person, says so. It is made on the owner's machine by `census sign`; the
charter and any code stay there. almma-ai/charter-registry imports verify()
from this module, so signing and checking cannot drift apart.

Signature: Ed25519 over the canonical JSON of every field except "signature"
(keys sorted, no spaces, UTF-8).
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import __version__
from .charter import SCORER_ID, charter_hash, score_charter

FORMAT = "charter-attestation/0"
KEY_DIR = Path(os.environ.get("CHARTER_KEY_DIR", Path.home() / ".config" / "charter-registry" / "keys"))


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def public_key_str(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "ed25519:" + base64.b64encode(raw).decode()


def parse_public_key(s: str) -> Ed25519PublicKey:
    if not isinstance(s, str) or not s.startswith("ed25519:"):
        raise ValueError("public key must look like ed25519:<base64>")
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(s.split(":", 1)[1], validate=True))


def default_key_path(slug: str) -> Path:
    return KEY_DIR / f"{slug}.pem"


def generate_key(path: Path) -> str:
    """Write a new private key (0600) and return its public key string."""
    if path.exists():
        raise FileExistsError(f"{path} already exists; it is your registry key, keep it")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return public_key_str(key.public_key())


def load_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 key")
    return key


def _pillar_results(scored: dict) -> list[dict]:
    return [{k: p[k] for k in ("n", "key", "points", "max", "result")} for p in scored["pillars"]]


def build(charter_raw: bytes, product: dict, key: Ed25519PrivateKey, now: datetime | None = None) -> dict:
    """Score the charter and return a signed attestation."""
    charter = json.loads(charter_raw)
    scored = score_charter(charter)
    ap = product.get("accountable_person") or {}
    att = {
        "format": FORMAT,
        "product_slug": product["product_slug"],
        "charter_spec": charter.get("spec"),
        "charter_id": charter.get("id"),
        "charter_version": charter.get("version"),
        "charter_hash": charter_hash(charter_raw),
        "charter_score": scored["charter_score"],
        "pillar_results": _pillar_results(scored),
        "scorer": {"id": SCORER_ID, "package": "agents-outrun-census", "version": __version__},
        "accountable_person": {"name": ap.get("name"), "role": ap.get("role")},
        "signed_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_key": public_key_str(key.public_key()),
    }
    att["signature"] = base64.b64encode(key.sign(canonical(att))).decode()
    return att


def verify(att: dict, charter_raw: bytes, expected_public_key: str | None = None) -> list[str]:
    """Return every problem found; an empty list means the attestation holds."""
    errs: list[str] = []
    if att.get("format") != FORMAT:
        errs.append(f"format is {att.get('format')!r}, expected {FORMAT!r}")
    body = {k: v for k, v in att.items() if k != "signature"}
    try:
        pub = parse_public_key(att.get("public_key"))
        pub.verify(base64.b64decode(att.get("signature") or "", validate=True), canonical(body))
    except InvalidSignature:
        errs.append("signature does not match the attestation (was it edited after signing?)")
    except Exception as e:  # malformed key or signature
        errs.append(f"signature or public key unreadable: {e}")
    if expected_public_key and att.get("public_key") != expected_public_key:
        errs.append("signed with a different key from the one registered for this product")
    if att.get("charter_hash") != charter_hash(charter_raw):
        errs.append("charter_hash does not match charter.json (re-run census sign after any change)")
    try:
        charter = json.loads(charter_raw)
    except ValueError as e:
        return errs + [f"charter.json is not JSON: {e}"]
    scored = score_charter(charter)
    if (att.get("scorer") or {}).get("id") != SCORER_ID:
        errs.append(f"scored by {(att.get('scorer') or {}).get('id')!r}; the registry uses {SCORER_ID!r}: upgrade census and re-sign")
    if att.get("charter_score") != scored["charter_score"]:
        errs.append(f"charter_score {att.get('charter_score')} does not match the recomputed {scored['charter_score']}")
    if att.get("pillar_results") != _pillar_results(scored):
        errs.append("pillar_results do not match the recomputed results")
    for k, field in (("charter_spec", "spec"), ("charter_id", "id"), ("charter_version", "version")):
        if att.get(k) != charter.get(field):
            errs.append(f"{k} does not match charter.json")
    ap = att.get("accountable_person") or {}
    if not ap.get("name") or not ap.get("role"):
        errs.append("accountable_person needs a name and a role")
    return errs
