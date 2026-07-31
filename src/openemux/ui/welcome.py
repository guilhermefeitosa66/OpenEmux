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

from openemux.i18n import LANGUAGE_META, SUPPORTED_LOCALES, normalize_locale  # noqa: E402

#: (slide id, sidebar icon, illustration filename). The heading/body strings are
#: looked up as ``welcome.<id>.title`` / ``welcome.<id>.body``.
SLIDES = [
    ("welcome", "start-here-symbolic", "welcome.png"),
    ("import", "folder-download-symbolic", "import.png"),
    # A sequence: the view modes are a thing you *see* change, so the slide
    # cycles them instead of describing them (issue: welcome refresh).
    ("views", "view-grid-symbolic",
     ("views-1.png", "views-2.png", "views-3.png", "views-4.png")),
    ("covers", "image-x-generic-symbolic", "covers.png"),
    ("shaders", "applications-graphics-symbolic", "shaders.png"),
    ("shortcuts", "preferences-desktop-keyboard-symbolic", "shortcuts.png"),
    ("gamepad", "input-gaming-symbolic", "gamepad.png"),
]

_IMAGE_DIR = Path(__file__).parent / "assets" / "images" / "welcome"

#: How long each frame of a multi-image slide is held, and how long the
#: slide across to the next one takes.
SLIDESHOW_INTERVAL_MS = 2500
SLIDESHOW_TRANSITION_MS = 400


class WelcomeAssistant(Adw.Dialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.t = win.t
        self.config = win.config_manager
        self._syncing = False
        # Same idea as the main window: register the callback that retranslates
        # a widget next to the widget, so the language picker below can change
        # the whole assistant without anything being forgotten.
        self._retranslate = []
        self._slideshows = {}
        self._slideshow_timer = None

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

        self.connect("closed", lambda _d: self._stop_slideshow())

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
            label = Gtk.Label()
            self._translatable(
                lambda l=label, s=slide_id: l.set_label(self.t(f"welcome.{s}.title"))
            )
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

        frames = (image,) if isinstance(image, str) else tuple(image)
        pictures = [self._picture(name) for name in frames]
        pictures = [p for p in pictures if p is not None]
        if len(pictures) == 1:
            box.append(pictures[0])
        elif pictures:
            # A stack rather than a carousel: this one advances on its own and
            # must not steal the horizontal drag that moves between slides.
            stack = Gtk.Stack()
            stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
            stack.set_transition_duration(SLIDESHOW_TRANSITION_MS)
            for index, picture in enumerate(pictures):
                stack.add_named(picture, str(index))
            stack.set_visible_child_name("0")
            self._slideshows[slide_id] = (stack, len(pictures))
            box.append(stack)

        heading = Gtk.Label()
        heading.add_css_class("title-1")
        heading.set_halign(Gtk.Align.CENTER)
        heading.set_justify(Gtk.Justification.CENTER)
        heading.set_wrap(True)
        self._translatable(lambda: heading.set_label(self.t(f"welcome.{slide_id}.title")))
        box.append(heading)

        body = Gtk.Label()
        body.set_wrap(True)
        body.set_justify(Gtk.Justification.CENTER)
        body.set_halign(Gtk.Align.CENTER)
        body.add_css_class("body")
        self._translatable(lambda: body.set_label(self.t(f"welcome.{slide_id}.body")))
        box.append(body)

        if slide_id == "welcome":
            box.append(self._build_language_row())

        clamp.set_child(box)
        scroller.set_child(clamp)
        return scroller

    def _picture(self, name):
        path = _IMAGE_DIR / name
        if not path.exists():
            return None
        picture = Gtk.Picture.new_for_filename(str(path))
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_can_shrink(True)
        picture.set_size_request(-1, 300)
        picture.add_css_class("welcome-image")
        return picture

    def _translatable(self, apply):
        apply()
        self._retranslate.append(apply)

    # ----- language -------------------------------------------------------
    def _build_language_row(self):
        """Pick the language before reading any of the tour.

        Someone who cannot read the first slide cannot find Settings either,
        so the choice belongs here rather than only in Settings > System.
        """
        self._locales = list(SUPPORTED_LOCALES)
        # Flag + native name in one string, the same shape Settings uses, so
        # the two pickers read alike. Native names never need retranslating.
        dropdown = Gtk.DropDown.new_from_strings([
            f"{LANGUAGE_META.get(code, LANGUAGE_META['en'])['flag']} "
            f"{LANGUAGE_META.get(code, LANGUAGE_META['en'])['native_name']}"
            for code in self._locales
        ])
        current = normalize_locale(self.win.locale)
        # Seeding the selection emits notify::selected; without the guard the
        # dialog "changes" the language to whatever it already was the moment
        # it opens, toast and all.
        self._syncing = True
        dropdown.set_selected(
            self._locales.index(current) if current in self._locales else 0
        )
        self._syncing = False
        # Centred and only as wide as it needs to be: a full-width row here
        # would read as a setting rather than a one-off choice.
        dropdown.set_halign(Gtk.Align.CENTER)
        dropdown.set_size_request(210, -1)
        dropdown.set_margin_top(4)
        dropdown.connect("notify::selected", self._on_language_selected)
        self._language_row = dropdown
        return dropdown

    def _on_language_selected(self, *_args):
        if self._syncing:
            return
        index = self._language_row.get_selected()
        if not (0 <= index < len(self._locales)):
            return
        locale = self._locales[index]
        if locale == normalize_locale(self.win.locale):
            return
        # The window retranslates itself and re-reads the library; the
        # assistant then replays its own registrations.
        self.win._apply_language_change(locale)
        self.t = self.win.t
        self.set_title(self.t("welcome.title"))
        for apply in self._retranslate:
            apply()

    # ----- slideshow ------------------------------------------------------
    def _stop_slideshow(self):
        if self._slideshow_timer is not None:
            GLib.source_remove(self._slideshow_timer)
            self._slideshow_timer = None

    def _start_slideshow(self, slide_id):
        """Cycle a multi-image slide, but only while it is the one on screen."""
        self._stop_slideshow()
        entry = self._slideshows.get(slide_id)
        if entry is None:
            return
        stack, count = entry

        def _advance():
            nxt = (int(stack.get_visible_child_name()) + 1) % count
            stack.set_visible_child_name(str(nxt))
            return True

        self._slideshow_timer = GLib.timeout_add(SLIDESHOW_INTERVAL_MS, _advance)

    def _build_bottom_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class("toolbar")
        bar.set_margin_top(8)
        bar.set_margin_bottom(12)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        # Positive framing that mirrors Preferences -> System: checked = show.
        self.show_startup_check = Gtk.CheckButton(label=self.t("welcome.show_on_startup"))
        self.show_startup_check.set_active(self.config.get_show_welcome_on_startup())
        self.show_startup_check.connect("toggled", self._on_show_startup_toggled)
        bar.append(self.show_startup_check)

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
        # Every path that moves between slides ends here, so this is the one
        # place that has to know which slide is on screen.
        self._start_slideshow(SLIDES[max(0, min(index, len(SLIDES) - 1))][0])

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

    def _on_show_startup_toggled(self, check):
        self.config.set_show_welcome_on_startup(check.get_active())
