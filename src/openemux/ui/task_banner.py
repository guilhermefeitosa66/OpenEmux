"""The progress banner and the registry of background tasks behind it.

One `Adw.Banner` shows what the app is doing in the background -- a scan, a
cover sync, an import -- and offers Cancel while the running task can be
interrupted. Several of those can be in flight at once, so the banner needs a
registry rather than a flag: it renders the first task and counts the rest.

This lived in `OpenEmuxWindow` as five methods and three attributes with no
coupling to the rest of the window beyond the banner widget and the translate
function, which made it the first thing to lift out of a class that owned
fourteen responsibilities (issue #237).
"""

import logging

logger = logging.getLogger(__name__)


class TaskBanner:
    """Tracks background tasks and renders the first one on ``banner``.

    The banner widget is attached separately, with :meth:`attach`, because the
    window registers the object before it builds its header bars -- a task
    begun in between is remembered and shows up as soon as there is somewhere
    to draw it.
    """

    def __init__(self, translate):
        self._t = translate
        self._banner = None
        self._seq = 0
        self._tasks = {}
        self._cancel_task_id = None

    def attach(self, banner):
        """Take over ``banner``: its title, its button, and its visibility."""
        self._banner = banner
        banner.connect("button-clicked", self._on_button_clicked)
        self.refresh()

    @property
    def banner(self):
        return self._banner

    def __len__(self):
        return len(self._tasks)

    def begin(self, kind, label, total=0, on_cancel=None):
        """Register a background task. ``on_cancel`` makes it interruptible.

        A cancellable task gets a Cancel button on the progress banner; the
        callback is expected to signal the worker, not to block waiting for it.
        """
        self._seq += 1
        task_id = f"{kind}-{self._seq}"
        self._tasks[task_id] = {
            "id": task_id,
            "kind": kind,
            "label": label,
            "current": 0,
            "total": int(total or 0),
            "pending": True,
            "on_cancel": on_cancel,
            "cancelling": False,
        }
        self.refresh()
        return task_id

    def update(self, task_id, current=None, total=None, label=None):
        task = self._tasks.get(task_id)
        if not task:
            return
        if current is not None:
            task["current"] = int(max(0, current))
        if total is not None:
            task["total"] = int(max(0, total))
        if label is not None:
            task["label"] = label
        self.refresh()

    def finish(self, task_id):
        self._tasks.pop(task_id, None)
        self.refresh()

    def cancel(self, task_id):
        task = self._tasks.get(task_id)
        if not task or task.get("cancelling") or not task.get("on_cancel"):
            return
        # Mark first: the worker stops at its next checkpoint, so the banner has
        # to show "stopping" rather than pretending it is already done.
        task["cancelling"] = True
        logger.info("task cancel requested: id=%s kind=%s", task_id, task["kind"])
        self.refresh()
        task["on_cancel"]()

    def show_notice(self, title):
        """Borrow the banner for a transient message, e.g. the drop hint.

        Whatever task was showing comes back on the next :meth:`refresh`.
        """
        if self._banner is None:
            return
        self._banner.set_title(title)
        self._banner.set_revealed(True)

    def refresh(self):
        if self._banner is None:
            return
        if not self._tasks:
            self._banner.set_revealed(False)
            return

        task = next(iter(self._tasks.values()))
        pending = max(0, len(self._tasks) - 1)
        label = task["label"]
        total = int(task.get("total") or 0)
        current = int(task.get("current") or 0)
        if task.get("cancelling"):
            label = self._t("banner.stopping")
        else:
            if total > 0:
                label = f"{label} ({current}/{total})"
            if pending:
                label = f"{label} (+{pending})"
        self._banner.set_title(label)

        # Offer Cancel only while the task is actually interruptible.
        if task.get("on_cancel") and not task.get("cancelling"):
            self._banner.set_button_label(self._t("banner.cancel"))
            self._cancel_task_id = task["id"]
        else:
            self._banner.set_button_label(None)
            self._cancel_task_id = None
        self._banner.set_revealed(True)

    def _on_button_clicked(self, _banner):
        if self._cancel_task_id:
            self.cancel(self._cancel_task_id)
