"""The task banners over the Shelf and the games, Android's way (issue 957).

Android shows a running task as a banner at the top of the library -- an
icon, "Fetching labels · 19 of 133", a progress line under it -- where the
desktop Big Picture had a chip in the corner. The banners mirror the
window's own state, so nothing new tracks a task: ``win.tasks`` (the task
the desktop's progress banner shows) and ``win.update_banner`` (a newer
release is out). A on the task banner offers to stop it (what the quick
menu's Stop did); A on the update banner does what the desktop banner's
button does.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from openemux.ui.bigpicture.widgets import Banner


class TaskBanners(Gtk.Box):
    """The banners a library page shows; ``sync()`` re-reads the window."""

    def __init__(self, shell):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.shell = shell
        self.win = shell.win
        self.task = Banner("emblem-synchronizing-symbolic", on_activate=shell.run_task_action)
        self.task.set_visible(False)
        self.append(self.task)
        self.update = Banner("software-update-available-symbolic", on_activate=self._on_update)
        self.update.set_visible(False)
        self.append(self.update)
        self.set_visible(False)

    def sync(self):
        win, t = self.win, self.win.t
        task = win.tasks.current_task()
        if task is not None:
            total = task.get("total") or 0
            current = task.get("current") or 0
            detail = t("big_picture.banner.progress", current=current, total=total) if total else None
            self.task.show(task.get("label") or win.banner.get_title(), detail, current / total if total else None)
            self.task.set_visible(True)
        else:
            self.task.set_visible(False)
        update = win.update_banner
        if update.get_revealed() and update.get_title():
            self.update.show(update.get_title())
            self.update.set_visible(True)
        else:
            self.update.set_visible(False)
        self.set_visible(self.task.get_visible() or self.update.get_visible())

    def _on_update(self):
        self.win._on_update_banner_clicked(self.win.update_banner)


__all__ = ["TaskBanners"]
