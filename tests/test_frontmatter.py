import unittest

from gowords_core import FrontmatterError, parse_frontmatter


class TestFrontmatter(unittest.TestCase):
    def test_quoted_and_bare_scalars(self):
        fm = parse_frontmatter("---\nname: a\ndescription: \"x: y\"\nmetadata:\n  go_word: 'go a'\n  status: open\n  next_due: '2026-10-27'\n---\nbody")
        self.assertEqual(fm["description"], "x: y")
        self.assertEqual(fm["metadata"]["go_word"], "go a")
        self.assertEqual(fm["metadata"]["status"], "open")
        self.assertEqual(fm["metadata"]["next_due"], "2026-10-27")

    def test_inline_list(self):
        fm = parse_frontmatter("---\nmetadata:\n  aliases: ['go b', \"go c\"]\n---\n")
        self.assertEqual(fm["metadata"]["aliases"], ["go b", "go c"])

    def test_escaped_single_quote(self):
        fm = parse_frontmatter("---\nmetadata:\n  done_when: 'it''s done'\n---\n")
        self.assertEqual(fm["metadata"]["done_when"], "it's done")

    def test_block_scalar_is_rejected(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nmetadata:\n  done_when: |\n    a\n---\n")

    def test_block_list_is_rejected(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nmetadata:\n  aliases:\n    - go b\n---\n")

    def test_unindented_block_list_is_rejected(self):
        with self.assertRaises(FrontmatterError):
            parse_frontmatter("---\nname: a\naliases:\n- go: x\n---\n")

    def test_comment_after_bare_value(self):
        fm = parse_frontmatter("---\nmetadata:\n  status: open    # bare with comment\n---\n")
        self.assertEqual(fm["metadata"]["status"], "open")

    def test_comment_after_quoted_value(self):
        fm = parse_frontmatter("---\nmetadata:\n  status: 'open'   # note\n  done_when: \"a # b\"  # c\n---\n")
        self.assertEqual(fm["metadata"]["status"], "open")
        self.assertEqual(fm["metadata"]["done_when"], "a # b")

    def test_comment_after_inline_list(self):
        fm = parse_frontmatter("---\nmetadata:\n  aliases: ['go y']        # optional\n---\n")
        self.assertEqual(fm["metadata"]["aliases"], ["go y"])

    def test_hash_inside_quotes_and_lists_is_kept(self):
        fm = parse_frontmatter("---\nmetadata:\n  done_when: 'issue #4 closed'\n  aliases: ['go #a', 'b # c']  # x\n  tag: a#b\n---\n")
        self.assertEqual(fm["metadata"]["done_when"], "issue #4 closed")
        self.assertEqual(fm["metadata"]["aliases"], ["go #a", "b # c"])
        self.assertEqual(fm["metadata"]["tag"], "a#b")

    def test_bom_is_ignored(self):
        fm = parse_frontmatter("\ufeff---\nname: a\n---\n")
        self.assertEqual(fm["name"], "a")

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(parse_frontmatter("# just a note"), {})


if __name__ == "__main__":
    unittest.main()
