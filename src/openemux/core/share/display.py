"""Words and numbers for the Share nearby screens (#589).

The core never shows a sentence to a user (``protocol.ErrorCode``): every
code, reason, path and size it reports is turned into text here, through the
caller's ``t(key, **kwargs)``. Pure -- no GTK, no files read except the
modification time of a file a conflict would replace.
"""

import time
from pathlib import Path

from openemux.core.save_backup import (
    ON_COLLISION_KEEP_BOTH,
    ON_COLLISION_NEWEST,
    ON_COLLISION_OVERWRITE,
    ON_COLLISION_SKIP,
)
from openemux.core.share.manifest import AUTO_SLOT, is_main_rom
from openemux.core.share.placement import ACTION_SEND
from openemux.core.share.protocol import (
    KIND_BATTERY_SAVE,
    KIND_COVER,
    KIND_LABEL,
    KIND_ROM,
    KIND_STATE,
    PATH_BEACON,
    PATH_MANUAL,
    PATH_MDNS,
    ErrorCode,
    SkipReason,
)

#: Decimal units, like GNOME Files: ``(key, factor, decimals)``.
_SIZE_UNITS = (
    ("share.size.gb", 1000 ** 3, 1),
    ("share.size.mb", 1000 ** 2, 1),
    ("share.size.kb", 1000, 0),
)

#: The order the discovery paths are named in, whatever order they were found.
_PATHS = (
    (PATH_MDNS, "share.paths.mdns"),
    (PATH_BEACON, "share.paths.beacon"),
    (PATH_MANUAL, "share.paths.manual"),
)

_PLATFORMS = {
    "desktop": ("computer-symbolic", "share.platform.desktop"),
    "phone": ("phone-symbolic", "share.platform.phone"),
    "tablet": ("tablet-symbolic", "share.platform.tablet"),
}

#: A transfer's end, or a failure, as the title and body of a result page.
_ERRORS = {
    ErrorCode.DECLINED: "share.error.declined",
    ErrorCode.EXPIRED: "share.error.expired",
    ErrorCode.CANCELLED: "share.error.cancelled",
    ErrorCode.BUSY: "share.error.busy",
    ErrorCode.FINGERPRINT_MISMATCH: "share.error.fingerprint_mismatch",
    ErrorCode.INCOMPATIBLE_VERSION: "share.error.incompatible_version",
    ErrorCode.TOO_LARGE: "share.error.too_large",
    ErrorCode.NO_SPACE: "share.error.no_space",
    ErrorCode.SOURCE_CHANGED: "share.error.source_changed",
    ErrorCode.UNREACHABLE: "share.error.unreachable",
    ErrorCode.IDLE_TIMEOUT: "share.error.idle_timeout",
    ErrorCode.UNAVAILABLE: "share.error.unavailable",
    ErrorCode.BAD_REQUEST: "share.error.bad_request",
}

_REASONS = {
    SkipReason.EXISTS_SKIP: "share.reason.exists_skip",
    SkipReason.INCOMPATIBLE_STATE: "share.reason.incompatible_state",
    SkipReason.UNSUPPORTED_CONSOLE: "share.reason.unsupported_console",
    SkipReason.USER_UNCHECKED: "share.reason.user_unchecked",
    SkipReason.INVALID_ITEM: "share.reason.invalid_item",
    SkipReason.UNIT_INCOMPLETE: "share.reason.unit_incomplete",
    SkipReason.TOO_MANY_ITEMS: "share.reason.too_many_items",
}

#: The same reasons, told from the sender's side: ``device`` did it.
_SENDER_REASONS = {
    SkipReason.EXISTS_SKIP: "share.reason.sent.exists_skip",
    SkipReason.USER_UNCHECKED: "share.reason.sent.not_accepted",
    SkipReason.INCOMPATIBLE_STATE: "share.reason.sent.cant_place",
    SkipReason.INVALID_ITEM: "share.reason.sent.cant_place",
    SkipReason.UNSUPPORTED_CONSOLE: "share.reason.sent.unsupported_console",
    SkipReason.UNIT_INCOMPLETE: "share.reason.unit_incomplete",
    SkipReason.TOO_MANY_ITEMS: "share.reason.too_many_items",
}

_KINDS = {
    KIND_ROM: "share.kind.rom",
    KIND_BATTERY_SAVE: "share.kind.battery_save",
    KIND_COVER: "share.kind.cover",
    KIND_LABEL: "share.kind.label",
}

#: Every policy, in the order a conflict row lists them.
POLICIES = (ON_COLLISION_NEWEST, ON_COLLISION_KEEP_BOTH, ON_COLLISION_OVERWRITE, ON_COLLISION_SKIP)
POLICY_KEYS = {
    ON_COLLISION_NEWEST: "share.policy.newest",
    ON_COLLISION_KEEP_BOTH: "share.policy.keep_both",
    ON_COLLISION_OVERWRITE: "share.policy.replace",
    ON_COLLISION_SKIP: "share.policy.skip",
}
#: Keeping two copies of a cover means nothing: the library shows one.
_ART_POLICIES = (ON_COLLISION_SKIP, ON_COLLISION_OVERWRITE)
#: The plan that finds every conflict: with "replace" everywhere, each item
#: that meets an existing file says which one.
PROBE_POLICIES = {
    kind: ON_COLLISION_OVERWRITE
    for kind in (KIND_ROM, KIND_BATTERY_SAVE, KIND_STATE, KIND_COVER, KIND_LABEL)
}


def format_size(n_bytes, t):
    for key, factor, decimals in _SIZE_UNITS:
        if n_bytes >= factor:
            return t(key, value=f"{n_bytes / factor:.{decimals}f}")
    return t("share.size.b", value=str(n_bytes))


def plural(t, count, one, many, **kwargs):
    """``one`` for a single thing, ``many`` otherwise; both get ``count``."""
    return t(one if count == 1 else many, count=count, **kwargs)


def paths_label(paths, t):
    names = [t(key) for path, key in _PATHS if path in paths]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return t("share.paths.and", first=", ".join(names[:-1]), last=names[-1])


def platform_icon(platform):
    return _PLATFORMS.get(platform, _PLATFORMS["desktop"])[0]


def platform_key(platform):
    return _PLATFORMS.get(platform, _PLATFORMS["desktop"])[1]


def error_key(code):
    return _ERRORS.get(code, "share.error.generic")


def reason_key(reason):
    return _REASONS.get(reason, "share.reason.invalid_item")


def sender_reason_key(reason):
    """A skip reason as the sender reads it; no answer at all is "not accepted"."""
    return _SENDER_REASONS.get(reason, "share.reason.sent.not_accepted")


def item_kind_label(kind, t, slot=None):
    if kind == KIND_STATE:
        if slot == AUTO_SLOT:
            return t("share.kind.state_auto")
        return t("share.kind.state", slot=slot or 0)
    return t(_KINDS.get(kind, "share.kind.rom"))


def format_date(timestamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def countdown(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def spaced_digits(code):
    """``"482913"`` read as ``"4 8 2 9 1 3"``, for a screen reader."""
    return " ".join(ch for ch in code if ch.isdigit())


def manifest_items(manifest):
    """``{item_id: (game, item)}`` over a manifest."""
    return {item["id"]: (game, item) for game in manifest.get("games", []) for item in game.get("items", [])}


def conflict_rows(probe, manifest):
    """The items that meet a file already in the library, one row each.

    ``probe`` is the plan made with :data:`PROBE_POLICIES`: every conflict in
    it replaces something, which is how the local file's date is known. A
    multi-file ROM
    is one row, its main file's. Same-content ROMs are no conflict: the
    receiver skips them on its own.
    """
    items = manifest_items(manifest)
    rows = []
    for decision in probe.decisions():
        if decision.action != ACTION_SEND or decision.replaces is None:
            continue
        game, item = items[decision.item_id]
        if decision.kind == KIND_ROM and not is_main_rom(item):
            continue
        try:
            yours = Path(decision.replaces).stat().st_mtime
        except OSError:
            continue
        rows.append({
            "item_id": decision.item_id,
            "game": game.get("title", ""),
            "kind": decision.kind,
            "slot": (item.get("state") or {}).get("slot"),
            "yours": yours,
            "incoming": item["mtime"],
            "newer": item["mtime"] > yours,
            "policies": _ART_POLICIES if decision.kind in (KIND_COVER, KIND_LABEL) else POLICIES,
        })
    return rows
