"""Matching a search box's text against a game's name (issue 906).

Words in any order, accents folded: "zelda link" finds "The Legend of Zelda -
A Link to the Past", and "pokemon" finds "Pokémon". The names are folded once,
when the library page is built; the query once per keystroke.
"""

import re
import unicodedata

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def fold(text):
    """Lowercase, with the accents stripped: the form both sides compare in."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def parse_query(text):
    """The query's words, folded, as a tuple; empty for a blank query."""
    return tuple(_TOKEN_RE.findall(fold(text)))


def matches(tokens, folded_name):
    """Whether every token appears somewhere in the folded name."""
    return all(token in folded_name for token in tokens)


def refinement(old_tokens, new_tokens):
    """How a query changed, for ``Gtk.FilterChange``.

    ``"stricter"`` when every old word is still there (as a prefix of a
    new one at most), so only what matched before needs re-checking;
    ``"looser"`` for the reverse, when deleting text; ``"different"`` when
    neither holds. GTK re-evaluates every entry on "different" and only the
    visible or the hidden ones otherwise, which is most of the cost of a
    keystroke on a 3000-game page.
    """
    if old_tokens == new_tokens:
        return "same"
    if _extends(old_tokens, new_tokens):
        return "stricter"
    if _extends(new_tokens, old_tokens):
        return "looser"
    return "different"


def _extends(base, extended):
    """Every word of ``base`` is a prefix of a word of ``extended``, in order."""
    if len(extended) < len(base):
        return False
    return all(ext.startswith(old) for old, ext in zip(base, extended))
