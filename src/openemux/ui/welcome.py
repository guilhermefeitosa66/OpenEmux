"""The Welcome Assistant: a slide-based onboarding tour.

Shown automatically on the first launch of the main window (see
``OpenEmuxWindow._maybe_show_welcome``), re-openable from the primary menu and
from Preferences -> System. Built as an ``Adw.Dialog`` (in-window, like
Preferences) with an ``Adw.Carousel`` of slides, a topic sidebar that jumps
straight to any slide, Back/Next controls with a page indicator, and a
"don't show again" toggle wired to ``ConfigManager``.

Slide copy is fully translatable (``prefs``-style i18n keys). The illustrations
are optional: a slide whose image asset is missing simply renders without one,
so the tour works before the screenshots are bundled.
"""
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

#: (slide id, sidebar icon, illustration filename). The heading/body strings are
#: looked up as ``welcome.<id>.title`` / ``welcome.<id>.body``.
SLIDES = [
    ("welcome", "start-here-symbolic", "welcome.png"),
    ("import", "folder-download-symbolic", "import.png"),
    ("views", "view-grid-symbolic", "views.png"),
    ("covers", "image-x-generic-symbolic", "covers.png"),
    ("shaders", "applications-graphics-symbolic", "shaders.png"),
    ("shortcuts", "preferences-desktop-keyboard-symbolic", "shortcuts.png"),
    ("gamepad", "input-gaming-symbolic", "gamepad.png"),
]

_IMAGE_DIR = Path(__file__).parent / "assets" / "images" / "welcome"


class WelcomeAssistant(Adw.Dialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.t = win.t
        self.config = win.config_manager
        self._syncing = False

        self.set_title(self.t("welcome.title"))
        self.set_content_width(900)
        self.set_content_height(640)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle.new(self.t("welcome.title"), ""))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(self._build_sidebar())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_hexpand(True)

        self.carousel = Adw.Carousel()
        self.carousel.set_hexpand(True)
        self.carousel.set_vexpand(True)
        self.carousel.set_allow_scroll_wheel(True)
        for slide_id, _icon, image in SLIDES:
            self.carousel.append(self._build_slide(slide_id, image))
        self.carousel.connect("page-changed", self._on_page_changed)
        content.append(self.carousel)

        content.append(self._build_bottom_bar())
        body.append(content)

        toolbar.set_content(body)
        self.set_child(toolbar)

        # Left/Right step through slides; Escape closes (Adw.Dialog default).
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self._select_index(0)

    # ----- construction ---------------------------------------------------
    def _build_sidebar(self):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(210, -1)

        self.topics = Gtk.ListBox()
        self.topics.add_css_class("navigation-sidebar")
        self.topics.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for slide_id, icon, _image in SLIDES:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(10)
            box.set_margin_bottom(10)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.append(Gtk.Image.new_from_icon_name(icon))
            label = Gtk.Label(label=self.t(f"welcome.{slide_id}.title"))
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(True)
            label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            box.append(label)
            row.set_child(box)
            self.topics.append(row)
        self.topics.connect("row-selected", self._on_topic_selected)
        scroller.set_child(self.topics)
        return scroller

    def _build_slide(self, slide_id, image):
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(560)
        clamp.set_margin_top(28)
        clamp.set_margin_bottom(28)
        clamp.set_margin_start(24)
        clamp.set_margin_end(24)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)

        image_path = _IMAGE_DIR / image
        if image_path.exists():
            picture = Gtk.Picture.new_for_filename(str(image_path))
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_can_shrink(True)
            picture.set_size_request(-1, 300)
            picture.add_css_class("welcome-image")
            box.append(picture)

        heading = Gtk.Label(label=self.t(f"welcome.{slide_id}.title"))
        heading.add_css_class("title-1")
        heading.set_halign(Gtk.Align.CENTER)
        heading.set_justify(Gtk.Justification.CENTER)
        heading.set_wrap(True)
        box.append(heading)

        body = Gtk.Label(label=self.t(f"welcome.{slide_id}.body"))
        body.set_wrap(True)
        body.set_justify(Gtk.Justification.CENTER)
        body.set_halign(Gtk.Align.CENTER)
        body.add_css_class("body")
        box.append(body)

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    def _build_bottom_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class("toolbar")
        bar.set_margin_top(8)
        bar.set_margin_bottom(12)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        self.dont_show_check = Gtk.CheckButton(label=self.t("welcome.dont_show_again"))
        self.dont_show_check.set_active(not self.config.get_show_welcome_on_startup())
        self.dont_show_check.connect("toggled", self._on_dont_show_toggled)
        bar.append(self.dont_show_check)

        dots = Adw.CarouselIndicatorDots()
        dots.set_carousel(self.carousel)
        dots.set_hexpand(True)
        dots.set_halign(Gtk.Align.CENTER)
        bar.append(dots)

        self.back_button = Gtk.Button(label=self.t("welcome.back"))
        self.back_button.connect("clicked", lambda _b: self._step(-1))
        bar.append(self.back_button)

        self.next_button = Gtk.Button(label=self.t("welcome.next"))
        self.next_button.add_css_class("suggested-action")
        self.next_button.connect("clicked", self._on_next)
        bar.append(self.next_button)
        return bar

    # ----- navigation -----------------------------------------------------
    def _current_index(self):
        return int(round(self.carousel.get_position()))

    def _select_index(self, index):
        index = max(0, min(index, len(SLIDES) - 1))
        self._syncing = True
        self.carousel.scroll_to(self.carousel.get_nth_page(index), True)
        self.topics.select_row(self.topics.get_row_at_index(index))
        self._syncing = False
        self._update_controls(index)

    def _step(self, delta):
        self._select_index(self._current_index() + delta)

    def _on_next(self, _button):
        index = self._current_index()
        if index >= len(SLIDES) - 1:
            self.close()
        else:
            self._select_index(index + 1)

    def _update_controls(self, index):
        self.back_button.set_sensitive(index > 0)
        last = index >= len(SLIDES) - 1
        self.next_button.set_label(
            self.t("welcome.finish") if last else self.t("welcome.next")
        )

    def _on_page_changed(self, _carousel, index):
        if self._syncing:
            return
        self._syncing = True
        self.topics.select_row(self.topics.get_row_at_index(index))
        self._syncing = False
        self._update_controls(index)

    def _on_topic_selected(self, _listbox, row):
        if self._syncing or row is None:
            return
        self._select_index(row.get_index())

    def _on_key(self, _controller, keyval, _keycode, _state):
        from gi.repository import Gdk

        if keyval in (Gdk.KEY_Right, Gdk.KEY_Page_Down):
            self._step(1)
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self._step(-1)
            return True
        return False

    def _on_dont_show_toggled(self, check):
        self.config.set_show_welcome_on_startup(not check.get_active())
