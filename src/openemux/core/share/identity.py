"""This device as Share nearby presents it: id, name and certificate.

Generated once and kept under ``~/.openemux/share/``: ``identity.json`` holds
the id, ``key.pem`` the private key (0600) and ``cert.pem`` the self-signed
certificate whose SHA-256 is the fingerprint other devices pin. The directory
is 0700. Anything missing, unreadable or inconsistent regenerates all three:
a new identity only costs the other side a new verification code.

``cryptography`` is imported here and nowhere earlier, so an install without
it still starts; ``core.share.availability()`` is what the UI asks first.
"""

import datetime
import hashlib
import json
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from openemux.core.atomic_write import atomic_write_bytes, atomic_write_text
from openemux.core.share.protocol import (
    DEFAULT_PLATFORM,
    PROTOCOL_MIN_VERSION,
    PROTOCOL_VERSION,
    is_hex,
    sanitize_name,
)

logger = logging.getLogger(__name__)

IDENTITY_FILE = "identity.json"
KEY_FILE = "key.pem"
CERT_FILE = "cert.pem"
CERT_VALIDITY_DAYS = 20 * 365
CN_PREFIX = "OpenEmux Share "


@dataclass(frozen=True)
class DeviceIdentity:
    id: str
    name: str
    platform: str
    fingerprint: str
    cert_path: Path
    key_path: Path

    def announcement(self, port):
        """What discovery advertises: the keys the peer list is built from."""
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "v": PROTOCOL_VERSION,
            "vmin": PROTOCOL_MIN_VERSION,
            "port": port,
            "fp": self.fingerprint,
        }

    def info(self):
        """The body of ``GET /info``."""
        return {
            "id": self.id,
            "name": self.name,
            "pf": self.platform,
            "v": PROTOCOL_VERSION,
            "vmin": PROTOCOL_MIN_VERSION,
        }

    def sender(self):
        """The ``sender`` object of an offer."""
        return {"id": self.id, "name": self.name, "pf": self.platform, "fp": self.fingerprint}


def default_device_name():
    return sanitize_name(socket.gethostname()) or "OpenEmux"


def fingerprint_of(der):
    return hashlib.sha256(der).hexdigest()


def load_or_create(share_dir, name=""):
    """The identity stored in ``share_dir``, created on first use."""
    share_dir = Path(share_dir)
    share_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(share_dir, 0o700)
    name = sanitize_name(name) or default_device_name()
    paths = (share_dir / IDENTITY_FILE, share_dir / KEY_FILE, share_dir / CERT_FILE)
    if any(path.exists() for path in paths):
        try:
            device_id, fp = _load(*paths)
            return _identity(device_id, name, fp, share_dir)
        # Broad on purpose: cryptography raises its own types for a file it
        # cannot use, and every one of them means the same thing here.
        except Exception as exc:
            logger.warning("Share identity in %s is unusable (%s); creating a new one", share_dir, exc)
    device_id, fp = _create(*paths)
    return _identity(device_id, name, fp, share_dir)


def _identity(device_id, name, fp, share_dir):
    return DeviceIdentity(
        device_id, name, DEFAULT_PLATFORM, fp, share_dir / CERT_FILE, share_dir / KEY_FILE
    )


def _load(identity_path, key_path, cert_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID

    device_id = json.loads(identity_path.read_text(encoding="utf-8"))["id"]
    if not is_hex(device_id, 32):
        raise ValueError("bad device id")
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if [attr.value for attr in common_names] != [CN_PREFIX + device_id]:
        raise ValueError("certificate belongs to another id")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    public = serialization.PublicFormat.SubjectPublicKeyInfo
    encoding = serialization.Encoding.DER
    if key.public_key().public_bytes(encoding, public) != cert.public_key().public_bytes(encoding, public):
        raise ValueError("key does not match the certificate")
    return device_id, fingerprint_of(cert.public_bytes(encoding))


def _create(identity_path, key_path, cert_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    device_id = os.urandom(16).hex()
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CN_PREFIX + device_id)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    atomic_write_bytes(key_path, key_pem, mode=0o600)
    atomic_write_bytes(cert_path, cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
    atomic_write_text(identity_path, json.dumps({"id": device_id}) + "\n", mode=0o644)
    return device_id, fingerprint_of(cert.public_bytes(serialization.Encoding.DER))
