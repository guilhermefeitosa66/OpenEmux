"""The Incoming Games dialog: another device wants to send games (#589).

Presented over whatever is open when an offer arrives. It shows who is
sending, what, how big, and the verification code both screens must agree
on; the user accepts or declines before the offer expires. Closing it -- the
close button, Escape -- declines, and focus starts on "Decline", so a stray
Enter never accepts. Conflicts with the library and a lack of disk space are
dealt with here, before anything is accepted.
"""

import html

from gi.repository import Adw, Gtk

from openemux.core.share.display import (
    POLICY_KEYS,
    conflict_rows,
    countdown,
    format_date,
    format_size,
    item_kind_label,
    manifest_items,
    plural,
    reason_key,
)
from openemux.core.share.placement import ACTION_SEND, DEFAULT_POLICIES, ROM_EXISTING, ROM_PLACED
from openemux.core.share.protocol import KIND_STATE, OFFER_TTL, ErrorCode, ShareError, SkipReason
from openemux.core.systems import get_system_display_name
from openemux.ui.share_pages import confirm_cancel, ProgressPage, code_label, label, page, result_page

#: Skip reasons the conflicts page lists under "Skipped": the ones that are
#: not the user's choice and not a file already there.
_LISTED_SKIPS = (
    SkipReason.INCOMPATIBLE_STATE,
    SkipReason.UNSUPPORTED_CONSOLE,
    SkipReason.INVALID_ITEM,
    SkipReason.UNIT_INCOMPLETE,
)


class IncomingOfferDialog(Adw.Dialog):
    def __init__(self, coordinator, offer):
        super().__init__()
        self.coordinator = coordinator
        self.win = coordinator.win
        self.t = self.win.t
        self.offer = offer
        self.device = offer.sender.get("name", "")
        self.overrides = {}
        self.answered = False
        self.transfer = None
        self.progress = None
        self.result = None
        self.deadline = coordinator.clock() + OFFER_TTL
        self.items = manifest_items(offer.manifest)
        self.plan = coordinator.plan(offer)
        self.conflicts = conflict_rows(coordinator.probe(offer), offer.manifest)

        self.set_content_width(480)
        self.set_content_height(720)
        self.set_title(self.t("share.offer.title"))
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self.root_page = self._build_root()
        self.nav.add(self.root_page)
        self._update_plan()
        self._tick_id = coordinator.timeout_add(1, self._tick)
        self.connect("close-attempt", self._on_close_attempt)
        self.connect("closed", self._on_closed)
        self.set_focus(self.decline_button)

    # -- the offer -------------------------------------------------------

    def _build_root(self):
        t = self.t
        games = self.offer.manifest.get("games", [])
        size = sum(item.get("size", 0) for _game, item in self.items.values())
        prefs = Adw.PreferencesPage()

        lead_group = Adw.PreferencesGroup()
        lead = label(t(
            "share.offer.lead", device=html.escape(self.device),
            games=plural(t, len(games), "share.offer.games.one", "share.offer.games.many"),
            size=format_size(size, t),
        ), markup=True)
        lead_group.add(lead)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.set_margin_top(12)
        for widget in (
            label(t("share.offer.code"), css=("caption-heading", "dim-label")),
            code_label(self.offer.code),
            label(t("share.offer.code_hint", device=self.device), css=("dim-label",)),
        ):
            widget.set_margin_start(12)
            widget.set_margin_end(12)
            card.append(widget)
        card.get_first_child().set_margin_top(12)
        card.get_last_child().set_margin_bottom(12)
        lead_group.add(card)
        prefs.add(lead_group)

        games_group = Adw.PreferencesGroup(title=t("share.offer.games"))
        for game in games:
            games_group.add(self._game_row(game))
        prefs.add(games_group)

        self.notes_group = Adw.PreferencesGroup()
        self.incompatible_note = label("", css=("warning",), xalign=0)
        self.notes_group.add(self.incompatible_note)
        self.unsupported_notes = []
        for game in self.plan.games:
            if any(d.reason == SkipReason.UNSUPPORTED_CONSOLE for d in game.decisions):
                note = label(t("share.offer.unsupported", title=game.title), css=("warning",), xalign=0)
                self.notes_group.add(note)
                self.unsupported_notes.append(note)
        self.review_row = Adw.ActionRow()
        self.review_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        self.review_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.review_row.set_activatable(True)
        self.review_row.connect("activated", lambda _r: self._push_conflicts())
        self.review_row.set_visible(bool(self.conflicts))
        if self.conflicts:
            count = len(self.conflicts)
            self.review_row.set_title(plural(t, count, "share.offer.review.one", "share.offer.review.many"))
        self.notes_group.add(self.review_row)
        self.space_error = self._space_label()
        self.notes_group.add(self.space_error)
        prefs.add(self.notes_group)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom.set_margin_top(6)
        bottom.set_margin_bottom(12)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        self.expires = label("", css=("dim-label", "numeric"))
        bottom.append(self.expires)
        buttons = Gtk.Box(spacing=12, homogeneous=True)
        self.decline_button = Gtk.Button(label=t("share.offer.decline"))
        self.decline_button.connect("clicked", lambda _b: self.decline())
        self.accept_button = Gtk.Button(label=t("share.offer.accept"))
        self.accept_button.add_css_class("suggested-action")
        self.accept_button.connect("clicked", lambda _b: self.accept())
        buttons.append(self.decline_button)
        buttons.append(self.accept_button)
        bottom.append(buttons)
        self._show_countdown()
        return page(t("share.offer.title"), prefs, "offer", bottom=bottom)

    def _game_row(self, game):
        t = self.t
        parts, states = [], 0
        for item in game.get("items", []):
            if item.get("kind") == KIND_STATE:
                states += 1
                continue
            text = item_kind_label(item.get("kind"), t)
            if text not in parts:
                parts.append(text)
        if states:
            parts.append(plural(t, states, "share.offer.states.one", "share.offer.states.many"))
        row = Adw.ActionRow(title=str(game.get("title", "")))
        row.set_use_markup(False)
        row.set_subtitle(f"{get_system_display_name(str(game.get('console', '')))} · {', '.join(parts)}")
        size = sum(item.get("size", 0) for item in game.get("items", []))
        row.add_suffix(label(format_size(size, t), css=("dim-label", "numeric"), wrap=False))
        return row

    def _space_label(self):
        widget = label("", css=("error",), xalign=0, markup=True)
        widget.set_accessible_role(Gtk.AccessibleRole.ALERT)
        widget.set_visible(False)
        return widget

    # -- the plan --------------------------------------------------------

    def _update_plan(self):
        t = self.t
        incompatible = sum(1 for d in self.plan.decisions() if d.reason == SkipReason.INCOMPATIBLE_STATE)
        self.incompatible_note.set_visible(bool(incompatible))
        if incompatible:
            self.incompatible_note.set_label(plural(
                t, incompatible, "share.offer.incompatible.one", "share.offer.incompatible.many"))
        self._update_space()

    def _update_space(self, checks=None):
        checks = self.plan.space_check() if checks is None else checks
        short = [check for check in checks if not check["ok"]]
        text = ""
        if short:
            t = self.t
            check = short[0]
            missing = check["needed"] + self.plan.reserve - check["free"]
            text = t(
                "share.space.body", needed=format_size(check["needed"], t), path=html.escape(check["path"]),
                free=format_size(check["free"], t), missing=format_size(missing, t),
            )
        for widget in self._space_labels():
            widget.set_markup(text)
            widget.set_visible(bool(short))
        self.accept_button.set_sensitive(not short and not self.answered)

    def _space_labels(self):
        labels = [self.space_error]
        if getattr(self, "conflicts_space", None) is not None:
            labels.append(self.conflicts_space)
        return labels

    def _push_conflicts(self):
        t = self.t
        prefs = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(description=t("share.conflicts.hint"))
        self.combo_rows = {}
        for row in self.conflicts:
            group.add(self._conflict_row(row))
        prefs.add(group)
        skipped = self._skipped_rows()
        if skipped:
            skipped_group = Adw.PreferencesGroup(title=t("share.conflicts.skipped"))
            for row in skipped:
                skipped_group.add(row)
            prefs.add(skipped_group)
        space_group = Adw.PreferencesGroup()
        self.conflicts_space = self._space_label()
        space_group.add(self.conflicts_space)
        prefs.add(space_group)
        conflicts_page = page(t("share.conflicts.title"), prefs, "conflicts")
        conflicts_page.connect("hidden", self._on_conflicts_hidden)
        self.nav.push(conflicts_page)
        self._update_space()

    def _on_conflicts_hidden(self, _page):
        self.conflicts_space = None

    def _conflict_row(self, row):
        t = self.t
        title = f"{row['game']} · {item_kind_label(row['kind'], t, slot=row['slot'])}"
        key = "share.conflicts.dates_newer" if row["newer"] else "share.conflicts.dates"
        combo = Adw.ComboRow(title=title, subtitle=t(
            key, yours=format_date(row["yours"]), incoming=format_date(row["incoming"])))
        combo.set_use_markup(False)
        policies = list(row["policies"])
        combo.set_model(Gtk.StringList.new([t(POLICY_KEYS[policy]) for policy in policies]))
        current = self.overrides.get(row["item_id"], DEFAULT_POLICIES[row["kind"]])
        combo.set_selected(policies.index(current) if current in policies else 0)
        combo.connect("notify::selected", lambda c, _p, r=row, ps=policies: self._on_policy(r, ps[c.get_selected()]))
        self.combo_rows[row["item_id"]] = combo
        return combo

    def _on_policy(self, row, policy):
        self.overrides[row["item_id"]] = policy
        self.plan = self.coordinator.plan(self.offer, self.overrides)
        self._update_plan()

    def _skipped_rows(self):
        t = self.t
        rows = []
        for decision in self.plan.decisions():
            if decision.reason not in _LISTED_SKIPS:
                continue
            game, item = self.items.get(decision.item_id, ({}, {}))
            state = item.get("state") or {}
            title = f"{game.get('title', '')} · {item_kind_label(decision.kind, t, slot=state.get('slot'))}"
            if decision.reason == SkipReason.INCOMPATIBLE_STATE and state.get("core"):
                subtitle = t("share.reason.incompatible_state_core", core=state["core"],
                             version=state.get("core_version", ""))
            else:
                subtitle = t(reason_key(decision.reason))
            action = Adw.ActionRow(title=title, subtitle=subtitle)
            action.set_use_markup(False)
            rows.append(action)
        return rows

    # -- the countdown ---------------------------------------------------

    def _remaining(self):
        return self.deadline - self.coordinator.clock()

    def _show_countdown(self):
        self.expires.set_label(self.t("share.offer.expires", time=countdown(self._remaining())))

    def _tick(self):
        if self.answered:
            self._tick_id = None
            return False
        if self._remaining() <= 0:
            self._tick_id = None
            # The server expired it already; nothing to answer.
            self.answered = True
            self.win._toast(self.t("share.offer.expired_toast", device=self.device))
            self.close()
            return False
        self._show_countdown()
        return True

    def _stop_tick(self):
        if self._tick_id is not None:
            self.coordinator.source_remove(self._tick_id)
            self._tick_id = None

    # -- answers ---------------------------------------------------------

    def decline(self):
        if not self.answered:
            self.answered = True
            self.coordinator.decline(self.offer.offer_id)
        self.close()

    def accept(self):
        if self.answered:
            return
        try:
            self.transfer = self.coordinator.accept(self.offer, self.plan, self)
        except ShareError as exc:
            if exc.code == ErrorCode.TOO_LARGE:
                self._update_space((exc.details or {}).get("space") or self.plan.space_check())
                return
            self.answered = True
            self._stop_tick()
            self._show_result({"status": "failed", "error": exc.code})
            return
        self.answered = True
        self._stop_tick()
        self.set_can_close(False)
        self.progress = ProgressPage(
            self.t, self.t("share.progress.receiving", device=self.device), self._cancel,
        )
        self.nav.replace([self.progress.page])

    def _cancel(self):
        if self.transfer is not None:
            self.transfer.cancel()

    def on_remote_cancel(self):
        """The sender gave up before this side answered."""
        if self.answered:
            return
        self.answered = True
        self._stop_tick()
        self._show_result({"status": ErrorCode.CANCELLED})

    def on_receive_progress(self, progress):
        if self.progress is not None:
            self.progress.update(progress)

    def on_receive_done(self, result):
        self.transfer = None
        self.set_can_close(True)
        self._show_result(result)

    def _received_games(self):
        return [
            game for game in self.plan.games
            if game.rom_status in ROM_PLACED + (ROM_EXISTING,)
            and any(d.action == ACTION_SEND for d in game.decisions)
        ]

    def _show_result(self, result):
        games = self._received_games()
        self.result = result_page(
            self.t, result, self.device, receiving=True, games=len(games),
            summary=self.coordinator.result_counts(result),
            on_close=self.close, on_show=self._show_in_library if games else None,
        )
        self.nav.replace([self.result])

    def _show_in_library(self):
        self.win.sidebar.select(self._received_games()[0].console)
        self.close()

    # -- closing ---------------------------------------------------------

    def _on_close_attempt(self, _dialog):
        self.close_alert = confirm_cancel(self, self.t, self._cancel_and_close)

    def _cancel_and_close(self):
        self._cancel()
        self.set_can_close(True)
        self.close()

    def _on_closed(self, _dialog):
        self._stop_tick()
        if not self.answered:
            self.answered = True
            self.coordinator.decline(self.offer.offer_id)
        self.coordinator.offer_closed(self)
