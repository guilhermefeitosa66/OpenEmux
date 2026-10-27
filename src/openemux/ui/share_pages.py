"""Pages both Share nearby dialogs show: waiting, progress and the result (#589).

The share dialog (sending) and the incoming-offer dialog (receiving) end the
same way, so the pages are built here once. Each builder returns an
``Adw.NavigationPage`` with no back button: these pages *replace* what was on
screen, so Back can never leave a transfer that is still running.
"""

from gi.repository import Adw, Gtk, Pango

from openemux.core.share.display import error_key, format_size, plural, spaced_digits
from openemux.core.share.protocol import ErrorCode
from openemux.core.share.verification import format_code

STATUS_DONE = "done"

#: A finished transfer's status (or the failure's code) -> the result's title.
_TITLES = {
    ErrorCode.DECLINED: "share.result.declined",
    ErrorCode.EXPIRED: "share.result.expired",
    ErrorCode.CANCELLED: "share.result.cancelled",
    ErrorCode.UNREACHABLE: "share.result.unreachable",
}


def label(text="", css=(), wrap=True, xalign=0.5, markup=False):
    widget = Gtk.Label()
    if markup:
        widget.set_markup(text)
    else:
        widget.set_label(text)
    widget.set_wrap(wrap)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_xalign(xalign)
    widget.set_justify(Gtk.Justification.CENTER if xalign == 0.5 else Gtk.Justification.LEFT)
    for name in css:
        widget.add_css_class(name)
    return widget


def page(title, child, tag, subtitle="", bottom=None, can_pop=True):
    """A navigation page: header bar with ``title``, ``child`` as content."""
    header = Adw.HeaderBar()
    window_title = Adw.WindowTitle(title=title, subtitle=subtitle)
    header.set_title_widget(window_title)
    toolbar = Adw.ToolbarView()
    toolbar.add_top_bar(header)
    toolbar.set_content(child)
    if bottom is not None:
        toolbar.add_bottom_bar(bottom)
    nav_page = Adw.NavigationPage(title=title, tag=tag, child=toolbar)
    nav_page.set_can_pop(can_pop)
    nav_page.window_title = window_title
    nav_page.focus_widget = None
    return nav_page


def show_page(dialog, nav_page):
    """Replace what ``dialog`` shows with ``nav_page`` and focus its button.

    The widget that had the focus goes away with the old page; without a new
    one the dialog stops getting keys -- Escape no longer closes it, and what
    is typed reaches the window behind.
    """
    dialog.nav.replace([nav_page])
    dialog.set_focus(nav_page.focus_widget)


def code_label(code):
    """The verification code, big and monospace, read digit by digit."""
    widget = label(format_code(code), css=("title-1", "share-code"))
    widget.set_selectable(True)
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [spaced_digits(code)])
    return widget


def _column(*children, spacing=12):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.set_valign(Gtk.Align.CENTER)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)
    for child in children:
        box.append(child)
    clamp = Adw.Clamp(maximum_size=420, child=box)
    scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp)
    scrolled.set_vexpand(True)
    return scrolled


def pill(text, css="suggested-action"):
    button = Gtk.Button(label=text)
    button.add_css_class("pill")
    if css:
        button.add_css_class(css)
    button.set_halign(Gtk.Align.CENTER)
    return button


class WaitingPage:
    """The sender's wait: preparing, then the code, until the answer."""

    def __init__(self, t, device, on_cancel):
        self.t = t
        self.device = device
        self.spinner = Gtk.Spinner(spinning=True)
        self.spinner.set_size_request(32, 32)
        self.title = label(t("share.wait.preparing"), css=("title-2",))
        self.code = label("", css=("title-1", "share-code"))
        self.code.set_visible(False)
        self.hint = label(t("share.wait.hint"), css=("dim-label",))
        self.hint.set_visible(False)
        self.cancel_button = pill(t("share.cancel"), css=None)
        self.cancel_button.connect("clicked", lambda _b: on_cancel())
        content = _column(self.spinner, self.title, self.code, self.hint, self.cancel_button)
        self.page = page(t("share.title"), content, "waiting", can_pop=False)
        self.page.focus_widget = self.cancel_button

    def show_code(self, code):
        self.title.set_label(self.t("share.wait.title", device=self.device))
        self.code.set_label(format_code(code))
        self.code.update_property([Gtk.AccessibleProperty.DESCRIPTION], [spaced_digits(code)])
        self.code.set_visible(True)
        self.hint.set_visible(True)


class ProgressPage:
    def __init__(self, t, header, on_cancel):
        self.t = t
        self.current = label("", css=("heading",))
        self.current.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.bar = Gtk.ProgressBar()
        self.bar.update_property([Gtk.AccessibleProperty.LABEL], [t("share.progress.label")])
        self.bytes = label("", css=("dim-label", "numeric"))
        self.files = label("", css=("dim-label", "numeric"))
        self.cancel_button = pill(t("share.progress.cancel"), css="destructive-action")
        self.cancel_button.connect("clicked", lambda _b: on_cancel())
        content = _column(self.current, self.bar, self.bytes, self.files, self.cancel_button)
        self.page = page(header, content, "progress", can_pop=False)
        self.page.focus_widget = self.cancel_button

    def update(self, progress):
        t = self.t
        total = progress.get("total_bytes") or 0
        done = progress.get("done_bytes") or 0
        self.current.set_label(progress.get("name", ""))
        self.bar.set_fraction(min(1.0, done / total) if total else 0.0)
        self.bytes.set_label(t("share.progress.bytes", done=format_size(done, t), total=format_size(total, t)))
        position = min(progress.get("files_done", 0) + 1, progress.get("file_count", 0))
        self.files.set_label(t("share.progress.file", i=position, n=progress.get("file_count", 0)))


def confirm_cancel(parent, t, on_confirm):
    """Ask before a close ends a running transfer; ``on_confirm`` cancels it."""
    alert = Adw.AlertDialog(heading=t("share.cancel_confirm.heading"), body=t("share.cancel_confirm.body"))
    alert.add_response("keep", t("share.cancel_confirm.keep"))
    alert.add_response("cancel", t("share.progress.cancel"))
    alert.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)
    alert.set_default_response("keep")
    alert.set_close_response("keep")
    alert.connect("response", lambda _alert, response: on_confirm() if response == "cancel" else None)
    alert.present(parent)
    return alert


def result_page(t, result, device, receiving, games=0, summary="", on_close=None, on_show=None):
    """The status page a transfer ends on; ``result`` is the core's."""
    status = result.get("status")
    error = result.get("error")
    page_box = Adw.StatusPage()
    if status == STATUS_DONE:
        page_box.set_icon_name("emblem-ok-symbolic")
        if receiving:
            page_box.set_title(plural(t, games, "share.result.received.one", "share.result.received.many"))
            description = t("share.result.received_body", device=device)
        else:
            page_box.set_title(plural(t, games, "share.result.sent.one", "share.result.sent.many"))
            description = t("share.result.sent_body", device=device)
        if summary:
            description = f"{description}\n{summary}"
    else:
        page_box.set_icon_name("dialog-error-symbolic")
        code = status if status in _TITLES else (error or status)
        page_box.set_title(t(_TITLES.get(code, "share.result.failed")))
        description = t(error_key(code), device=device)
        if receiving:
            description = f"{description}\n{t('share.result.nothing_saved')}"
    page_box.set_description(description)
    buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    buttons.set_halign(Gtk.Align.CENTER)
    if on_show is not None and status == STATUS_DONE:
        show = pill(t("share.result.show"))
        show.connect("clicked", lambda _b: on_show())
        buttons.append(show)
    close = pill(t("share.result.close"), css=None if on_show is not None and status == STATUS_DONE else "suggested-action")
    close.connect("clicked", lambda _b: on_close())
    buttons.append(close)
    page_box.set_child(buttons)
    result_nav = page(t("share.offer.title" if receiving else "share.title"), page_box, "result", can_pop=False)
    result_nav.close_button = close
    result_nav.focus_widget = close
    return result_nav
