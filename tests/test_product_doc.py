"""The product-direction document and the places that point to it (issue #514).

``docs/PRODUCT.md`` is what contributors read before proposing a change and
what reviews cite when one does not fit. These tests hold its five sections in
place, keep README, CONTRIBUTING and the pull request template pointing at it,
and fail when a repository path it cites no longer exists -- the cheapest
guard against the document drifting away from the code it describes.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRODUCT = REPO / "docs" / "PRODUCT.md"

SECTIONS = [
    "Product vision",
    "Principles",
    "Non-goals",
    "Design system",
    "Contribution fit",
]

# [text](target) -- the target up to the closing parenthesis.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# `src/...`, `tests/...` and similar repository paths quoted as code.
CODE_PATH = re.compile(r"`((?:src|tests|docs)/[^`\s]+)`")


def _relative_links(text):
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        yield target.split("#", 1)[0]


class ProductDocTests(unittest.TestCase):
    def setUp(self):
        self.text = PRODUCT.read_text(encoding="utf-8")

    def test_has_the_five_sections_in_order(self):
        headings = re.findall(r"^## (.+)$", self.text, flags=re.MULTILINE)
        self.assertEqual(headings, SECTIONS)

    def test_relative_links_resolve(self):
        targets = list(_relative_links(self.text))
        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                self.assertTrue((PRODUCT.parent / target).resolve().exists())

    def test_cited_repository_paths_exist(self):
        paths = CODE_PATH.findall(self.text)
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((REPO / path).exists())

    def test_link_helper_skips_urls_and_anchors(self):
        text = "[a](https://x.org) [b](#here) [c](../README.md#about) [d](mailto:a@b)"
        self.assertEqual(list(_relative_links(text)), ["../README.md"])


class PointersToProductDocTests(unittest.TestCase):
    def test_readme_links_it(self):
        self.assertIn(
            "(docs/PRODUCT.md)", (REPO / "README.md").read_text(encoding="utf-8")
        )

    def test_contributing_links_it(self):
        text = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("(docs/PRODUCT.md)", text)

    def test_pull_request_template_asks_for_it(self):
        text = (REPO / ".github" / "pull_request_template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "- [ ] I read [docs/PRODUCT.md]"
            "(https://github.com/guilhermefeitosa66/OpenEmux/blob/develop/docs/PRODUCT.md)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
