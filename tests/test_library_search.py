"""Matching the search box against game names (issue 906)."""

import unittest

from openemux.core.library_search import fold, matches, parse_query, refinement


class FoldingTests(unittest.TestCase):
    def test_case_and_accents_fall_away(self):
        self.assertEqual(fold("Pokémon ROUGE"), "pokemon rouge")
        self.assertEqual(fold(None), "")


class ParsingTests(unittest.TestCase):
    def test_words_in_any_order_are_the_query(self):
        self.assertEqual(parse_query("  Zelda   link "), ("zelda", "link"))
        self.assertEqual(parse_query(""), ())
        self.assertEqual(parse_query("a-link"), ("a", "link"))


class MatchingTests(unittest.TestCase):
    def test_every_word_has_to_appear_somewhere(self):
        name = fold("The Legend of Zelda - A Link to the Past")
        self.assertTrue(matches(parse_query("zelda link"), name))
        self.assertTrue(matches(parse_query("LINK zelda"), name))
        self.assertFalse(matches(parse_query("zelda ocarina"), name))
        self.assertTrue(matches((), name))

    def test_accents_in_the_query_or_the_name_do_not_matter(self):
        self.assertTrue(matches(parse_query("pokemon"), fold("Pokémon Rouge")))
        self.assertTrue(matches(parse_query("pokémon"), fold("Pokemon Red")))


class RefinementTests(unittest.TestCase):
    """What GTK has to re-check after a keystroke."""

    def test_typing_on_narrows(self):
        self.assertEqual(refinement(parse_query("zel"), parse_query("zeld")), "stricter")
        self.assertEqual(refinement(parse_query("zelda"), parse_query("zelda li")), "stricter")
        self.assertEqual(refinement((), parse_query("z")), "stricter")

    def test_deleting_widens(self):
        self.assertEqual(refinement(parse_query("zeld"), parse_query("zel")), "looser")
        self.assertEqual(refinement(parse_query("zelda li"), parse_query("zelda")), "looser")
        self.assertEqual(refinement(parse_query("z"), ()), "looser")

    def test_anything_else_is_a_different_query(self):
        self.assertEqual(refinement(parse_query("zelda"), parse_query("mario")), "different")
        self.assertEqual(refinement(parse_query("zelda link"), parse_query("link zelda")), "different")

    def test_the_same_query_is_the_same(self):
        self.assertEqual(refinement(parse_query("zelda"), parse_query("Zelda")), "same")


if __name__ == "__main__":
    unittest.main()
