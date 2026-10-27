"""Which games a finished transfer delivered, and why the others did not (#614).

A transfer is answered and uploaded item by item, but the people on both ends
count games. The result pages used to count what was *offered*: a game the
receiver left out still came out as sent. These helpers turn the sender's
manifest and the core's result -- or the receiver's plan -- into the games
that arrived and the ones that did not, each with the reason the core gave.

Pure: no GTK, no files read.
"""

from dataclasses import dataclass, field
from pathlib import Path

from openemux.core.share.manifest import is_main_rom
from openemux.core.share.placement import ACTION_SEND, ROM_ABSENT, ROM_EXISTING
from openemux.core.share.protocol import KIND_ROM, SkipReason


@dataclass
class DeliveryReport:
    delivered: int = 0
    total: int = 0
    #: ``{title, console, reason, excluded}`` for every game that did not
    #: arrive; ``excluded`` when the sender's own build left it out.
    missing: list = field(default_factory=list)

    @property
    def complete(self):
        return not self.missing


def game_delivered(rom_status, actions):
    """The one rule both ends count a game by.

    The ROM is in the receiver's library -- placed now, or already there --
    and something of the game was written. A ROM already there with nothing
    else new is not a game delivered: it is "already on the device".
    """
    return rom_status != ROM_ABSENT and ACTION_SEND in actions


def send_report(built, result):
    """What a finished send delivered, from the manifest that was offered.

    ``built`` is the real send's build: its ``excluded`` games were selected
    but never offered, so they count in the total and are listed. A game is
    delivered when each of its ROM items was sent, or was already on the
    receiver while something else of it was sent.
    """
    sent = set(result.get("sent") or ())
    reasons = {
        entry.get("item_id"): entry.get("reason")
        for entry in result.get("skipped") or () if isinstance(entry, dict)
    }
    report = DeliveryReport()
    for game in built.manifest["games"]:
        roms = sorted(
            (item for item in game["items"] if item["kind"] == KIND_ROM),
            key=lambda item: not is_main_rom(item),
        )
        unsent = [item for item in roms if item["id"] not in sent]
        missing = [item for item in unsent if reasons.get(item["id"]) != SkipReason.EXISTS_SKIP]
        anything_sent = any(item["id"] in sent for item in game["items"])
        if not missing and anything_sent:
            report.delivered += 1
            continue
        # The main ROM's reason first; a ROM already there only when it is all.
        reason = reasons.get((missing or unsent)[0]["id"]) if unsent else None
        report.missing.append({"title": game["title"], "console": game["console"], "reason": reason,
                               "excluded": False})
    for entry in built.excluded:
        rom = entry["rom"]
        title = rom.get("name") or Path(str(rom.get("path", ""))).stem
        report.missing.append({"title": title, "console": rom.get("console", ""), "reason": entry["reason"],
                               "excluded": True})
    report.total = len(built.manifest["games"]) + len(built.excluded)
    return report


def receive_report(plan, unchecked=()):
    """What a finished receive added, from the plan that was accepted.

    Games in ``unchecked`` (game ids) were left out by the user on the offer
    page: they are neither listed nor counted.
    """
    unchecked = set(unchecked)
    report = DeliveryReport()
    for game in plan.games:
        if game.game_id in unchecked:
            continue
        report.total += 1
        if game_delivered(game.rom_status, {decision.action for decision in game.decisions}):
            report.delivered += 1
            continue
        report.missing.append({"title": game.title, "console": game.console, "reason": _receive_reason(game),
                               "excluded": False})
    return report


def _receive_reason(game):
    if game.rom_status == ROM_EXISTING:
        return SkipReason.EXISTS_SKIP
    rom = next((d for d in game.decisions if d.kind == KIND_ROM and d.reason), None)
    if rom is not None:
        return rom.reason
    return next((d.reason for d in game.decisions if d.reason), game.absent_reason)
