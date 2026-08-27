"""The sidebar: the list of places to be in the library, and what each offers.

Rows for "All", "Favorites", the user's collections and every console with
ROMs; a hover button and a right-click menu on the ones where per-console
actions apply; the core, shader and layout submenus behind them; and the
footer's two entry points.

Seven hundred lines of `OpenEmuxWindow` (issue #237). What it needs from the
window is narrow and explicit -- see :class:`ConsoleSidebar` -- but it is a
two-way relationship, not a widget the window merely holds: selecting a row
is how the user navigates, and the menus act on the window's library.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk

from openemux.core.library_view import VIEW_MODES, normalize_view_mode
from openemux.core.shaders import normalize_shader_id
from openemux.core.systems import get_system_display_name
from openemux.ui.console_icons import console_icon
from openemux.ui.context_menu import (
    SEPARATOR,
    Submenu,
    build_context_popover,
    present_context_popover,
    unparent_when_idle,
)
from openemux.ui.scopes import (
    ALL_CONSOLES_ID,
    FAVORITES_ID,
    collection_slug,
    is_collection_scope,
    sidebar_row_ids,
)

logger = logging.getLogger(__name__)


class ConsoleSidebar:
    """Builds and owns the sidebar navigation page.

    Reads from the window: ``t``, ``_translatable``, ``config_manager``,
    ``collection_manager``, ``core_catalog``, ``shader_catalog``,
    ``visible_consoles``, ``current_console``, ``roms_path``.

    Calls back into it for: row selection (``_on_console_selected``), the
    primary menu widget, the collection prompts, rescans, cover syncs,
    preferences, the file manager, toasts, and re-rendering a console page
    whose layout just changed.
    """

    def __init__(self, window):
        self.win = window
        #: The row whose menu is open, so its hover button does not fade out
        #: from under the pointer mid-click.
        self._menu_row = None
        #: The console the open menu applies to; the action group is one per
        #: window, so the actions read the console from here.
        self._menu_console = None
        self._action_group = None
        self.page = self._build()

    # ----- construction ---------------------------------------------------
    def _build(self):
        t = self.win.t
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        title = Adw.WindowTitle.new(t("sidebar.header"), "")
        self.win._translatable(lambda: title.set_title(t("sidebar.header")))
        header.set_title_widget(title)
        header.pack_end(self.win._build_primary_menu())
        toolbar.add_top_bar(header)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-selected", self.win._on_console_selected)
        self.list_box.add_css_class("navigation-sidebar")
        self._install_empty_area_menu(self.list_box)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self.list_box)
        toolbar.set_content(scroll)

        # Two entry points side by side, so neither has to be guessed at.
        #
        # "New playlist" alone was being read as "import ROMs here" -- it was
        # the only button in the sidebar, and the header's import icon was not
        # being found. Importing now has a labelled button of its own, and the
        # playlist button is hidden until there is something to put in one:
        # offering to group games before any game exists is what made it look
        # like the way to add them.
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer_box.set_homogeneous(True)
        footer_box.set_margin_top(6)
        footer_box.set_margin_bottom(6)
        footer_box.set_margin_start(6)
        footer_box.set_margin_end(6)

        import_button = Gtk.Button()
        import_content = Adw.ButtonContent(icon_name="folder-download-symbolic")
        self.win._translatable(lambda: import_content.set_label(t("sidebar.import")))
        import_button.set_child(import_content)
        import_button.add_css_class("flat")
        import_button.connect("clicked", lambda _b: self.win.imports.open_picker())
        footer_box.append(import_button)

        self.new_collection_button = Gtk.Button()
        new_collection_content = Adw.ButtonContent(icon_name="list-add-symbolic")
        self.win._translatable(
            lambda: new_collection_content.set_label(t("collections.new"))
        )
        self.new_collection_button.set_child(new_collection_content)
        self.new_collection_button.add_css_class("flat")
        self.new_collection_button.connect(
            "clicked", lambda _b: self.win._prompt_new_collection()
        )
        footer_box.append(self.new_collection_button)

        footer = Adw.Bin()
        footer.set_child(footer_box)
        toolbar.add_bottom_bar(footer)

        page = Adw.NavigationPage.new(toolbar, t("sidebar.header"))
        page.set_tag("sidebar")
        self.rebuild([])
        return page

    def sync_footer(self):
        """Offer playlists only once there are games to put in one.

        On an empty library it was the sidebar's only button, which is most of
        why people read it as the way to add games.
        """
        self.new_collection_button.set_visible(bool(self.win.visible_consoles))

    # ----- rows -----------------------------------------------------------
    def label_for(self, console_id):
        t = self.win.t
        if console_id == ALL_CONSOLES_ID:
            return t("sidebar.all")
        if console_id == FAVORITES_ID:
            return t("sidebar.favorites")
        if is_collection_scope(console_id):
            slug = collection_slug(console_id)
            return self.win.collection_manager.get_name(slug) or slug
        return f"{console_id} - {get_system_display_name(console_id)}"

    def rebuild(self, consoles):
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)

        slugs = [c["slug"] for c in self.win.collection_manager.list_collections()]
        for row_id in sidebar_row_ids(consoles, slugs):
            self._append_row(row_id)

    def _append_row(self, console_id):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(16)
        box.set_margin_end(16)

        box.append(console_icon(console_id))

        name = Gtk.Label(label=self.label_for(console_id))
        name.set_halign(Gtk.Align.START)
        name.set_hexpand(True)
        box.append(name)

        # All and Favorites are virtual views: no per-console actions apply, so
        # they get neither the button nor the right-click menu.
        if console_id not in (ALL_CONSOLES_ID, FAVORITES_ID):
            menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
            menu_button.add_css_class("flat")
            menu_button.add_css_class("sidebar-menu-button")
            menu_button.set_valign(Gtk.Align.CENTER)
            menu_button.set_tooltip_text(self.win.t("context.more_options"))
            # Keep the button in the layout at all times and only fade it in on
            # hover: toggling visibility would add/remove its (taller than the
            # icon) allocation, growing the row and shoving the list below it.
            # can-target follows opacity so the invisible button catches no clicks.
            menu_button.set_opacity(0)
            menu_button.set_can_target(False)
            menu_button.connect(
                "clicked", lambda b, cid=console_id, r=row: self._on_menu_button(b, r, cid)
            )
            box.append(menu_button)

            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda _c, _x, _y, b=menu_button: self._show_menu_button(b))
            motion.connect("leave", lambda _c, b=menu_button, r=row: self._hide_menu_button(b, r))
            row.add_controller(motion)
            row.menu_button = menu_button

        row.set_child(box)
        row.id = console_id
        self._install_context_menu(row, console_id)
        self.list_box.append(row)

    def find_row(self, console_id):
        row = self.list_box.get_first_child()
        while row:
            if getattr(row, "id", None) == console_id:
                return row
            row = row.get_next_sibling()
        return None

    def select(self, console_id):
        """Highlight ``console_id``'s row; True when there was one to select."""
        row = self.find_row(console_id)
        if row is None:
            return False
        self.list_box.select_row(row)
        return True

    def reselect_current(self):
        """Restore the sidebar highlight after the row list was rebuilt."""
        if not self.win.current_console:
            return
        self.select(self.win.current_console)

    def selected_id(self):
        row = self.list_box.get_selected_row()
        return getattr(row, "id", None) if row else None

    # ----- the hover button -----------------------------------------------
    def _show_menu_button(self, button):
        button.set_opacity(1)
        button.set_can_target(True)

    def _hide_menu_button(self, button, row):
        # Keep it while its own menu is open, so it does not vanish mid-click.
        if self._menu_row is not row:
            button.set_opacity(0)
            button.set_can_target(False)

    def _on_menu_button(self, button, row, console_id):
        # Coordinates are relative to the row, which the popover is parented to.
        ok, bounds = button.compute_bounds(row)
        x, y = (bounds.get_x(), bounds.get_y() + bounds.get_height()) if ok else (0, 0)
        self._show_menu(row, console_id, x, y)

    # ----- the menus ------------------------------------------------------
    def _install_empty_area_menu(self, listbox):
        """Right-clicking empty sidebar space offers New collection…

        The per-row gestures claim their own clicks, so this only fires when the
        release lands below the last row, where ``get_row_at_y`` finds nothing.
        """
        gesture = Gtk.GestureClick()
        gesture.set_button(Gdk.BUTTON_SECONDARY)

        def _released(g, _n, _x, y, lb=listbox):
            if lb.get_row_at_y(int(y)) is not None:
                return
            g.set_state(Gtk.EventSequenceState.CLAIMED)
            popover = build_context_popover([
                (
                    self.win.t("collections.new"),
                    (lambda: self.win._prompt_new_collection()),
                    "list-add-symbolic",
                ),
            ])
            popover.set_parent(lb)
            popover.set_pointing_to(Gdk.Rectangle(x=int(_x), y=int(y), width=1, height=1))
            popover.connect("closed", unparent_when_idle)
            present_context_popover(popover)

        gesture.connect("released", _released)
        listbox.add_controller(gesture)

    def _install_context_menu(self, row, console_id):
        # "All" and "Favorites" are virtual views: none of the actions apply.
        if console_id in (ALL_CONSOLES_ID, FAVORITES_ID):
            return
        gesture = Gtk.GestureClick()
        gesture.set_button(Gdk.BUTTON_SECONDARY)
        # Popping up on "pressed" makes the matching release close the popover
        # again, so the menu only stays while the button is held. Wait for the
        # release, and claim the sequence so the row does not also react.
        gesture.connect(
            "released",
            lambda g, _n, x, y, cid=console_id, r=row: (
                g.set_state(Gtk.EventSequenceState.CLAIMED),
                self._show_menu(r, cid, x, y),
            ),
        )
        row.add_controller(gesture)

    def _show_menu(self, row, console_id, x, y):
        """Right-click actions for a sidebar console.

        The first three mirror the header-bar buttons; "open folder" is the one
        thing that only makes sense per console.
        """
        if is_collection_scope(console_id):
            self._show_collection_menu(row, console_id, x, y)
            return

        t = self.win.t
        self._menu_console = console_id
        self._ensure_action_group()

        entries = [
            # Not the header button's wording: there the action is "reload what
            # is on screen", here it is "rescan this console's folder".
            (t("context.rescan.console"), "sidebar.refresh", "view-refresh-symbolic"),
            (t("header.import"), "sidebar.import", "document-open-symbolic"),
            (t("header.sync_covers"), "sidebar.sync-covers", "image-x-generic-symbolic"),
            SEPARATOR,
            self._layout_submenu(console_id),
        ]
        # Appended one at a time: SEPARATOR *is* None, so a submenu that has
        # nothing to offer would otherwise draw itself as a divider.
        for submenu in (
            self._core_submenu(console_id),
            self._shader_submenu(console_id),
        ):
            if submenu is not None:
                entries.append(submenu)
        # Next to Core and Shader: the third per-console setting, and the only
        # one that needs the dialog. The header button reaches the same page,
        # but only while that console is the one on screen.
        entries.append(
            (t("context.controller"), "sidebar.controller", "input-gaming-symbolic")
        )
        entries.append(SEPARATOR)
        entries.append(
            (t("context.open_folder"), "sidebar.open-folder", "folder-open-symbolic")
        )
        self._present(build_context_popover(entries), row, x, y)

    def _show_collection_menu(self, row, scope, x, y):
        t = self.win.t
        slug = collection_slug(scope)
        popover = build_context_popover([
            (
                t("collections.rename"),
                (lambda s=slug: self.win._prompt_rename_collection(s)),
                "document-edit-symbolic",
            ),
            SEPARATOR,
            self._layout_submenu(scope),
            SEPARATOR,
            (
                t("collections.delete"),
                (lambda s=slug: self.win._confirm_delete_collection(s)),
                "user-trash-symbolic",
            ),
        ])
        self._present(popover, row, x, y)

    def _present(self, popover, row, x, y):
        popover.set_parent(row)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        self._menu_row = row
        popover.connect("closed", lambda p, r=row: self._on_popover_closed(p, r))
        present_context_popover(popover)

    def _on_popover_closed(self, popover, row):
        if self._menu_row is row:
            self._menu_row = None
        button = getattr(row, "menu_button", None)
        # The pointer may have left the row while the menu was up; the button
        # only belongs on the hovered row. Fade it out (never hide it) so the
        # row keeps its height -- see _append_row.
        if button is not None and not row.get_state_flags() & Gtk.StateFlags.PRELIGHT:
            button.set_opacity(0)
            button.set_can_target(False)
        unparent_when_idle(popover)

    # ----- the per-console submenus ---------------------------------------
    def _core_submenu(self, console):
        """The console's default core, from the sidebar.

        The same setting Preferences > Cores edits, one right-click away from
        the console it applies to. Returns None when nothing is installed for
        this system: an empty submenu is worse than no submenu.
        """
        t = self.win.t
        cores = self.win.core_catalog.cores_for_console(console)
        if not cores:
            return None

        override = self.win.config_manager.get_console_core_override(console)
        automatic = cores[0].display_name
        entries = [
            (
                t("context.core.automatic", core=automatic),
                (lambda c=console: self.set_console_core(c, None)),
                "emblem-ok-symbolic" if not override else None,
            ),
            SEPARATOR,
        ]
        for core in cores:
            entries.append(
                (
                    core.display_name,
                    (lambda c=console, f=core.filename: self.set_console_core(c, f)),
                    "emblem-ok-symbolic" if override == core.filename else None,
                )
            )
        return Submenu(
            t("context.console.core"), entries, "application-x-executable-symbolic"
        )

    def set_console_core(self, console, core_filename):
        self.win.config_manager.set_console_core_override(console, core_filename)
        if core_filename:
            # The same warning Preferences gives: a core whose BIOS is missing
            # will fail at launch, and that is worth knowing when picking it.
            self.win._warn_missing_bios_for_core(console, core_filename)
        label = (
            self.win.core_catalog.display_name_for(core_filename)
            if core_filename
            else self.win.t("context.core.automatic_short")
        )
        logger.info(
            "sidebar context action: core console=%s core=%s", console, core_filename
        )
        self.win._toast(
            self.win.t("toast.console_core_set", console=console, core=label)
        )

    def _shader_submenu(self, console):
        """The console's default shader, from the sidebar."""
        config = self.win.config_manager
        show_all = bool(config.get_shader_settings().get("show_all_shaders", False))
        options = self.win.shader_catalog.get_options(show_all=show_all)
        if not options:
            return None

        current = normalize_shader_id(config.get_shader_for_console(console))
        entries = []
        for shader_id, label in options:
            entries.append(
                (
                    label,
                    (lambda c=console, s=shader_id: self.set_console_shader(c, s)),
                    "emblem-ok-symbolic" if shader_id == current else None,
                )
            )
        return Submenu(
            self.win.t("context.console.shader"), entries, "applications-graphics-symbolic"
        )

    def set_console_shader(self, console, shader_id):
        shader_id = normalize_shader_id(shader_id)
        self.win.config_manager.set_shader_for_console(console, shader_id)
        logger.info(
            "sidebar context action: shader console=%s shader=%s", console, shader_id
        )
        self.win._toast(
            self.win.t(
                "toast.console_shader_set",
                console=console,
                shader=self.win.shader_catalog.label_for_shader(shader_id),
            )
        )

    def _layout_submenu(self, console):
        """The Layout ▸ shortcut on a sidebar console, mirroring the header menu.

        The fastest route when setting several consoles in a row: it acts on the
        console clicked, whatever page is on screen.
        """
        t = self.win.t
        config = self.win.config_manager
        follows = not config.has_scope_override(console)
        resolved = config.get_display_settings(console)
        entries = [
            (
                t("layout.use_global"),
                (lambda c=console: self._use_global_layout(c)),
                "emblem-ok-symbolic" if follows else None,
            ),
            SEPARATOR,
        ]
        for mode in VIEW_MODES:
            entries.append(
                (
                    t(f"view_mode.{mode}"),
                    (lambda c=console, m=mode: self._set_view_mode(c, m)),
                    "emblem-ok-symbolic" if resolved["view_mode"] == mode else None,
                )
            )
        return Submenu(t("layout.menu"), entries, "view-grid-symbolic")

    def _set_view_mode(self, console, mode):
        self.win.config_manager.set_scope_display(
            console, "view_mode", normalize_view_mode(mode)
        )
        self._after_layout_changed(console)

    def _use_global_layout(self, console):
        self.win.config_manager.clear_scope_override(console)
        self._after_layout_changed(console)

    def _after_layout_changed(self, console):
        # Re-render that console's page so the change shows even if it is not the
        # page on screen, and re-sync the header controls when it is.
        self.win.pages.ensure_loaded(console)
        if console == self.win.current_console:
            self.win._refresh_scope_settings()

    # ----- the action group behind the menu -------------------------------
    def _ensure_action_group(self):
        if self._action_group is not None:
            return
        group = Gio.SimpleActionGroup()
        for name, handler in (
            ("refresh", self._act_refresh),
            ("import", self._act_import),
            ("sync-covers", self._act_sync_covers),
            ("controller", self._act_controller),
            ("open-folder", self._act_open_folder),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            group.add_action(action)
        self.win.insert_action_group("sidebar", group)
        self._action_group = group

    def _act_refresh(self, _action, _param):
        console = self._menu_console
        logger.info("sidebar context action: refresh console=%s", console)
        if console in (ALL_CONSOLES_ID, FAVORITES_ID):
            self.win._rescan_all_consoles(show_toast=True)
        else:
            self.win._rescan_single_console(console, show_toast=True)

    def _act_import(self, _action, _param):
        logger.info("sidebar context action: import console=%s", self._menu_console)
        self.win.imports.open_picker()

    def _act_sync_covers(self, _action, _param):
        console = self._menu_console
        logger.info("sidebar context action: sync_covers console=%s", console)
        if console in (ALL_CONSOLES_ID, FAVORITES_ID):
            self.win._start_cover_sync(scope="all", selected_console=None)
        else:
            self.win._start_cover_sync(scope="console", selected_console=console)

    def _act_controller(self, _action, _param):
        console = self._menu_console
        logger.info("sidebar context action: controller console=%s", console)
        self.win._open_preferences(page="input", console=console)

    def _act_open_folder(self, _action, _param):
        console = self._menu_console
        logger.info("sidebar context action: open_folder console=%s", console)
        self.win._open_path_in_file_manager(self.win.roms_path / console)
