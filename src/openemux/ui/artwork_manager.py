"""Per-ROM artwork manager (issue #77).

One window, three tabs. Cover and Label search the same provider chain the
bulk sync uses (issue #76) and show every image found, one click to pick.
Import brings a file from the computer -- drag-and-drop or a chooser -- with
crop/flip/rotate applied to a working copy, never to the source file.

Temporary downloads and the import working copy live in a per-window folder
under the XDG cache dir, removed when the window closes.
"""

import logging
import shutil
import uuid
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk

from openemux.core import artwork_search
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.hasher import compute_crc32
from openemux.core.library_view import ZOOM_LEVELS, scale_spacing
from openemux.core.scraper import COVER_ART, LABEL_ART, SUPPORTED_COVER_EXTS, save_local_art
from openemux.ui.grid import GRID_SPACING, FixedSizePicture, cover_size_for_console
from threading import Thread

logger = logging.getLogger(__name__)

_KIND_BY_PAGE = {
    "cover": (COVER_ART_TYPE_BOXART, COVER_ART),
    "label": (COVER_ART_TYPE_CARTRIDGE_LABEL, LABEL_ART),
}

#: Results are laid out like the library's own shelf, at the largest zoom the
#: grid offers: this is where a cover is judged, so it is worth the room.
_RESULT_ZOOM = ZOOM_LEVELS[-1]


class _SearchTab(Gtk.Box):
    """Name/hash fields, search buttons, and the results grid for one kind."""

    def __init__(self, manager, page_id):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.manager = manager
        self.page_id = page_id
        self.art_kind, self.art_dir = _KIND_BY_PAGE[page_id]
        self._search_seq = 0
        self._candidates = {}
        self._running = False
        t = manager.t

        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        fields = Gtk.Grid(column_spacing=8, row_spacing=8)
        fields.attach(Gtk.Label(label=t("artwork.search.name"), xalign=0), 0, 0, 1, 1)
        self.name_entry = Gtk.Entry(hexpand=True, text=manager.rom.get("name", ""))
        fields.attach(self.name_entry, 1, 0, 1, 1)
        fields.attach(Gtk.Label(label=t("artwork.search.hash"), xalign=0), 0, 1, 1, 1)
        self.hash_entry = Gtk.Entry(hexpand=True, editable=False)
        self.hash_entry.set_placeholder_text(t("artwork.search.hash.computing"))
        fields.attach(self.hash_entry, 1, 1, 1, 1)
        self.append(fields)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.by_name_btn = Gtk.Button(label=t("artwork.search.by_name"))
        self.by_name_btn.connect("clicked", lambda _b: self._start_search(by_hash=False))
        buttons.append(self.by_name_btn)
        self.by_hash_btn = Gtk.Button(label=t("artwork.search.by_hash"))
        self.by_hash_btn.set_sensitive(False)
        self.by_hash_btn.connect("clicked", lambda _b: self._start_search(by_hash=True))
        buttons.append(self.by_hash_btn)
        # Only up while a search runs: a provider chain can take a while, and
        # the only way out used to be closing the window.
        self.cancel_btn = Gtk.Button(label=t("artwork.search.cancel"))
        self.cancel_btn.add_css_class("destructive-action")
        self.cancel_btn.set_visible(False)
        self.cancel_btn.connect("clicked", lambda _b: self._cancel_search())
        buttons.append(self.cancel_btn)
        self.spinner = Gtk.Spinner()
        buttons.append(self.spinner)
        self.status = Gtk.Label(xalign=0, hexpand=True)
        self.status.add_css_class("dim-label")
        buttons.append(self.status)
        self.append(buttons)

        self.results = Gtk.FlowBox()
        self.results.set_valign(Gtk.Align.START)
        self.results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results.set_homogeneous(False)
        # Same lattice as the library grid, so a result reads exactly like the
        # card it is going to become.
        self.results.add_css_class("rom-grid")
        spacing = scale_spacing(GRID_SPACING, _RESULT_ZOOM)
        self.results.set_column_spacing(spacing)
        self.results.set_row_spacing(spacing)
        self.results.connect("selected-children-changed", self._sync_selection_marks)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.results)
        self.append(scroller)

        self._prefill_hash()

    # -- hash prefill ------------------------------------------------------
    def _prefill_hash(self):
        rom_path = self.manager.rom.get("path")
        if not rom_path:
            self.hash_entry.set_placeholder_text("")
            return

        def _worker():
            try:
                digest = compute_crc32(rom_path)
            except OSError:
                digest = ""
            GLib.idle_add(self._set_hash, digest)

        Thread(target=_worker, daemon=True).start()

    def _set_hash(self, digest):
        if digest:
            self.hash_entry.set_text(digest)
            # A hash that lands mid-search must not re-arm the button the
            # running search just disabled.
            self.by_hash_btn.set_sensitive(not self._running)
        else:
            self.hash_entry.set_placeholder_text("")
        return False

    # -- searching ---------------------------------------------------------
    def _start_search(self, by_hash):
        self._search_seq += 1
        seq = self._search_seq
        self._candidates.clear()
        while (child := self.results.get_child_at_index(0)) is not None:
            self.results.remove(child)
        self._set_running(True)
        self.status.set_text(self.manager.t("artwork.search.running"))

        dest = self.manager.temp_dir / f"{self.page_id}-{seq}"
        rom = self.manager.rom

        artwork_search.search_artwork_async(
            console=rom["console"],
            rom_name=self.name_entry.get_text().strip() or rom["name"],
            sync_settings=self.manager.sync_settings,
            art_kind=self.art_kind,
            dest_dir=dest,
            rom_path=rom.get("path") if by_hash else None,
            on_result=lambda cand, s=seq: GLib.idle_add(self._add_result, s, cand),
            should_cancel=lambda s=seq: s != self._search_seq or self.manager.closed,
            on_done=lambda results, s=seq: GLib.idle_add(self._search_done, s, len(results)),
        )

    def _add_result(self, seq, candidate):
        if seq != self._search_seq:
            return False
        try:
            texture = Gdk.Texture.new_from_filename(str(candidate.path))
        except GLib.Error:
            return False

        width, height = cover_size_for_console(self.manager.rom.get("console"), _RESULT_ZOOM)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("rom-card")

        # The check sits on top of the artwork so the picked image says so
        # itself, instead of leaving the selection to a thin outline.
        overlay = Gtk.Overlay()
        picture = FixedSizePicture(width, height)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.add_css_class("rom-cover")
        picture.set_paintable(texture)
        overlay.set_child(picture)
        check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        check.set_pixel_size(48)
        check.set_halign(Gtk.Align.CENTER)
        check.set_valign(Gtk.Align.CENTER)
        check.add_css_class("artwork-check")
        check.set_visible(False)
        overlay.add_overlay(check)
        card.append(overlay)

        provider = Gtk.Label(label=self.manager.t(f"artwork.provider.{candidate.provider}"))
        provider.add_css_class("dim-label")
        provider.add_css_class("caption")
        card.append(provider)

        child = Gtk.FlowBoxChild()
        child.set_child(card)
        child.candidate = candidate
        child.check = check
        child.card = card
        self.results.append(child)
        if len(self._candidates) == 0:
            self.results.select_child(child)
        self._candidates[id(child)] = candidate
        self._sync_selection_marks()
        return False

    def _sync_selection_marks(self, *_args):
        """Show the check on the selected result, and only on that one."""
        selected = {id(child) for child in self.results.get_selected_children()}
        index = 0
        while (child := self.results.get_child_at_index(index)) is not None:
            index += 1
            chosen = id(child) in selected
            check = getattr(child, "check", None)
            card = getattr(child, "card", None)
            if check is not None:
                check.set_visible(chosen)
            if card is None:
                continue
            if chosen:
                card.add_css_class("rom-card-selected")
            else:
                card.remove_css_class("rom-card-selected")

    def _cancel_search(self):
        """Drop the running search: the sequence bump is what stops it.

        Every callback the search holds is bound to the sequence it started
        with, so bumping it makes the worker's ``should_cancel`` true and
        discards whatever is already in flight toward the UI.
        """
        self._search_seq += 1
        logger.info("artwork search cancelled: page=%s", self.page_id)
        self._set_running(False)
        self.status.set_text(self.manager.t("artwork.search.cancelled"))

    def _set_running(self, running):
        self._running = running
        self.cancel_btn.set_visible(running)
        self.by_name_btn.set_sensitive(not running)
        self.by_hash_btn.set_sensitive(not running and bool(self.hash_entry.get_text()))
        if running:
            self.spinner.start()
        else:
            self.spinner.stop()

    def _search_done(self, seq, count):
        if seq != self._search_seq:
            return False
        self._set_running(False)
        key = "artwork.search.none" if count == 0 else "artwork.search.found"
        self.status.set_text(self.manager.t(key, count=count))
        return False

    def selected_candidate(self):
        selected = self.results.get_selected_children()
        if not selected:
            return None
        return getattr(selected[0], "candidate", None)


class _PreviewArea(Gtk.DrawingArea):
    """Pixbuf preview that owns its geometry, so crop coordinates map 1:1.

    Draws the working pixbuf scaled to fit and, in crop mode, a draggable
    rectangle with corner handles. Everything is in widget coordinates and
    converted to pixbuf pixels only when the crop is applied.
    """

    HANDLE = 12
    MIN_SIZE = 24

    def __init__(self):
        super().__init__()
        self.pixbuf = None
        self.crop_mode = False
        self.crop_rect = None  # (x, y, w, h) in widget coords
        self._drag = None
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", lambda *_a: setattr(self, "_drag", None))
        self.add_controller(drag)

    # -- geometry ----------------------------------------------------------
    def _image_box(self, width=None, height=None):
        """Where the scaled pixbuf sits inside the widget: (x, y, w, h, scale)."""
        if self.pixbuf is None:
            return None
        w = width if width is not None else self.get_width()
        h = height if height is not None else self.get_height()
        if w <= 0 or h <= 0:
            return None
        pw, ph = self.pixbuf.get_width(), self.pixbuf.get_height()
        scale = min(w / pw, h / ph, 1.0)
        iw, ih = pw * scale, ph * scale
        return ((w - iw) / 2, (h - ih) / 2, iw, ih, scale)

    def set_pixbuf(self, pixbuf):
        self.pixbuf = pixbuf
        self.crop_rect = None
        self.queue_draw()

    def set_crop_mode(self, enabled):
        self.crop_mode = enabled
        box = self._image_box()
        if enabled and box:
            x, y, w, h, _ = box
            inset_w, inset_h = w * 0.1, h * 0.1
            self.crop_rect = [x + inset_w, y + inset_h, w - 2 * inset_w, h - 2 * inset_h]
        else:
            self.crop_rect = None
        self.queue_draw()

    def crop_in_pixbuf_coords(self):
        box = self._image_box()
        if not (box and self.crop_rect and self.pixbuf):
            return None
        bx, by, bw, bh, scale = box
        x, y, w, h = self.crop_rect
        px = max(0, int((x - bx) / scale))
        py = max(0, int((y - by) / scale))
        pw = min(self.pixbuf.get_width() - px, int(w / scale))
        ph = min(self.pixbuf.get_height() - py, int(h / scale))
        if pw <= 0 or ph <= 0:
            return None
        return px, py, pw, ph

    # -- drawing -----------------------------------------------------------
    def _draw(self, _area, cr, width, height):
        box = self._image_box(width, height)
        if not box:
            return
        x, y, w, h, scale = box
        cr.save()
        cr.translate(x, y)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.paint()
        cr.restore()

        if not (self.crop_mode and self.crop_rect):
            return
        rx, ry, rw, rh = self.crop_rect
        # Dim everything outside the crop rectangle.
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.rectangle(x, y, w, h)
        cr.rectangle(rx, ry + rh, rw, -rh)  # negative height punches the hole
        cr.set_fill_rule(1)  # EVEN_ODD
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(2)
        cr.rectangle(rx, ry, rw, rh)
        cr.stroke()
        half = self.HANDLE / 2
        for cx, cy in self._corners():
            cr.rectangle(cx - half, cy - half, self.HANDLE, self.HANDLE)
        cr.fill()

    def _corners(self):
        x, y, w, h = self.crop_rect
        return [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]

    # -- interaction ---------------------------------------------------------
    def _on_drag_begin(self, _gesture, start_x, start_y):
        if not (self.crop_mode and self.crop_rect):
            return
        for index, (cx, cy) in enumerate(self._corners()):
            if abs(start_x - cx) <= self.HANDLE and abs(start_y - cy) <= self.HANDLE:
                self._drag = ("corner", index, list(self.crop_rect))
                return
        x, y, w, h = self.crop_rect
        if x <= start_x <= x + w and y <= start_y <= y + h:
            self._drag = ("move", None, list(self.crop_rect))

    def _on_drag_update(self, _gesture, offset_x, offset_y):
        if not (self._drag and self.crop_rect):
            return
        mode, index, origin = self._drag
        box = self._image_box()
        if not box:
            return
        bx, by, bw, bh, _ = box
        x, y, w, h = origin
        if mode == "move":
            x = min(max(x + offset_x, bx), bx + bw - w)
            y = min(max(y + offset_y, by), by + bh - h)
        else:
            # Corners: 0=TL 1=TR 2=BL 3=BR. Opposite corner stays anchored.
            x2, y2 = x + w, y + h
            if index in (0, 2):
                x = min(max(x + offset_x, bx), x2 - self.MIN_SIZE)
            else:
                x2 = max(min(x2 + offset_x, bx + bw), x + self.MIN_SIZE)
            if index in (0, 1):
                y = min(max(y + offset_y, by), y2 - self.MIN_SIZE)
            else:
                y2 = max(min(y2 + offset_y, by + bh), y + self.MIN_SIZE)
            w, h = x2 - x, y2 - y
        self.crop_rect = [x, y, w, h]
        self.queue_draw()


class _ImportTab(Gtk.Box):
    """Drop/choose an image, edit a working copy, pick the destination."""

    def __init__(self, manager, label_supported):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.manager = manager
        self._original = None
        self.pixbuf = None
        t = manager.t

        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Drop area / add button.
        drop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        drop_box.add_css_class("card")
        drop_box.set_size_request(-1, 72)
        drop_label = Gtk.Label(label=t("artwork.import.drop_hint"))
        drop_label.add_css_class("dim-label")
        drop_label.set_vexpand(True)
        drop_label.set_valign(Gtk.Align.CENTER)
        drop_box.append(drop_label)
        add_btn = Gtk.Button(label=t("artwork.import.add"), halign=Gtk.Align.CENTER)
        add_btn.set_margin_bottom(8)
        add_btn.connect("clicked", lambda _b: self._choose_file())
        drop_box.append(add_btn)
        self.append(drop_box)

        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop)
        self.add_controller(target)

        # Preview and edit actions.
        self.preview = _PreviewArea()
        self.append(self.preview)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.CENTER)
        self.crop_toggle = Gtk.ToggleButton(label=t("artwork.import.crop"))
        self.crop_toggle.connect("toggled", self._on_crop_toggled)
        actions.append(self.crop_toggle)
        self.crop_apply = Gtk.Button(label=t("artwork.import.crop_apply"))
        self.crop_apply.set_visible(False)
        self.crop_apply.connect("clicked", lambda _b: self._apply_crop())
        actions.append(self.crop_apply)
        for icon, tooltip, handler in (
            ("object-flip-horizontal-symbolic", t("artwork.import.flip_h"),
             lambda: self._transform(lambda p: p.flip(True))),
            ("object-flip-vertical-symbolic", t("artwork.import.flip_v"),
             lambda: self._transform(lambda p: p.flip(False))),
            ("object-rotate-left-symbolic", t("artwork.import.rotate_left"),
             lambda: self._transform(
                 lambda p: p.rotate_simple(GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE))),
            ("object-rotate-right-symbolic", t("artwork.import.rotate_right"),
             lambda: self._transform(
                 lambda p: p.rotate_simple(GdkPixbuf.PixbufRotation.CLOCKWISE))),
        ):
            btn = Gtk.Button(icon_name=icon)
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", lambda _b, fn=handler: fn())
            actions.append(btn)
        reset = Gtk.Button(label=t("artwork.import.reset"))
        reset.connect("clicked", lambda _b: self._reset())
        actions.append(reset)
        self._action_bar = actions
        actions.set_sensitive(False)
        self.append(actions)

        # Destination selector.
        dest_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dest_box.set_halign(Gtk.Align.CENTER)
        dest_box.append(Gtk.Label(label=t("artwork.import.destination")))
        model = Gtk.StringList()
        self._dest_dirs = [COVER_ART]
        model.append(t("artwork.import.destination.cover"))
        if label_supported:
            model.append(t("artwork.import.destination.label"))
            self._dest_dirs.append(LABEL_ART)
        self.dest_dropdown = Gtk.DropDown(model=model)
        dest_box.append(self.dest_dropdown)
        self.append(dest_box)

    def set_default_destination(self, art_dir):
        if art_dir in self._dest_dirs:
            self.dest_dropdown.set_selected(self._dest_dirs.index(art_dir))

    def destination_dir(self):
        return self._dest_dirs[self.dest_dropdown.get_selected()]

    # -- loading -----------------------------------------------------------
    def _choose_file(self):
        chooser = Gtk.FileChooserDialog(
            title=self.manager.t("artwork.import.add"),
            transient_for=self.manager,
            modal=True,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_button(self.manager.t("dialog.cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(self.manager.t("dialog.start"), Gtk.ResponseType.ACCEPT)
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        for ext in SUPPORTED_COVER_EXTS:
            img_filter.add_pattern(f"*.{ext}")
            img_filter.add_pattern(f"*.{ext.upper()}")
        chooser.add_filter(img_filter)

        def _on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_file()
                if selected and selected.get_path():
                    self.load_file(selected.get_path())
            dialog.destroy()

        chooser.connect("response", _on_response)
        chooser.show()

    def _on_drop(self, _target, value, _x, _y):
        files = value.get_files() if isinstance(value, Gdk.FileList) else []
        for gfile in files:
            path = gfile.get_path()
            if path and self.load_file(path):
                return True
        return False

    def load_file(self, path):
        suffix = Path(path).suffix.lower().lstrip(".")
        if suffix not in SUPPORTED_COVER_EXTS:
            self.manager.toast(self.manager.t("toast.cover.invalid_extension"))
            return False
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
        except GLib.Error:
            self.manager.toast(self.manager.t("toast.cover.invalid_extension"))
            return False
        self._original = pixbuf
        self.pixbuf = pixbuf
        self.preview.set_pixbuf(pixbuf)
        self.crop_toggle.set_active(False)
        self._action_bar.set_sensitive(True)
        return True

    # -- edits ---------------------------------------------------------------
    def _transform(self, operation):
        if self.pixbuf is None:
            return
        result = operation(self.pixbuf)
        if result is not None:
            self.pixbuf = result
            self.preview.set_pixbuf(result)
            self.crop_toggle.set_active(False)

    def _reset(self):
        if self._original is not None:
            self.pixbuf = self._original
            self.preview.set_pixbuf(self._original)
            self.crop_toggle.set_active(False)

    def _on_crop_toggled(self, toggle):
        self.preview.set_crop_mode(toggle.get_active())
        self.crop_apply.set_visible(toggle.get_active())

    def _apply_crop(self):
        rect = self.preview.crop_in_pixbuf_coords()
        if rect is None or self.pixbuf is None:
            return
        x, y, w, h = rect
        self._transform(lambda p: p.new_subpixbuf(x, y, w, h).copy())


class ArtworkManagerWindow(Adw.Window):
    """Search, pick or import artwork for a single ROM."""

    def __init__(self, win, rom, art_dir=COVER_ART, label_supported=False):
        super().__init__(transient_for=win, modal=False)
        self.win = win
        self.rom = rom
        self.t = win.t
        self.closed = False
        self.sync_settings = win.config_manager.get_cover_sync_settings()
        self.temp_dir = (
            Path(GLib.get_user_cache_dir()) / "openemux" / "artwork-manager" / uuid.uuid4().hex
        )
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.set_title(self.t("artwork.window.title", name=rom.get("name", "")))
        # Wide enough for two result cards side by side at the grid's top zoom.
        self.set_default_size(980, 720)

        stack = Adw.ViewStack()
        self.stack = stack
        self.cover_tab = _SearchTab(self, "cover")
        stack.add_titled_with_icon(
            self.cover_tab, "cover", self.t("artwork.tab.cover"), "image-x-generic-symbolic"
        )
        self.label_tab = None
        if label_supported:
            self.label_tab = _SearchTab(self, "label")
            stack.add_titled_with_icon(
                self.label_tab, "label", self.t("artwork.tab.label"), "insert-image-symbolic"
            )
        self.import_tab = _ImportTab(self, label_supported)
        stack.add_titled_with_icon(
            self.import_tab, "import", self.t("artwork.tab.import"), "document-open-symbolic"
        )
        self.import_tab.set_default_destination(art_dir)
        if art_dir == LABEL_ART and self.label_tab is not None:
            stack.set_visible_child_name("label")

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        footer = Gtk.ActionBar()
        cancel = Gtk.Button(label=self.t("dialog.cancel"))
        cancel.connect("clicked", lambda _b: self.close())
        footer.pack_start(cancel)
        done = Gtk.Button(label=self.t("artwork.action.done"))
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda _b: self._save(close_after=True))
        footer.pack_end(done)
        save = Gtk.Button(label=self.t("artwork.action.save"))
        save.connect("clicked", lambda _b: self._save(close_after=False))
        footer.pack_end(save)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(stack)
        view.add_bottom_bar(footer)
        self.set_content(view)

        self.connect("close-request", self._on_close_request)

    def toast(self, text):
        self.win._toast(text)

    # -- saving --------------------------------------------------------------
    def _save(self, close_after):
        page = self.stack.get_visible_child_name()
        try:
            if page in ("cover", "label"):
                saved = self._save_search_selection(page)
            else:
                saved = self._save_import()
        except (ValueError, GLib.Error, OSError) as exc:
            logger.warning("artwork manager save failed: %s", exc)
            self.toast(self.t("artwork.toast.save_failed"))
            return
        if not saved:
            self.toast(self.t("artwork.toast.nothing_selected"))
            return
        kind = saved
        key = "toast.label.updated" if kind == LABEL_ART else "toast.cover.updated"
        self.toast(self.t(key, name=self.rom.get("name", "")))
        self.win.refresh_rom_artwork(self.rom)
        if close_after:
            self.close()

    def _save_search_selection(self, page):
        tab = self.cover_tab if page == "cover" else self.label_tab
        candidate = tab.selected_candidate() if tab else None
        if candidate is None:
            return None
        save_local_art(
            Path(self.win.roms_path),
            self.rom["console"],
            self.rom["name"],
            candidate.path,
            tab.art_dir,
        )
        return tab.art_dir

    def _save_import(self):
        if self.import_tab.pixbuf is None:
            return None
        working = self.temp_dir / "import-result.png"
        self.import_tab.pixbuf.savev(str(working), "png", [], [])
        art_dir = self.import_tab.destination_dir()
        save_local_art(
            Path(self.win.roms_path), self.rom["console"], self.rom["name"], working, art_dir
        )
        return art_dir

    # -- teardown ------------------------------------------------------------
    def _on_close_request(self, _window):
        self.closed = True
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        return False
