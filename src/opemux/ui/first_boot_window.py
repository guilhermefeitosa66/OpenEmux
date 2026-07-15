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
        self.set_default_size(640, 480)
        if parent is not None:
            self.set_transient_for(parent)
            self.set_modal(True)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_title(False)
        toolbar.add_top_bar(header)

        status_page = Adw.StatusPage()
        status_page.set_icon_name("system-software-install-symbolic")
        status_page.set_title(tr(self.locale, "bootstrap.title"))
        self.title_label = status_page  # kept for compatibility; drives the title
        self.status_page = status_page

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.set_halign(Gtk.Align.CENTER)
        body.set_size_request(420, -1)

        self.subtitle_label = Gtk.Label(label=tr(self.locale, "bootstrap.subtitle.initial"))
        self.subtitle_label.add_css_class("dim-label")
        self.subtitle_label.set_wrap(True)
        self.subtitle_label.set_justify(Gtk.Justification.CENTER)
        body.append(self.subtitle_label)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_fraction(0.0)
        self.progress.set_text("0%")
        body.append(self.progress)

        self.status_label = Gtk.Label(label="")
        self.status_label.add_css_class("caption")
        self.status_label.add_css_class("dim-label")
        self.status_label.set_wrap(True)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        body.append(self.status_label)

        # Spinner retained for API compatibility; the progress bar is the primary cue.
        self.spinner = Gtk.Spinner()

        status_page.set_child(body)
        toolbar.set_content(status_page)
        self.set_content(toolbar)

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

