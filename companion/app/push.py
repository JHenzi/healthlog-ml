"""Web push, sealed here and delivered by the courier (reminders; privacy.md, R5).

The Companion never sends anything itself. For each reminder and subscribed phone it encrypts the message end to
end (RFC 8291, ``aes128gcm``) and signs a VAPID token (RFC 8292), then writes the result as one JSON file to the
outbox on a shared volume. The courier (``collector deliver``), which has network access but no database and no
health data, posts each file to the phone's push service and writes the status back to ``results/``. The push
service sees only that a message went to a subscription, never what it says.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import http_ece
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

# The push services phones and browsers use: Apple (iOS Home Screen apps, Safari), Google, Mozilla, Microsoft.
# A subscription to any other host is refused, so the courier can't be pointed somewhere else (SSRF).
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")
PUSH_HOST_SUFFIXES = (".notify.windows.com", ".push.apple.com")
TTL_SECONDS = 4 * 3600  # a reminder still worth showing a few hours late, not the next day
TOKEN_SECONDS = 12 * 3600
OUTBOX, RESULTS = "outbox", "results"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def endpoint_allowed(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str  # the browser's public key, base64url
    auth: str  # its auth secret, base64url


def valid_subscription(sub: Subscription) -> bool:
    try:
        return endpoint_allowed(sub.endpoint) and len(unb64url(sub.p256dh)) == 65 and len(unb64url(sub.auth)) == 16
    except ValueError:
        return False


# --- VAPID ------------------------------------------------------------------------


def generate_keys() -> tuple[str, str]:
    """A new VAPID key pair: (public, private), base64url, for ``.env``."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64url(public), b64url(private)


def _private_key(private_b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(unb64url(private_b64), "big"), ec.SECP256R1())


def vapid_header(endpoint: str, public_b64: str, private_b64: str, subject: str, now: dt.datetime) -> str:
    """``Authorization: vapid t=<ES256 JWT>, k=<public key>`` for this push service (RFC 8292)."""
    parsed = urlparse(endpoint)
    claims = {"aud": f"{parsed.scheme}://{parsed.netloc}", "exp": int(now.timestamp()) + TOKEN_SECONDS, "sub": subject}
    signing_input = (
        b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    der = _private_key(private_b64).sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = signing_input + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={public_b64}"


# --- sealing --------------------------------------------------------------------


def encrypt(payload: bytes, sub: Subscription) -> bytes:
    """End-to-end encryption to the phone's key (RFC 8291): only the phone can read it."""
    return http_ece.encrypt(
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=unb64url(sub.p256dh),
        auth_secret=unb64url(sub.auth),
        version="aes128gcm",
    )


def seal(message: dict, sub: Subscription, public_b64: str, private_b64: str, subject: str, now: dt.datetime) -> dict:
    """One outbox entry: where to post, the headers, and the encrypted body (base64)."""
    return {
        "id": uuid.uuid4().hex,
        "endpoint": sub.endpoint,
        "created": now.isoformat(timespec="seconds"),
        "headers": {
            "Authorization": vapid_header(sub.endpoint, public_b64, private_b64, subject, now),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SECONDS),
            "Urgency": "normal",
        },
        "body": base64.b64encode(encrypt(json.dumps(message).encode(), sub)).decode(),
    }


def write_outbox(push_dir: Path, entry: dict) -> Path:
    """Atomically, so the courier never reads half a file."""
    folder = push_dir / OUTBOX
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{entry['id']}.tmp"
    tmp.write_text(json.dumps(entry))
    final = folder / f"{entry['id']}.json"
    os.replace(tmp, final)
    return final


@dataclass(frozen=True)
class Result:
    endpoint: str
    status: int  # the push service's HTTP status; 0 when it couldn't be reached


def take_results(push_dir: Path) -> list[Result]:
    """The courier's reports, removed once read."""
    out = []
    folder = push_dir / RESULTS
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            out.append(Result(str(data["endpoint"]), int(data["status"])))
        except (ValueError, KeyError, TypeError):
            pass
        path.unlink(missing_ok=True)
    return out


def gone(status: int) -> bool:
    """The push service says the subscription no longer exists: forget it."""
    return status in (404, 410)
