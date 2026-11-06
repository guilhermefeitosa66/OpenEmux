"""Which actions are being pressed right now (issue 816).

The controller drawing on the input page lights a button for as long as the
input bound to it is held: a key when the keyboard is being edited, a pad
button, axis or hat when a pad is. The readers say which binding tokens are
down; this turns that into the actions to light. No GTK and no device in it,
so the rules are tested without either.
"""

from openemux.core.input_actions import GLOBAL_HOTKEY_ACTIONS, retroarch_key_token

#: The action that gates every other hotkey once it is bound.
MODIFIER = "enable_hotkey"


def lit_actions(bindings, held):
    """The actions of `bindings` (action -> token) whose token is in `held`.

    A hotkey is lit only when it would fire. With a modifier bound, as on a
    pad where Select + Start opens the menu, Start alone lights Start and not
    the menu button; with none, as on a keyboard, the hotkey's own key is
    enough. An input bound to nothing lights nothing.
    """
    held = {token for token in held if token}
    if not held:
        return set()
    modifier = bindings.get(MODIFIER) or ""
    gated = bool(modifier) and modifier not in held
    lit = set()
    for action, token in bindings.items():
        if not token or token not in held:
            continue
        if gated and action in GLOBAL_HOTKEY_ACTIONS and action != MODIFIER:
            continue
        lit.add(action)
    return lit


def key_token(name):
    """A key's name, as bindings spell it: lower case, in RetroArch's vocabulary."""
    return retroarch_key_token((name or "").lower())


class HeldKeys:
    """The keyboard keys held down, by hardware keycode.

    By keycode because a key's name can change between its press and its
    release -- Shift going down in between turns ``1`` into ``exclam`` -- and
    a release that names another key would leave the first one lit for good.
    """

    def __init__(self):
        self._by_keycode = {}

    def press(self, keycode, name):
        """Record a press; True when it changed what is held."""
        token = key_token(name)
        if not token or self._by_keycode.get(keycode) == token:
            return False
        self._by_keycode[keycode] = token
        return True

    def release(self, keycode):
        """Record a release; True when it changed what is held."""
        return self._by_keycode.pop(keycode, None) is not None

    def clear(self):
        """Forget everything (the dialog lost the keyboard); True when something was held."""
        had = bool(self._by_keycode)
        self._by_keycode.clear()
        return had

    @property
    def tokens(self):
        return frozenset(self._by_keycode.values())
