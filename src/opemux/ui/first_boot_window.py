import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from opemux.i18n import tr


class FirstBootWindow(Adw.ApplicationWindow):
    def __init__(self, application, locale="en", parent=None, **kwargs):
        super().__init__(application=application, **kwargs)
        self.locale = locale
        self.set_title(tr(self.locale, "bootstrap.title"))
        self.set_default_size(640, 260)
        self.set_resizable(False)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_modal(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_margin_top(28)
        outer.set_margin_bottom(28)
        outer.set_margin_start(28)
        outer.set_margin_end(28)
        self.set_content(outer)

        self.title_label = Gtk.Label(label=tr(self.locale, "bootstrap.title"))
        self.title_label.add_css_class("title-2")
        self.title_label.set_halign(Gtk.Align.START)
        outer.append(self.title_label)

        self.subtitle_label = Gtk.Label(label=tr(self.locale, "bootstrap.subtitle.initial"))
        self.subtitle_label.add_css_class("dim-label")
        self.subtitle_label.set_wrap(True)
        self.subtitle_label.set_halign(Gtk.Align.START)
        outer.append(self.subtitle_label)

        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.START)
        self.spinner.start()
        outer.append(self.spinner)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_fraction(0.0)
        self.progress.set_text("0%")
        outer.append(self.progress)

        self.status_label = Gtk.Label(label="")
        self.status_label.add_css_class("dim-label")
        self.status_label.set_halign(Gtk.Align.START)
        outer.append(self.status_label)

    def handle_event(self, event):
        event_type = event.get("type")
        if event_type in ("step_started", "step_skipped", "step_completed"):
            label_key = event.get("label_key")
            if label_key:
                self.subtitle_label.set_text(tr(self.locale, label_key))
            index = int(event.get("index", 0))
            total_steps = max(1, int(event.get("total_steps", 1)))
            fraction = min(1.0, max(0.0, index / total_steps))
            self.progress.set_fraction(fraction)
            self.progress.set_text(f"{int(fraction * 100)}%")

        elif event_type == "step_progress":
            current = int(event.get("current", 0))
            total = max(1, int(event.get("total", 1)))
            message = event.get("message", "")
            self.status_label.set_text(f"{message} ({current}/{total})")

        elif event_type == "download_progress":
            current = int(event.get("current", 0))
            total = max(1, int(event.get("total", 1)))
            core_name = event.get("core_name", "")
            self.status_label.set_text(
                tr(self.locale, "bootstrap.download.progress", core=core_name, current=current, total=total)
            )

        elif event_type == "bootstrap_completed":
            self.progress.set_fraction(1.0)
            self.progress.set_text("100%")
            self.subtitle_label.set_text(tr(self.locale, "bootstrap.subtitle.completed"))
            self.status_label.set_text("")

        elif event_type == "bootstrap_failed":
            error = event.get("error", "")
            self.subtitle_label.set_text(tr(self.locale, "bootstrap.subtitle.failed"))
            self.status_label.set_text(error)

