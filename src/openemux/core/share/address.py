"""The manual address and the QR payload: ``openemux-share://host:port#fp``.

What a user types when discovery cannot see the other device, and what the
QR code encodes. Parsing accepts the full URI, ``host``, ``host:port`` and
``[v6]:port``; the fingerprint, when present, pins the certificate.
"""

from collections import namedtuple

from openemux.core.share.protocol import SERVER_PORT, ErrorCode, ShareError, is_hex

SCHEME = "openemux-share://"

Address = namedtuple("Address", "host port fp")


def build(host, port=SERVER_PORT, fp=None):
    shown = f"[{host}]" if ":" in host else host
    uri = f"{SCHEME}{shown}:{port}"
    return f"{uri}#{fp}" if fp else uri


def _bad(text):
    return ShareError(ErrorCode.BAD_REQUEST, f"not an address: {text!r}")


def parse(text):
    """An :class:`Address`; ``ShareError(bad_request)`` when ``text`` is not one."""
    if not isinstance(text, str):
        raise _bad(text)
    rest = text.strip()
    if rest.lower().startswith(SCHEME):
        rest = rest[len(SCHEME):]
    rest, _, fp = rest.partition("#")
    fp = fp.replace(" ", "").replace(":", "").lower() or None
    if fp is not None and not is_hex(fp, 64):
        raise _bad(text)
    host, port = _split_host_port(rest.rstrip("/"), text)
    if not host or any(ch.isspace() or ch in "/?@[]" for ch in host):
        raise _bad(text)
    return Address(host, port, fp)


def _split_host_port(rest, text):
    if rest.startswith("["):
        host, bracket, after = rest[1:].partition("]")
        if not bracket or (after and not after.startswith(":")):
            raise _bad(text)
        return host, _port(after[1:], text) if after else SERVER_PORT
    if rest.count(":") == 1:
        host, _, port = rest.partition(":")
        return host, _port(port, text)
    # A bare host, or a bare IPv6 literal -- no port can be told apart from it.
    return rest, SERVER_PORT


def _port(value, text):
    if not value.isdigit() or not 0 < int(value) < 65536:
        raise _bad(text)
    return int(value)
