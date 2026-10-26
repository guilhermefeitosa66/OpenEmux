"""OpenEmux Share Protocol v1: constants, errors and validators of the wire.

Pure -- no sockets, no threads. Everything here parses data a stranger on the
LAN sent, so every parser checks the size before it parses, accepts JSON only,
ignores unknown keys and answers ``None`` or :class:`ShareError` instead of
letting a malformed value through. ``docs/share-protocol.md`` is the normative
description; the two must agree.
"""

import json
import re
import unicodedata

#: Highest and lowest protocol version this build speaks.
PROTOCOL_VERSION = 1
PROTOCOL_MIN_VERSION = 1

#: Header every request and response carries, except a request for ``/info``.
VERSION_HEADER = "OpenEmux-Share-Version"

SERVICE_TYPE = "_openemux._tcp.local."
BEACON_PROTOCOL = "openemux-share"
BEACON_GROUP = "239.255.77.77"
BEACON_PORT = 53318
BEACON_TTL = 1
BEACON_INTERVAL = 2.0
#: A peer only the beacon found is dropped this long after its last beacon.
PEER_EXPIRY = 7.0
SERVER_PORT = 53319

BEACON_MAX_BYTES = 1024
BODY_MAX_BYTES = 1024 * 1024
OFFER_TTL = 60
CONNECT_TIMEOUT = 10.0
IDLE_TIMEOUT = 30.0

MAX_NAME_CHARS = 64
MAX_ITEMS = 2000
MAX_FILE_NAME_BYTES = 255

PLATFORMS = ("desktop", "phone", "tablet")
DEFAULT_PLATFORM = "desktop"

PATH_MDNS = "mdns"
PATH_BEACON = "beacon"
PATH_MANUAL = "manual"

_HEX = re.compile(r"[0-9a-f]+")


class ErrorCode:
    """Error codes, on the wire and in the core's own failures.

    The UI translates these (#589); the core never shows a sentence to a user.
    The last three never cross the network: they are what the client or the
    service report locally.
    """

    BAD_REQUEST = "bad_request"
    INCOMPATIBLE_VERSION = "incompatible_version"
    BAD_COMMIT = "bad_commit"
    NOT_FOUND = "not_found"
    BUSY = "busy"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DECLINED = "declined"
    TOO_LARGE = "too_large"
    NOT_IMPLEMENTED = "not_implemented"
    INTERNAL = "internal"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    UNREACHABLE = "unreachable"
    UNAVAILABLE = "unavailable"


#: The HTTP status each wire error is answered with.
HTTP_STATUS = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.INCOMPATIBLE_VERSION: 400,
    ErrorCode.BAD_COMMIT: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.BUSY: 409,
    ErrorCode.EXPIRED: 410,
    ErrorCode.CANCELLED: 410,
    ErrorCode.DECLINED: 410,
    ErrorCode.TOO_LARGE: 413,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.INTERNAL: 500,
}


class ShareError(Exception):
    """A protocol failure, carrying its :class:`ErrorCode`.

    ``details`` holds the extra fields of the error envelope -- the version
    ranges of an ``incompatible_version``.
    """

    def __init__(self, code, message="", details=None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = dict(details or {})

    @property
    def http_status(self):
        return HTTP_STATUS.get(self.code, 500)

    def to_envelope(self):
        envelope = dict(self.details)
        envelope["error"] = self.code
        envelope["message"] = self.message
        return envelope

    @classmethod
    def from_envelope(cls, status, body):
        """The error a response carried; ``internal`` when it carried none."""
        if not isinstance(body, dict) or not isinstance(body.get("error"), str):
            return cls(ErrorCode.INTERNAL, f"HTTP {status}")
        details = {k: v for k, v in body.items() if k not in ("error", "message")}
        message = body.get("message") if isinstance(body.get("message"), str) else ""
        return cls(body["error"], message, details)


def version_error(peer_min, peer_max):
    """The ``incompatible_version`` error naming both sides' versions."""
    return ShareError(
        ErrorCode.INCOMPATIBLE_VERSION,
        f"version {PROTOCOL_VERSION} vs {peer_max}",
        {
            "supported": {"min": PROTOCOL_MIN_VERSION, "max": PROTOCOL_VERSION},
            "peer": {"min": peer_min, "max": peer_max},
        },
    )


def is_compatible(vmin, v):
    """Whether a peer speaking ``vmin``..``v`` shares a version with us."""
    return negotiate(vmin, v) is not None


def negotiate(vmin, v):
    """The highest version both sides speak, or ``None``."""
    if not _is_int(vmin) or not _is_int(v) or vmin > v:
        return None
    best = min(v, PROTOCOL_VERSION)
    return best if best >= max(vmin, PROTOCOL_MIN_VERSION) else None


def is_hex(value, length):
    return (
        isinstance(value, str) and len(value) == length and _HEX.fullmatch(value) is not None
    )


def sanitize_name(name):
    """A device name fit to show: no control characters, at most 64 chars."""
    if not isinstance(name, str):
        return ""
    kept = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf"))
    return kept.strip()[:MAX_NAME_CHARS].strip()


def sanitize_platform(platform):
    return platform if platform in PLATFORMS else DEFAULT_PLATFORM


def format_fingerprint(fp):
    """``fp`` in groups of four, the way both apps display it."""
    return " ".join(fp[i:i + 4] for i in range(0, len(fp), 4))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _versions(raw_v, raw_vmin):
    """``(vmin, v)`` from advertised values; ``(0, 0)`` when unreadable.

    An unreadable version is still a device: it is listed and flagged
    incompatible, never dropped.
    """
    v = _to_int(raw_v)
    vmin = _to_int(raw_vmin)
    if v is None:
        return 0, 0
    if vmin is None or vmin > v:
        vmin = v
    return vmin, v


def _to_int(value):
    if _is_int(value):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _port(value):
    port = _to_int(value)
    return port if port is not None and 0 < port < 65536 else None


def _announcement(raw_id, name, platform, v, vmin, port, fp):
    """The normalized form every discovery path hands the peer list."""
    vmin, v = _versions(v, vmin)
    return {
        "id": raw_id,
        "name": sanitize_name(name) or raw_id[:6],
        "platform": sanitize_platform(platform),
        "v": v,
        "vmin": vmin,
        "port": port,
        "fp": fp,
        "compatible": is_compatible(vmin, v),
    }


def parse_beacon(data):
    """A beacon datagram as ``{"type", "id", ...}``, or ``None`` to drop it."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > BEACON_MAX_BYTES:
        return None
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("p") != BEACON_PROTOCOL:
        return None
    kind = payload.get("t")
    port = _port(payload.get("port"))
    if kind not in ("hello", "bye") or port is None:
        return None
    if not is_hex(payload.get("id"), 32) or not is_hex(payload.get("fp"), 64):
        return None
    parsed = _announcement(
        payload["id"], payload.get("name"), payload.get("pf"),
        payload.get("v"), payload.get("vmin"), port, payload["fp"],
    )
    parsed["type"] = kind
    return parsed


def build_beacon(kind, announcement):
    """The datagram announcing ``announcement`` (``hello`` or ``bye``)."""
    payload = {
        "p": BEACON_PROTOCOL,
        "t": kind,
        "id": announcement["id"],
        "name": announcement["name"],
        "pf": announcement["platform"],
        "v": announcement["v"],
        "vmin": announcement["vmin"],
        "port": announcement["port"],
        "fp": announcement["fp"],
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value if isinstance(value, str) else None


def parse_txt(properties, port):
    """An mDNS TXT record (bytes or str keys and values), or ``None``."""
    if not isinstance(properties, dict):
        return None
    txt = {}
    for key, value in properties.items():
        key = _text(key)
        if key is not None:
            txt[key] = _text(value)
    port = _port(port)
    if port is None or not is_hex(txt.get("id"), 32) or not is_hex(txt.get("fp"), 64):
        return None
    return _announcement(
        txt["id"], txt.get("name"), txt.get("pf"), txt.get("v"), txt.get("vmin"), port, txt["fp"]
    )


def build_txt(announcement):
    return {
        "id": announcement["id"],
        "name": announcement["name"],
        "pf": announcement["platform"],
        "v": str(announcement["v"]),
        "vmin": str(announcement["vmin"]),
        "fp": announcement["fp"],
    }


def parse_info(payload):
    """A ``GET /info`` answer, normalized; :class:`ShareError` when unusable."""
    if not isinstance(payload, dict) or not is_hex(payload.get("id"), 32):
        raise ShareError(ErrorCode.BAD_REQUEST, "malformed /info")
    vmin, v = _versions(payload.get("v"), payload.get("vmin"))
    return {
        "id": payload["id"],
        "name": sanitize_name(payload.get("name")) or payload["id"][:6],
        "platform": sanitize_platform(payload.get("pf")),
        "v": v,
        "vmin": vmin,
        "compatible": is_compatible(vmin, v),
    }


def _bad(message):
    return ShareError(ErrorCode.BAD_REQUEST, message)


def is_safe_file_name(name):
    """A bare file name: never a path, never empty, at most 255 bytes."""
    if not isinstance(name, str) or name in ("", ".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name or ".." in name:
        return False
    return len(name.encode("utf-8")) <= MAX_FILE_NAME_BYTES


def validate_manifest(manifest):
    """Check the manifest's shape and limits; raise ``bad_request`` if off.

    Only the envelope is checked here. Placement, conflicts and writing are
    #588's, and a name is never turned into a path by anything: the receiver
    computes every path itself.
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get("games"), list):
        raise _bad("manifest.games must be a list")
    count = 0
    for game in manifest["games"]:
        if not isinstance(game, dict) or not isinstance(game.get("items"), list):
            raise _bad("game.items must be a list")
        for key in ("id", "console", "title"):
            if not isinstance(game.get(key), str):
                raise _bad(f"game.{key} must be a string")
        for item in game["items"]:
            count += 1
            if count > MAX_ITEMS:
                raise _bad(f"more than {MAX_ITEMS} items")
            _validate_item(item)
    for key in ("total_size", "file_count"):
        if not _is_int(manifest.get(key)) or manifest[key] < 0:
            raise _bad(f"manifest.{key} must be a non-negative integer")
    return manifest


def _validate_item(item):
    if not isinstance(item, dict):
        raise _bad("item must be an object")
    if not isinstance(item.get("id"), str) or not isinstance(item.get("kind"), str):
        raise _bad("item.id and item.kind must be strings")
    if not is_safe_file_name(item.get("name")):
        raise _bad("item.name must be a bare file name")
    if not _is_int(item.get("size")) or item["size"] < 0:
        raise _bad("item.size must be a non-negative integer")
    if not isinstance(item.get("mtime"), (int, float)) or isinstance(item["mtime"], bool):
        raise _bad("item.mtime must be a number")


def parse_offer(payload):
    """A ``POST /offer`` body: ``{sender, commit, manifest}``, validated."""
    if not isinstance(payload, dict):
        raise _bad("offer must be an object")
    sender = payload.get("sender")
    if not isinstance(sender, dict) or not is_hex(sender.get("id"), 32):
        raise _bad("sender.id must be 32 hex characters")
    if not is_hex(sender.get("fp"), 64):
        raise _bad("sender.fp must be 64 hex characters")
    if not is_hex(payload.get("commit"), 64):
        raise _bad("commit must be 64 hex characters")
    validate_manifest(payload.get("manifest"))
    return {
        "sender": {
            "id": sender["id"],
            "name": sanitize_name(sender.get("name")) or sender["id"][:6],
            "platform": sanitize_platform(sender.get("pf")),
            "fp": sender["fp"],
        },
        "commit": payload["commit"],
        "manifest": payload["manifest"],
    }
