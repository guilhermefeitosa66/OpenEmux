"""The state machine behind "press a button for this action".

Mapping a controller is a small machine: one action is armed at a time; a
press stores a token and, in map-all, arms the next action; Escape aborts;
and storing a token takes it away from whatever else held it. That machine
lived inside `OpenEmuxPreferences`, tangled with the button labels and the
prompt it drives, so none of it could be tested without a display -- the
dialog sits around 10% coverage (issue #238).

There is nothing about it that needs a widget. It is here now, and the dialog
asks it what happened and renders that.
"""

from collections import namedtuple

#: What :meth:`InputCaptureSession.cancel` reports back: which action was
#: armed (so its button can go back to showing its binding) and whether a
#: map-all was interrupted (so the dialog can say so).
Cancelled = namedtuple("Cancelled", "action was_sequence")

#: What :meth:`InputCaptureSession.commit` reports back. Exactly one of
#: ``next_action`` and ``finished`` is meaningful: a sequence either moves on
#: or is over, and a single capture is neither.
Committed = namedtuple("Committed", "action released next_action finished")


class InputCaptureSession:
    """The bindings being edited, and which action is listening right now.

    Owns four things and no widgets: the buffer of bindings for the device on
    screen, the actions a map-all walks, which action is armed, and where the
    walk has got to.
    """

    #: A hotkey that only fires while a modifier is held *is* a shared button,
    #: so this one action never takes a token away from another and no other
    #: takes it away from this one (issue #124).
    SHARED_ACTION = "enable_hotkey"

    def __init__(self):
        self.bindings = {}
        self.sequence_actions = []
        self.active_action = None
        self.sequence_mode = False
        self._sequence_index = -1

    # ----- loading a device ------------------------------------------------
    def load(self, bindings, sequence_actions):
        """Take the bindings of the device now on screen.

        ``sequence_actions`` is what map-all walks -- the visible actions
        minus the optional ones, since forcing a user through binding a
        modifier they may not want defeats the flow.
        """
        self.bindings = dict(bindings)
        self.sequence_actions = list(sequence_actions)
        self.active_action = None
        self.sequence_mode = False
        self._sequence_index = -1

    # ----- the collision rule ----------------------------------------------
    def actions_holding(self, action, value):
        """What else is on ``value`` and has to let go of it.

        Every collision is real -- the user pointed a button at a new command,
        and the old one cannot keep it (issue #281) -- except the shared
        modifier, in both directions.
        """
        if not value:
            return []
        return [
            other
            for other, other_value in self.bindings.items()
            if other != action
            and other_value == value
            and self.SHARED_ACTION not in (other, action)
        ]

    def set_binding(self, action, value):
        """Store ``value`` on ``action``; return the actions it took it from."""
        value = (value or "").strip().lower()
        released = self.actions_holding(action, value)
        for other_action in released:
            self.bindings[other_action] = ""
        self.bindings[action] = value
        return released

    def binding_for(self, action):
        return self.bindings.get(action, "")

    # ----- arming ----------------------------------------------------------
    @property
    def capturing(self):
        return self.active_action is not None

    def start(self, action, sequence_mode=False):
        self.active_action = action
        self.sequence_mode = sequence_mode

    def begin_sequence(self):
        """Arm the first action of a map-all, or None when there is nothing.

        The caller is expected to have cancelled whatever was armed before.
        """
        if not self.sequence_actions:
            return None
        self.sequence_mode = True
        self._sequence_index = 0
        first = self.sequence_actions[0]
        self.start(first, sequence_mode=True)
        return first

    def cancel(self):
        """Disarm, and report what was armed and whether a map-all died."""
        cancelled = Cancelled(self.active_action, self.sequence_mode)
        self.active_action = None
        self.sequence_mode = False
        self._sequence_index = -1
        return cancelled

    # ----- a press ---------------------------------------------------------
    def commit(self, value):
        """Store ``value`` on the armed action and work out what comes next.

        Returns None when nothing was armed -- the gamepad reader runs on its
        own thread, so a press can arrive after the capture was cancelled.
        """
        action = self.active_action
        if not action:
            return None
        released = self.set_binding(action, value)
        if not self.sequence_mode:
            return Committed(action, released, next_action=None, finished=False)

        self._sequence_index += 1
        if self._sequence_index >= len(self.sequence_actions):
            return Committed(action, released, next_action=None, finished=True)
        next_action = self.sequence_actions[self._sequence_index]
        self.start(next_action, sequence_mode=True)
        return Committed(action, released, next_action=next_action, finished=False)
