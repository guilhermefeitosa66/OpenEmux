"""The Share Nearby dialog: pick what to send and to whom (#589).

Opened for a game, a selection or a whole console ("send"), or from the
Import button's menu to only be visible ("receive"). While it is open this device is
discoverable -- the coordinator keeps the service up -- and it lists the other
devices as discovery finds them. Choosing one sends; the waiting, progress
and result pages then replace the list, so Back cannot leave a transfer.
"""

from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.core.share.display import (
    format_date,
    format_size,
    paths_label,
    platform_icon,
    platform_key,
    plural,
)
from openemux.core.share import qr
from openemux.core.share.protocol import (
    BEACON_PORT,
    PROTOCOL_VERSION,
    SERVER_PORT,
    ErrorCode,
    SkipReason,
    format_fingerprint,
)
from openemux.core.share.selection import (
    BATTERY,
    COVER,
    DETAILS,
    GAME,
    LABEL,
    STATES,
    apply_selection,
    inventory,
    kept_roms,
    summarize,
)
from openemux.core.systems import get_system_display_name
from openemux.ui.icons import SHARE_ICON
from openemux.ui.share_coordinator import STATE_FAILED
from openemux.ui.share_pages import (
    confirm_cancel,
    ProgressPage,
    WaitingPage,
    label,
    page,
    pill,
    result_page,
    show_page,
)

#: Seconds without a compatible device before the dialog explains why.
NOTHING_FOUND_SECONDS = 15
#: How many titles the "What to Send" summary names before "and N more".
SUMMARY_TITLES = 3

_GROUP_TITLES = {
    GAME: "share.items.game",
    BATTERY: "share.items.battery",
    STATES: "share.items.states",
    COVER: "share.items.cover",
    LABEL: "share.items.label",
    DETAILS: "share.items.details",
}
_EXCLUDED = {
    SkipReason.UNIT_INCOMPLETE: "share.excluded.unit_incomplete",
    SkipReason.UNSUPPORTED_CONSOLE: "share.excluded.unsupported_console",
    SkipReason.TOO_MANY_ITEMS: "share.excluded.too_many_items",
}
_ADDRESS_ERRORS = {
    ErrorCode.BAD_REQUEST: "share.address.invalid",
    ErrorCode.UNREACHABLE: "share.address.unreachable",
    ErrorCode.FINGERPRINT_MISMATCH: "share.address.mismatch",
}


class ShareDialog(Adw.Dialog):
    def __init__(self, coordinator, roms=None):
        super().__init__()
        self.coordinator = coordinator
        self.win = coordinator.win
        self.t = self.win.t
        self.roms = list(roms) if roms else None
        self.mode = "send" if self.roms else "receive"
        self.built = None
        self.unchecked = set()
        self._selection_cache = None
        self.transfer = None
        self.peer = None
        self.games_sent = 0
        self.nothing_found = False
        self._empty_timer = None
        self._peer_rows = []
        self._syncing = False
        self.is_unavailable = False
        self.what_page = None
        self.address_page = None
        self.waiting = None
        self.progress = None

        self.set_content_width(480)
        self.set_content_height(640)
        self.set_title(self.t("share.title" if self.mode == "send" else "share.title.receive"))
        self.nav = Adw.NavigationView()
        self.toasts = Adw.ToastOverlay(child=self.nav)
        self.set_child(self.toasts)
        self.root_page = self._build_root()
        self.nav.add(self.root_page)
        self.connect("close-attempt", self._on_close_attempt)
        self.connect("closed", self._on_closed)

        coordinator.open_screen(self)
        if self.mode == "send" and self._available():
            coordinator.inventory(self.roms, self._on_inventory)
        self.on_share_state()
        # The service may be running already (another share screen, or the
        # grace period of one that closed): the devices it knows by now will
        # not be announced as a change again.
        self.on_peers_changed()

    # -- root ------------------------------------------------------------

    def _available(self):
        return self.coordinator.availability()["share"] == "ok"

    def _build_root(self):
        t = self.t
        self.stack = Gtk.Stack()
        self.stack.add_named(self._build_unavailable(), "unavailable")

        prefs = Adw.PreferencesPage()
        if self.mode == "send":
            what_group = Adw.PreferencesGroup()
            self.what_row = Adw.ActionRow(title=t("share.what"), subtitle=t("share.what.preparing"))
            self.what_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.what_row.set_activatable(False)
            self.what_row.connect("activated", lambda _r: self._push_what())
            what_group.add(self.what_row)
            prefs.add(what_group)

            self.devices_group = Adw.PreferencesGroup(title=t("share.devices"))
            self.spinner = Gtk.Spinner(spinning=True)
            self.devices_group.set_header_suffix(self.spinner)
            prefs.add(self.devices_group)
        else:
            ready_group = Adw.PreferencesGroup()
            self.ready = Adw.StatusPage(
                icon_name=SHARE_ICON, title=t("share.receive.title"),
            )
            self.ready.add_css_class("compact")
            ready_group.add(self.ready)
            prefs.add(ready_group)

        this_group = Adw.PreferencesGroup(title=t("share.this_device"))
        self.visible_row = Adw.ActionRow(subtitle=t("share.visible_hint"))
        self.visible_row.set_use_markup(False)
        this_group.add(self.visible_row)
        address_row = Adw.ActionRow(title=t("share.address.title"))
        address_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        address_row.set_activatable(True)
        address_row.connect("activated", lambda _r: self._push_address())
        this_group.add(address_row)
        self.address_row = address_row
        prefs.add(this_group)
        self.stack.add_named(prefs, "main")

        if self.mode == "send":
            self.stack.add_named(self._build_empty(), "empty")
        return page(self.get_title(), self.stack, "root")

    def _build_unavailable(self):
        self.unavailable = Adw.StatusPage(
            icon_name="dialog-error-symbolic", title=self.t("share.unavailable.title"),
        )
        return self.unavailable

    def _build_empty(self):
        t = self.t
        status = Adw.StatusPage(
            icon_name="network-wireless-no-route-symbolic",
            title=t("share.empty.title"),
            description=t("share.empty.body"),
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(label(t("share.empty.isolation"), css=("dim-label",)))
        box.append(label(t("share.empty.firewall", tcp=SERVER_PORT, udp=BEACON_PORT), css=("dim-label",)))
        connect = pill(t("share.address.button"))
        connect.connect("clicked", lambda _b: self._push_address())
        box.append(connect)
        searching = Gtk.Box(spacing=6)
        searching.set_halign(Gtk.Align.CENTER)
        searching.append(Gtk.Spinner(spinning=True))
        searching.append(label(t("share.empty.searching"), css=("dim-label",)))
        box.append(searching)
        status.set_child(box)
        self.empty = status
        return status

    def on_share_state(self):
        """The coordinator started, failed or stopped the service."""
        availability = self.coordinator.availability()["share"]
        if availability != "ok":
            name = availability.partition(":")[2]
            self._show_unavailable(self.t("share.unavailable.body", name=name))
            return
        if self.coordinator.state == STATE_FAILED:
            self._show_unavailable(self.t("share.unavailable.failed"))
            return
        self.is_unavailable = False
        name = self.coordinator.device_name()
        self.visible_row.set_title(self.t("share.visible_as", name=name))
        if self.mode == "receive":
            self.ready.set_description(self.t("share.receive.body", name=name))
            self.stack.set_visible_child_name("main")
        self._refresh_address()
        self._update_root()

    def _show_unavailable(self, description):
        self.is_unavailable = True
        self.unavailable.set_description(description)
        self.stack.set_visible_child_name("unavailable")

    # -- devices ---------------------------------------------------------

    def on_peers_changed(self):
        if self.mode != "send":
            return
        for row in self._peer_rows:
            self.devices_group.remove(row)
        self._peer_rows = []
        for peer in self.coordinator.peers():
            row = self._peer_row(peer)
            self.devices_group.add(row)
            self._peer_rows.append(row)
        self._update_root()

    def _peer_row(self, peer):
        t = self.t
        row = Adw.ActionRow(title=peer.name)
        row.set_use_markup(False)
        row.add_prefix(Gtk.Image.new_from_icon_name(platform_icon(peer.platform)))
        row.peer = peer
        if peer.compatible:
            row.set_subtitle(t(
                "share.device.subtitle", platform=t(platform_key(peer.platform)),
                paths=paths_label(peer.paths, t),
            ))
            row.set_activatable(True)
            row.connect("activated", lambda _r, p=peer: self._send(p))
        else:
            row.set_subtitle(t("share.device.incompatible", peer=peer.v, ours=PROTOCOL_VERSION))
            row.add_suffix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            row.set_sensitive(False)
        return row

    def _compatible_peers(self):
        return [row for row in self._peer_rows if row.peer.compatible]

    def _something_selected(self):
        return self.built is not None and summarize(self._selection())["files"] > 0

    def _update_root(self):
        if self.mode != "send" or self.is_unavailable:
            return
        selected = self._something_selected()
        for row in self._compatible_peers():
            row.set_sensitive(selected)
            row.set_tooltip_text(None if selected else self.t("share.device.nothing_selected"))
        if self._compatible_peers():
            self._stop_empty_timer()
            self.nothing_found = False
        elif self._empty_timer is None and not self.nothing_found:
            self._empty_timer = self.coordinator.timeout_add(NOTHING_FOUND_SECONDS, self._on_nothing_found)
        self.stack.set_visible_child_name("empty" if self.nothing_found else "main")

    def _on_nothing_found(self):
        self._empty_timer = None
        self.nothing_found = True
        self._update_root()
        return False

    def _stop_empty_timer(self):
        if self._empty_timer is not None:
            self.coordinator.source_remove(self._empty_timer)
            self._empty_timer = None

    # -- what to send ----------------------------------------------------

    def _on_inventory(self, built):
        if built is None:
            built = apply_selection(_EmptyBuilt(), ())
        self.built = built
        self.what_row.set_activatable(True)
        self._update_summary()

    def _selection(self):
        # Every toggle and every peer change asks; the copy is of the whole
        # manifest, so it is made once per choice the user makes.
        unchecked = frozenset(self.unchecked)
        cache = self._selection_cache
        if cache is None or cache[0] is not self.built or cache[1] != unchecked:
            cache = (self.built, unchecked, apply_selection(self.built, self.unchecked))
            self._selection_cache = cache
        return cache[2]

    def _update_summary(self):
        t = self.t
        summary = summarize(self._selection())
        titles = summary["titles"]
        names = ", ".join(titles[:SUMMARY_TITLES])
        if len(titles) > SUMMARY_TITLES:
            names = t("share.what.more", titles=names, count=len(titles) - SUMMARY_TITLES)
        files = plural(t, summary["files"], "share.files.one", "share.files.many")
        self.what_row.set_subtitle(f"{names} · {files}" if names else files)
        self.root_page.window_title.set_subtitle(plural(
            t, summary["games"], "share.subtitle.one", "share.subtitle.many",
            size=format_size(summary["size"], t),
        ))
        if self.what_page is not None:
            self.total_label.set_label(f"{format_size(summary['size'], t)} · {files}")
        self._update_root()

    def _push_what(self):
        t = self.t
        games, excluded = inventory(self.built)
        group = Adw.PreferencesGroup()
        self._game_checks = {}
        for game in games:
            group.add(self._game_row(game))
        for entry in excluded:
            row = Adw.ActionRow(title=entry["title"])
            row.set_use_markup(False)
            row.set_subtitle(t(_EXCLUDED.get(entry["reason"], "share.excluded.invalid_item")))
            check = Gtk.CheckButton(active=False)
            row.add_prefix(check)
            row.set_sensitive(False)
            group.add(row)
        prefs = Adw.PreferencesPage()
        prefs.add(group)

        bottom = Gtk.Box(spacing=12)
        bottom.set_margin_top(6)
        bottom.set_margin_bottom(6)
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        totals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        totals.set_hexpand(True)
        totals.append(label(t("share.items.total"), css=("heading",), xalign=0))
        self.total_label = label("", css=("dim-label", "numeric"), xalign=0)
        totals.append(self.total_label)
        bottom.append(totals)
        done = Gtk.Button(label=t("share.items.done"))
        done.add_css_class("suggested-action")
        done.set_valign(Gtk.Align.CENTER)
        done.connect("clicked", lambda _b: self.nav.pop())
        bottom.append(done)

        self.what_page = page(t("share.what"), prefs, "what", bottom=bottom)
        self.what_page.connect("hidden", self._on_what_hidden)
        self.nav.push(self.what_page)
        self._update_summary()

    def _on_what_hidden(self, _page):
        self.what_page = None

    def _game_row(self, game):
        t = self.t
        key = game["key"]
        row = Adw.ExpanderRow(title=game["title"])
        row.set_use_markup(False)
        row.set_subtitle(f"{get_system_display_name(game['console'])} · {format_size(game['size'], t)}")
        parent = Gtk.CheckButton()
        parent.set_valign(Gtk.Align.CENTER)
        parent.connect("toggled", lambda b, k=key: self._on_game_toggled(k, b))
        row.add_prefix(parent)
        children = {}
        for category, group in game["groups"].items():
            child = Adw.ActionRow(title=t(_GROUP_TITLES[category]), subtitle=self._group_detail(category, group))
            child.set_use_markup(False)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.connect("toggled", lambda b, k=key, c=category: self._on_group_toggled(k, c, b))
            child.add_prefix(check)
            child.set_activatable_widget(check)
            row.add_row(child)
            children[category] = (child, check)
        self._game_checks[key] = (parent, children)
        self._sync_checks(key)
        return row

    def _group_detail(self, category, group):
        t = self.t
        size = format_size(group["size"], t)
        if category == GAME:
            name = group["name"] if group["count"] == 1 else plural(
                t, group["count"], "share.files.one", "share.files.many")
            return f"{name} · {size}"
        if category == BATTERY:
            return f"{t('share.items.battery_saved', date=format_date(group['mtime']))} · {size}"
        if category == STATES:
            return plural(t, group["count"], "share.items.states_hint.one", "share.items.states_hint.many")
        if category == DETAILS:
            return t("share.items.details_hint")
        return size

    def _sync_checks(self, key):
        parent, children = self._game_checks[key]
        self._syncing = True
        try:
            game_on = (key, GAME) not in self.unchecked
            mixed = game_on and any((key, c) in self.unchecked for c in children)
            parent.set_active(game_on)
            parent.set_inconsistent(mixed)
            for category, (child, check) in children.items():
                check.set_active((key, category) not in self.unchecked)
                child.set_sensitive(game_on or category == GAME)
        finally:
            self._syncing = False

    def _on_game_toggled(self, key, button):
        if self._syncing:
            return
        if button.get_active():
            self.unchecked = {pair for pair in self.unchecked if pair[0] != key}
        else:
            self.unchecked.add((key, GAME))
        self._sync_checks(key)
        self._update_summary()

    def _on_group_toggled(self, key, category, button):
        if self._syncing:
            return
        if button.get_active():
            self.unchecked.discard((key, category))
        else:
            self.unchecked.add((key, category))
        self._sync_checks(key)
        self._update_summary()

    # -- connect by address ----------------------------------------------

    def _push_address(self):
        t = self.t
        prefs = Adw.PreferencesPage()
        this_group = Adw.PreferencesGroup(title=t("share.this_device"), description=t("share.address.this_hint"))
        self.qr_picture = Gtk.Picture()
        self.qr_picture.set_size_request(168, 168)
        self.qr_picture.set_halign(Gtk.Align.CENTER)
        self.qr_picture.set_can_shrink(True)
        self.qr_picture.add_css_class("share-qr")
        self.qr_picture.update_property([Gtk.AccessibleProperty.LABEL], [t("share.address.qr")])
        self.qr_picture.set_visible(False)
        this_group.add(self.qr_picture)
        self.host_row = Adw.ActionRow(title=t("share.address.address"))
        self.host_row.set_subtitle_selectable(True)
        self.host_row.add_css_class("property")
        this_group.add(self.host_row)
        self.fp_row = Adw.ActionRow(title=t("share.address.fingerprint"))
        self.fp_row.set_subtitle_selectable(True)
        self.fp_row.add_css_class("property")
        this_group.add(self.fp_row)
        copy = Gtk.Button(label=t("share.address.copy"))
        copy.set_halign(Gtk.Align.CENTER)
        copy.set_margin_top(12)
        copy.add_css_class("pill")
        copy.connect("clicked", lambda _b: self._copy_address())
        self.copy_button = copy
        this_group.add(copy)
        prefs.add(this_group)

        other = Adw.PreferencesGroup(title=t("share.address.other"), description=t("share.address.other_hint"))
        self.address_entry = Adw.EntryRow(title=t("share.address.address"))
        self.address_entry.set_show_apply_button(True)
        self.address_entry.connect("apply", lambda _e: self._connect_address())
        other.add(self.address_entry)
        self.address_error = label("", css=("error",), xalign=0)
        self.address_error.set_margin_top(6)
        self.address_error.set_visible(False)
        other.add(self.address_error)
        prefs.add(other)

        self.address_page = page(t("share.address.title"), prefs, "address")
        self.address_page.connect("hidden", self._on_address_hidden)
        self.nav.push(self.address_page)
        self._refresh_address()

    def _on_address_hidden(self, _page):
        self.address_page = None

    def _refresh_address(self):
        if self.address_page is None:
            return
        address = self.coordinator.address()
        if address is None:
            self.host_row.set_subtitle("…")
            self.fp_row.set_subtitle("…")
            self.copy_button.set_sensitive(False)
            return
        host, port, fp, uri = address
        self.host_row.set_subtitle(f"{host}:{port}")
        self.fp_row.set_subtitle(format_fingerprint(fp))
        self.fp_row.set_tooltip_text(fp)
        self.copy_button.set_sensitive(True)
        png = qr.png_bytes(uri)
        if png is not None:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
            self.qr_picture.set_paintable(texture)
            self.qr_picture.set_visible(True)

    def _copy_address(self):
        address = self.coordinator.address()
        if address is None:
            return
        self.get_clipboard().set(address[3])
        self.toasts.add_toast(Adw.Toast(title=self.t("share.address.copied")))

    def _connect_address(self):
        if not self.address_entry.get_editable():
            return
        self.address_error.set_visible(False)
        # Read-only, not insensitive: an insensitive entry drops the focus,
        # and the keys typed next would reach the library behind the dialog.
        self.address_entry.set_editable(False)
        self.coordinator.connect_address(self.address_entry.get_text(), self._on_address_connected)

    def _on_address_connected(self, error, host):
        if self.address_page is None:
            return
        self.address_entry.set_editable(True)
        if error is None:
            self.address_entry.set_text("")
            self.nav.pop_to_tag("root")
            return
        key = _ADDRESS_ERRORS.get(error)
        text = self.t(key, host=host or "") if key else self.t(
            "share.error.incompatible_version" if error == ErrorCode.INCOMPATIBLE_VERSION else "share.error.generic",
            device=host or "",
        )
        self.address_error.set_label(text)
        self.address_error.set_visible(True)

    # -- sending ---------------------------------------------------------

    def _send(self, peer):
        if self.coordinator.busy or not self._something_selected():
            return
        self.peer = peer
        self.games_sent = summarize(self._selection())["games"]
        self.waiting = WaitingPage(self.t, peer.name, self._cancel)
        show_page(self, self.waiting.page)
        self.set_can_close(False)
        roms = kept_roms(self.built, self.roms, self.unchecked)
        self.transfer = self.coordinator.send(peer, roms, set(self.unchecked), self)

    def _cancel(self):
        if self.transfer is not None:
            self.transfer.cancel()

    def on_send_code(self, code):
        if self.waiting is not None:
            self.waiting.show_code(code)

    def on_send_progress(self, progress):
        if self.progress is None:
            self.progress = ProgressPage(
                self.t, self.t("share.progress.sending", device=self.peer.name), self._cancel,
            )
            show_page(self, self.progress.page)
        self.progress.update(progress)

    def on_send_done(self, result):
        self.transfer = None
        self.set_can_close(True)
        self.result = result_page(
            self.t, result, self.peer.name, receiving=False, games=self.games_sent,
            on_close=self.close,
        )
        show_page(self, self.result)

    # -- closing ---------------------------------------------------------

    def _on_close_attempt(self, _dialog):
        self.close_alert = confirm_cancel(self, self.t, self._cancel_and_close)

    def _cancel_and_close(self):
        self._cancel()
        self.set_can_close(True)
        self.close()

    def _on_closed(self, _dialog):
        self._stop_empty_timer()
        self.coordinator.close_screen(self)


class _EmptyBuilt:
    """What an inventory that failed leaves: nothing to send."""

    manifest = {"games": [], "total_size": 0, "file_count": 0}
    sources = {}
    excluded = []
