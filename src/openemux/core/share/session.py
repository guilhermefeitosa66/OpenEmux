"""The secure session: HTTPS over TLS 1.3 with the certificate pinned.

The receiver runs :class:`ShareServer`; the sender talks to it with
:class:`ShareClient`. There is no CA: the client compares the SHA-256 of the
certificate it was shown with the fingerprint it expects, right after the
handshake and before a byte of HTTP. With no fingerprint to expect (a typed
address) the first one seen is used, and the verification code -- built from
both fingerprints and both nonces -- is what protects that first contact.

Only the offer handshake lives here; the file bodies (``PUT /file``) are
#588's, behind :attr:`ShareServer.file_handler`.
"""

import base64
import hashlib
import hmac
import http.client
import json
import logging
import os
import socketserver
import ssl
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from openemux.core.share import verification
from openemux.core.share.protocol import (
    BODY_MAX_BYTES,
    CONNECT_TIMEOUT,
    IDLE_TIMEOUT,
    OFFER_TTL,
    PROTOCOL_VERSION,
    SERVER_PORT,
    VERSION_HEADER,
    ErrorCode,
    ShareError,
    is_hex,
    negotiate,
    parse_info,
    parse_offer,
    version_error,
)

logger = logging.getLogger(__name__)

STATUS_COMMITTED = "committed"
STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_DECLINED = "declined"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"

#: Statuses an offer can still leave; the others are final.
LIVE_STATUSES = (STATUS_COMMITTED, STATUS_PENDING)
#: How long a finished offer is kept for the sender's last poll.
FINISHED_RETENTION = 300
JOIN_TIMEOUT = 2.0
#: The most an error answer reads away before closing (see _discard_body).
DISCARD_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class IncomingOffer:
    """What the receiver's UI is handed once an offer is revealed."""

    offer_id: str
    sender: dict
    manifest: dict
    code: str


class _Offer:
    def __init__(self, offer_id, parsed, nonce_r, created):
        self.offer_id = offer_id
        self.sender = parsed["sender"]
        self.commit = parsed["commit"]
        self.manifest = parsed["manifest"]
        self.nonce_r = nonce_r
        self.created = created
        self.status = STATUS_COMMITTED
        self.items = None
        self.code = None


def new_offer_id():
    """128 random bits, url-safe base64 without padding: 22 characters."""
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")


def _not_implemented(offer, item_id, request):
    raise ShareError(ErrorCode.NOT_IMPLEMENTED, "file transfer is not implemented")


def tls_server_context(cert_path, key_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


def tls_client_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    # Pinning replaces the CA and the host name: see the module docstring.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = IDLE_TIMEOUT
    server_version = "OpenEmuxShare"
    sys_version = ""

    def setup(self):
        # The handshake runs here, in this connection's own thread, so a
        # client that stalls mid-handshake never blocks the accept loop.
        raw = self.request
        raw.settimeout(CONNECT_TIMEOUT)
        try:
            self.request = self.server.ssl_context.wrap_socket(raw, server_side=True)
        except Exception:
            raw.close()
            raise
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            self.request.close()

    def log_message(self, format, *args):
        logger.debug("share %s - %s", self.address_string(), format % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def _dispatch(self, method):
        self._body_read = False
        self.server.share.request_count += 1
        try:
            status, body = self.server.share.route(method, self.path.split("?")[0], self)
        except ShareError as exc:
            status, body = exc.http_status, exc.to_envelope()
            self._discard_body()
        except Exception:
            logger.exception("Share server failed on %s %s", method, self.path)
            status, body = 500, ShareError(ErrorCode.INTERNAL, "internal error").to_envelope()
            self._discard_body()
        self._respond(status, body)

    def _discard_body(self):
        """Read an unread body away, then end the connection after the answer.

        Closing a TLS socket with bytes still unread resets it, and the client
        loses the error answer with it. A body too large to be worth reading
        is left, and that client sees the reset instead.
        """
        self.close_connection = True
        length = self.headers.get("Content-Length", "0")
        if not self._body_read and length.isdigit() and int(length) <= DISCARD_MAX_BYTES:
            self._body_read = True
            remaining = int(length)
            while remaining:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

    def _respond(self, status, body):
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header(VERSION_HEADER, str(PROTOCOL_VERSION))
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        length = self.headers.get("Content-Length", "0")
        if not length.isdigit():
            raise ShareError(ErrorCode.BAD_REQUEST, "bad Content-Length")
        if int(length) > BODY_MAX_BYTES:
            raise ShareError(ErrorCode.TOO_LARGE, "body over 1 MiB")
        self._body_read = True
        try:
            return json.loads(self.rfile.read(int(length)).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ShareError(ErrorCode.BAD_REQUEST, "body is not JSON") from exc


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer's own resolves the bound address with getfqdn(), a
        # reverse DNS lookup that can stall start() for seconds.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        # A failed handshake -- a wrong client, a port scan -- is not news.
        logger.debug("Share connection from %s dropped", client_address, exc_info=True)


class ShareServer:
    """The receiving side: ``/info``, the offer handshake, and its state."""

    def __init__(self, identity, clock=time.monotonic, on_offer=None, on_cancel=None,
                 host="0.0.0.0", port=SERVER_PORT):
        self.identity = identity
        self.clock = clock
        self.on_offer = on_offer
        self.on_cancel = on_cancel
        self.host = host
        self.preferred_port = port
        self.file_handler = _not_implemented
        self.request_count = 0
        self.port = None
        self._offers = {}
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    # -- lifecycle -------------------------------------------------------

    def start(self):
        """Listen; returns the port, which falls back to any free one."""
        if self._httpd is not None:
            return self.port
        context = tls_server_context(self.identity.cert_path, self.identity.key_path)
        try:
            httpd = _HTTPServer((self.host, self.preferred_port), _Handler)
        except OSError:
            httpd = _HTTPServer((self.host, 0), _Handler)
        httpd.ssl_context = context
        httpd.share = self
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
            name="share-server", daemon=True,
        )
        self._thread.start()
        return self.port

    def stop(self):
        if self._httpd is None:
            return
        httpd, self._httpd = self._httpd, None
        httpd.shutdown()
        httpd.server_close()
        self._thread.join(JOIN_TIMEOUT)
        self._thread = None

    @property
    def listening(self):
        return self._httpd is not None

    # -- caller API ------------------------------------------------------

    def answer(self, offer_id, accepted, items=None):
        """The user's decision on a revealed offer."""
        with self._lock:
            offer = self._live_offer(offer_id)
            if offer.status != STATUS_PENDING:
                raise ShareError(ErrorCode.BAD_REQUEST, "offer is not waiting for an answer")
            offer.status = STATUS_ACCEPTED if accepted else STATUS_DECLINED
            offer.items = list(items or []) if accepted else None

    def cancel(self, offer_id):
        """Cancel from this side; the sender learns it on its next request."""
        with self._lock:
            offer = self._offers.get(offer_id)
            if offer is not None:
                offer.status = STATUS_CANCELLED

    # -- routing ---------------------------------------------------------

    def route(self, method, path, request):
        parts = [part for part in path.split("/") if part]
        if method == "GET" and parts == ["info"]:
            return 200, self.identity.info()
        self._check_version(request.headers.get(VERSION_HEADER))
        if method == "POST" and parts == ["offer"]:
            return self._create_offer(request.read_json())
        if method == "POST" and len(parts) == 3 and parts[0] == "offer" and parts[2] == "reveal":
            return self._reveal(parts[1], request.read_json())
        if method == "GET" and len(parts) == 2 and parts[0] == "offer":
            return self._poll(parts[1])
        if method == "POST" and len(parts) == 2 and parts[0] == "cancel":
            return self._cancelled_by_sender(parts[1])
        if method == "PUT" and len(parts) == 3 and parts[0] == "file":
            return self._file(parts[1], parts[2], request)
        raise ShareError(ErrorCode.NOT_FOUND, "no such endpoint")

    @staticmethod
    def _check_version(header):
        peer = int(header) if header is not None and header.isdigit() else None
        if peer is None or negotiate(peer, peer) is None:
            raise version_error(peer, peer)

    def _expire(self, now):
        for offer_id, offer in list(self._offers.items()):
            age = now - offer.created
            if offer.status in LIVE_STATUSES and age > OFFER_TTL:
                offer.status = STATUS_EXPIRED
            elif offer.status not in LIVE_STATUSES and age > FINISHED_RETENTION:
                del self._offers[offer_id]

    def _live_offer(self, offer_id):
        self._expire(self.clock())
        offer = self._offers.get(offer_id)
        if offer is None:
            raise ShareError(ErrorCode.NOT_FOUND, "no such offer")
        if offer.status == STATUS_EXPIRED:
            raise ShareError(ErrorCode.EXPIRED, "offer expired")
        return offer

    def _create_offer(self, body):
        parsed = parse_offer(body)
        with self._lock:
            now = self.clock()
            self._expire(now)
            if any(offer.status in LIVE_STATUSES for offer in self._offers.values()):
                raise ShareError(ErrorCode.BUSY, "another offer is pending")
            offer = _Offer(new_offer_id(), parsed, verification.new_nonce(), now)
            self._offers[offer.offer_id] = offer
        return 201, {"offer_id": offer.offer_id, "nonce_r": offer.nonce_r.hex(), "expires_in": OFFER_TTL}

    def _reveal(self, offer_id, body):
        nonce_s = body.get("nonce_s") if isinstance(body, dict) else None
        if not is_hex(nonce_s, 2 * verification.NONCE_BYTES):
            raise ShareError(ErrorCode.BAD_REQUEST, "nonce_s must be 64 hex characters")
        nonce_s = bytes.fromhex(nonce_s)
        with self._lock:
            offer = self._live_offer(offer_id)
            if offer.status != STATUS_COMMITTED:
                raise ShareError(ErrorCode.BAD_REQUEST, "offer already revealed")
            if not verification.check_commit(offer.commit, nonce_s):
                del self._offers[offer_id]
                raise ShareError(ErrorCode.BAD_COMMIT, "nonce does not match the commitment")
            offer.code = verification.code(
                offer.sender["fp"], self.identity.fingerprint, nonce_s, offer.nonce_r
            )
            offer.status = STATUS_PENDING
            incoming = IncomingOffer(offer.offer_id, offer.sender, offer.manifest, offer.code)
        if self.on_offer is not None:
            self.on_offer(incoming)
        return 200, {"code": incoming.code}

    def _poll(self, offer_id):
        with self._lock:
            self._expire(self.clock())
            offer = self._offers.get(offer_id)
            if offer is None:
                raise ShareError(ErrorCode.NOT_FOUND, "no such offer")
            status = STATUS_PENDING if offer.status == STATUS_COMMITTED else offer.status
            body = {"status": status}
            if offer.status == STATUS_ACCEPTED:
                body["items"] = offer.items
        return 200, body

    def _cancelled_by_sender(self, offer_id):
        with self._lock:
            offer = self._offers.get(offer_id)
            if offer is None:
                raise ShareError(ErrorCode.NOT_FOUND, "no such offer")
            offer.status = STATUS_CANCELLED
        if self.on_cancel is not None:
            self.on_cancel(offer_id)
        return 204, None

    def _file(self, offer_id, item_id, request):
        with self._lock:
            offer = self._live_offer(offer_id)
            if offer.status in (STATUS_CANCELLED, STATUS_DECLINED):
                raise ShareError(offer.status, f"offer {offer.status}")
            sendable = {
                item.get("id") for item in offer.items or ()
                if isinstance(item, dict) and item.get("action") == "send"
            }
            if offer.status != STATUS_ACCEPTED or item_id not in sendable:
                raise ShareError(ErrorCode.BAD_REQUEST, "item is not accepted for upload")
        self.file_handler(offer, item_id, request)
        return 204, None


class ShareClient:
    """The sending side, talking to one receiver.

    Every request opens its own connection and pins the certificate on it;
    the connection is closed whatever happens. ``peer_fp`` is the fingerprint
    the receiver presented -- the one the verification code is built from.
    """

    def __init__(self, host, port=SERVER_PORT, expected_fp=None, context=None):
        self.host = host
        self.port = port
        self.peer_fp = expected_fp
        self.context = context or tls_client_context()

    def _connect(self):
        conn = http.client.HTTPSConnection(
            self.host, self.port, context=self.context, timeout=CONNECT_TIMEOUT
        )
        try:
            conn.connect()
            der = conn.sock.getpeercert(binary_form=True)
            observed = hashlib.sha256(der).hexdigest()
            if self.peer_fp is not None and not hmac.compare_digest(observed, self.peer_fp):
                raise ShareError(
                    ErrorCode.FINGERPRINT_MISMATCH,
                    "the device presented a different certificate",
                )
            conn.sock.settimeout(IDLE_TIMEOUT)
        except ShareError:
            conn.close()
            raise
        except (OSError, ssl.SSLError) as exc:
            conn.close()
            raise ShareError(ErrorCode.UNREACHABLE, str(exc)) from exc
        self.peer_fp = observed
        return conn

    def request(self, method, path, body=None):
        """``(status, json-or-None)``; an error answer raises :class:`ShareError`."""
        conn = self._connect()
        try:
            payload = None if body is None else json.dumps(body).encode("utf-8")
            headers = {VERSION_HEADER: str(PROTOCOL_VERSION)}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read(BODY_MAX_BYTES + 1)
            status = response.status
        except (OSError, http.client.HTTPException) as exc:
            raise ShareError(ErrorCode.UNREACHABLE, str(exc)) from exc
        finally:
            conn.close()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, ValueError):
            data = None
        if status >= 400:
            raise ShareError.from_envelope(status, data)
        return status, data

    def info(self):
        """The receiver's ``/info``; ``incompatible_version`` when no version is shared."""
        _, data = self.request("GET", "/info")
        info = parse_info(data)
        if not info["compatible"]:
            raise version_error(info["vmin"], info["v"])
        return info

    def offer(self, sender, manifest):
        """Commit, offer, reveal. Returns ``(offer_id, code)``."""
        self.info()
        nonce_s = verification.new_nonce()
        body = {"sender": sender, "commit": verification.commit(nonce_s), "manifest": manifest}
        _, created = self.request("POST", "/offer", body)
        if (
            not isinstance(created, dict)
            or not isinstance(created.get("offer_id"), str)
            or not is_hex(created.get("nonce_r"), 2 * verification.NONCE_BYTES)
        ):
            raise ShareError(ErrorCode.BAD_REQUEST, "malformed offer answer")
        offer_id = created["offer_id"]
        self.request("POST", f"/offer/{offer_id}/reveal", {"nonce_s": nonce_s.hex()})
        code = verification.code(sender["fp"], self.peer_fp, nonce_s, bytes.fromhex(created["nonce_r"]))
        return offer_id, code

    def poll(self, offer_id):
        _, data = self.request("GET", f"/offer/{offer_id}")
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise ShareError(ErrorCode.BAD_REQUEST, "malformed poll answer")
        return data

    def cancel(self, offer_id):
        self.request("POST", f"/cancel/{offer_id}")

