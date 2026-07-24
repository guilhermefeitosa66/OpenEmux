"""Optionally-embedded ScreenScraper *developer* credentials.

OpenEmux's official builds bake the project's ScreenScraper developer account
(``devid`` + ``devpassword``) in here so cover scraping via ScreenScraper works
out of the box, without every user having to request their own developer
account. See ``core/screenscraper.py`` for how the two credential pairs differ:
the developer pair identifies the *application*; the ``ssid``/``sspassword``
pair (kept in Preferences) is the *end user's* account and decides whose quota a
request spends.

How the value gets here
-----------------------
* The placeholder below (:data:`_EMBEDDED_BLOB`) is **empty in the source tree**
  and MUST stay empty in git. Local and development builds therefore ship no
  embedded credential and behave exactly as before: ScreenScraper stays opt-in
  and off by default.
* Official release builds inject the credential at packaging time from a CI
  secret, via ``packaging/embed_screenscraper_credentials.py`` (documented in
  ``docs/DEVELOPMENT.md``). The injection only rewrites the built copy; it never
  touches the committed source.

On secrecy
----------
The blob is lightly obfuscated (XOR + base64) only so it is not a plaintext,
grep-able string in the artifact. This is **not** real secrecy -- a credential
shipped inside a client is inherently extractable. Two things make that
acceptable: per-user ``ssid`` accounts (so heavy users spend their own quota,
not the project's), and the ability to rotate this credential with ScreenScraper
staff if it is ever abused.
"""
import base64

#: base64( XOR( "devid\ndevpassword", _OBFUSCATION_KEY ) ). Empty in the source
#: tree; overwritten in official builds by the injection script. Never commit a
#: non-empty value here (``tests/test_embedded_credentials.py`` guards this).
_EMBEDDED_BLOB = ""

#: Fixed XOR key. Obfuscation only -- deliberately public; not a secret.
_OBFUSCATION_KEY = b"OpenEmux-ScreenScraper-embed-v1"

_SEPARATOR = "\n"


def _xor(data, key):
    return bytes(byte ^ key[i % len(key)] for i, byte in enumerate(data))


def obfuscate(devid, devpassword):
    """Encode a (devid, devpassword) pair into the embeddable blob string.

    Symmetric with :func:`deobfuscate`; used by the build-time injection script
    and by the tests.
    """
    text = f"{devid}{_SEPARATOR}{devpassword}"
    return base64.b64encode(_xor(text.encode("utf-8"), _OBFUSCATION_KEY)).decode("ascii")


def deobfuscate(blob):
    """Decode a blob back into ``(devid, devpassword)``. Raises on bad input."""
    raw = _xor(base64.b64decode(blob.encode("ascii")), _OBFUSCATION_KEY)
    devid, devpassword = raw.decode("utf-8").split(_SEPARATOR, 1)
    return devid.strip(), devpassword.strip()


def get_embedded_dev_credentials():
    """Return ``(devid, devpassword)`` baked into this build, or ``("", "")``.

    Never raises: a malformed blob degrades to "no embedded credential" so a bad
    injection can only fall back to libretro, never crash the app.
    """
    if not _EMBEDDED_BLOB:
        return ("", "")
    try:
        return deobfuscate(_EMBEDDED_BLOB)
    except Exception:  # noqa: BLE001 - any decode failure means "no credential"
        return ("", "")


def has_embedded_dev_credentials():
    """True when this build carries a usable embedded developer credential."""
    devid, devpassword = get_embedded_dev_credentials()
    return bool(devid and devpassword)
