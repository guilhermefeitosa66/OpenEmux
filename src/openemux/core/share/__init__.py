"""Share nearby: send games between OpenEmux devices on the same network.

Epic #586; this package is the desktop core of issue #587 -- device identity,
discovery and the secure session. The wire format is specified normatively in
``docs/share-protocol.md``, which is what the Android side is written against;
read that before changing anything that crosses the network.

Both third-party dependencies are optional and imported lazily, the way
``core/x11_windows.py`` treats python-xlib. Without ``cryptography`` there is
no certificate, so the feature is off; without ``zeroconf`` discovery runs on
the UDP beacon alone. Neither ever stops the app from starting.
"""

import importlib.util

#: The value :func:`availability` reports for a part that works.
AVAILABLE = "ok"


def _installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def availability():
    """What Share nearby can do on this install.

    ``{"share": ..., "mdns": ...}``, each ``"ok"`` or ``"unavailable:<module>"``
    naming the missing dependency, for the UI to explain. ``mdns`` is reported
    unavailable too when the whole feature is.
    """
    if not _installed("cryptography"):
        missing = "unavailable:cryptography"
        return {"share": missing, "mdns": missing}
    mdns = AVAILABLE if _installed("zeroconf") else "unavailable:zeroconf"
    return {"share": AVAILABLE, "mdns": mdns}
