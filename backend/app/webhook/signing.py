"""Webhook request signing (HMAC-SHA256), Stripe-style.

The sender signs f"{timestamp}.{raw body}" with the shared secret and sends:
    X-CDP-Timestamp: <unix seconds>
    X-CDP-Signature: sha256=<hex digest>
"""

import hashlib
import hmac
import time

TIMESTAMP_HEADER = "X-CDP-Timestamp"
SIGNATURE_HEADER = "X-CDP-Signature"


class SignatureError(Exception):
    pass


def sign(body: bytes, secret: str, timestamp: int | None = None) -> dict[str, str]:
    """Headers a sender attaches to a webhook request."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: f"sha256={digest}"}


def verify(body: bytes, timestamp: str | None, signature: str | None, secrets: list[str], tolerance_seconds: int) -> None:
    """Raise SignatureError unless the signature matches one of `secrets` and the timestamp is fresh."""
    if not secrets:
        raise SignatureError("Webhook secret is not configured")
    if not timestamp or not signature:
        raise SignatureError("Missing signature headers")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise SignatureError("Invalid timestamp header") from exc
    if abs(time.time() - sent_at) > tolerance_seconds:
        raise SignatureError("Timestamp outside the allowed window (possible replay)")

    provided = signature.removeprefix("sha256=")
    for secret in secrets:  # more than one during a secret rotation
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, provided):
            return
    raise SignatureError("Signature does not match")
