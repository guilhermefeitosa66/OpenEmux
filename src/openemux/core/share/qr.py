"""This device's address as a QR code, when ``segno`` is installed (#589).

``segno`` is optional, like ``zeroconf``: without it the Connect by Address
page shows the address as text only. Imported lazily, so a missing package
costs nothing until the page asks.
"""

import importlib
import importlib.util
import io


def available():
    try:
        return importlib.util.find_spec("segno") is not None
    except (ImportError, ValueError):
        return False


def png_bytes(text, scale=4):
    """A PNG of ``text`` (error correction M, quiet zone 4, dark on white), or ``None``."""
    if not available():
        return None
    segno = importlib.import_module("segno")
    buffer = io.BytesIO()
    segno.make(text, error="m", micro=False).save(
        buffer, kind="png", scale=scale, border=4, dark="#000000", light="#ffffff"
    )
    return buffer.getvalue()
