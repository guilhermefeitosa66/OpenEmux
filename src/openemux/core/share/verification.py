"""The six-digit code both screens show before a transfer (commit-reveal).

The sender commits to its nonce before it sees the receiver's, so a man in
the middle relaying the offer cannot pick values until the codes collide: it
gets one 1-in-a-million guess per offer. ``docs/share-protocol.md`` explains
the derivation; ``tests/data/share_vectors.json`` pins it for both apps.
"""

import hashlib
import hmac
import os

COMMIT_LABEL = b"openemux-share-v1/commit"
CODE_LABEL = b"openemux-share-v1/code"
NONCE_BYTES = 32


def new_nonce():
    return os.urandom(NONCE_BYTES)


def commit(nonce):
    """``hex(SHA-256(label || nonce))``."""
    return hashlib.sha256(COMMIT_LABEL + nonce).hexdigest()


def check_commit(commitment, nonce):
    """Whether ``nonce`` is what ``commitment`` committed to (constant time)."""
    if not isinstance(commitment, str) or not isinstance(nonce, bytes):
        return False
    return hmac.compare_digest(commit(nonce), commitment.lower())


def code(fp_sender, fp_receiver, nonce_sender, nonce_receiver):
    """The code as six digits, zero-padded.

    The fingerprints are the lowercase hex strings; their 32 raw bytes go into
    the digest. The sender passes the fingerprint it observed in TLS as the
    receiver's.
    """
    digest = hashlib.sha256(
        CODE_LABEL
        + bytes.fromhex(fp_sender)
        + bytes.fromhex(fp_receiver)
        + nonce_sender
        + nonce_receiver
    ).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def format_code(value):
    """``"123456"`` shown as ``"123 456"``."""
    return f"{value[:3]} {value[3:]}"
