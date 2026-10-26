import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gowords_core import due_label, format_delta, launch_label, load_workstreams

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 26, 10, 59, tzinfo=PARIS)


def card(go_word="go a", status="open", extra="", done_when="'it ships'"):
    lines = ["---", "name: n", "metadata:"]
    if go_word is not None:
        lines.append(f"  go_word: '{go_word}'")
    if status is not None:
        lines.append(f"  status: {status}")
    if done_when is not None:
        lines.append(f"  done_when: {done_when}")
    if extra:
        lines.append(extra)
    lines += ["---", "body"]
    return "\n".join(lines)


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def load(self, now=NOW):
        return load_workstreams(self.dir, PARIS, now)

    def one(self, text, now=NOW):
        self.write("a.md", text)
        ws, problems = self.load(now)
        self.assertEqual(len(ws), 1, problems)
        return ws[0], problems


class TestDates(RegistryCase):
    def test_bare_date_due_is_end_of_day(self):
        w, _ = self.one(card(extra="  next_due: '2026-10-27'"))
        self.assertEqual(w.due, datetime(2026, 10, 27, 23, 59, tzinfo=PARIS))
        self.assertFalse(w.due_timed)

    def test_timed_due(self):
        w, _ = self.one(card(extra="  next_due: '2026-10-27 08:15'"))
        self.assertEqual(w.due, datetime(2026, 10, 27, 8, 15, tzinfo=PARIS))
        self.assertTrue(w.due_timed)

    def test_bare_date_not_before_is_midnight(self):
        w, _ = self.one(card(extra="  not_before: '2026-10-27'"))
        self.assertEqual(w.not_before, datetime(2026, 10, 27, 0, 0, tzinfo=PARIS))

    def test_invalid_date_reported_and_ignored(self):
        w, problems = self.one(card(extra="  next_due: 'soon'"))
        self.assertIsNone(w.due)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("a.md"))
        self.assertIn("next_due", problems[0])

    def test_age_days(self):
        self.write("a.md", card())
        ts = (NOW - timedelta(days=5)).timestamp()
        os.utime(os.path.join(self.dir, "a.md"), (ts, ts))
        ws, _ = self.load()
        self.assertEqual(ws[0].age_days, 5)


class TestLabels(RegistryCase):
    def test_launch_now_when_not_before_past(self):
        w, _ = self.one(card(extra="  not_before: '2026-10-25'"))
        self.assertEqual(launch_label(w, NOW, "en"), "now")
        self.assertEqual(launch_label(w, NOW, "fr"), "maintenant")

    def test_launch_now_without_not_before(self):
        w, _ = self.one(card())
        self.assertEqual(launch_label(w, NOW, "en"), "now")

    def test_launch_later(self):
        w, _ = self.one(card(extra="  not_before: '2026-10-27 07:30'"))
        self.assertEqual(launch_label(w, NOW, "en"), "not before 2026-10-27 07:30 (in 20 h 31)")
        self.assertEqual(launch_label(w, NOW, "fr"), "pas avant 2026-10-27 07:30 (dans 20 h 31)")

    def test_launch_later_same_day_shows_time_only(self):
        w, _ = self.one(card(extra="  not_before: '2026-10-26 14:00'"))
        self.assertEqual(launch_label(w, NOW, "en"), "not before 14:00 (in 3 h 01)")

    def test_overdue(self):
        w, _ = self.one(card(extra="  next_due: '2026-10-25'"))
        self.assertTrue(due_label(w, NOW, "en").startswith("OVERDUE by 11 h 00"))
        self.assertTrue(due_label(w, NOW, "fr").startswith("DÉPASSÉE de 11 h 00"))

    def test_due_soon_end_of_day(self):
        w, _ = self.one(card(extra="  next_due: '2026-10-27'"))
        self.assertEqual(due_label(w, NOW, "en"), "in 1 d 13 h (end of day)")
        self.assertEqual(due_label(w, NOW, "fr"), "dans 1 j 13 h (fin de journée)")

    def test_due_timed_has_no_end_of_day(self):
        w, _ = self.one(card(extra="  next_due: '2026-10-26 12:00'"))
        self.assertEqual(due_label(w, NOW, "en"), "in 1 h 01")

    def test_due_beyond_48h_is_empty(self):
        w, _ = self.one(card(extra="  next_due: '2026-11-30'"))
        self.assertEqual(due_label(w, NOW, "en"), "")

    def test_no_due_is_empty(self):
        w, _ = self.one(card())
        self.assertEqual(due_label(w, NOW, "en"), "")

    def test_dst_change(self):
        now = datetime(2026, 10, 24, 12, 0, tzinfo=PARIS)
        w, _ = self.one(card(extra="  next_due: '2026-10-25 12:00'"), now)
        self.assertEqual(due_label(w, now, "en"), "in 1 d 1 h")

    def test_format_delta(self):
        self.assertEqual(format_delta(timedelta(hours=3, minutes=5)), "3 h 05")
        self.assertEqual(format_delta(timedelta(days=1, hours=12)), "1 d 12 h")
        self.assertEqual(format_delta(timedelta(days=1, hours=12), "fr"), "1 j 12 h")
        self.assertEqual(format_delta(timedelta(days=2)), "2 d")
        self.assertEqual(format_delta(timedelta(minutes=20)), "20 min")
        self.assertEqual(format_delta(-timedelta(minutes=20)), "20 min")


class TestWaitingOn(RegistryCase):
    def test_default_empty(self):
        w, _ = self.one(card())
        self.assertEqual(w.waiting_on, "")

    def test_waiting_on_alone_not_launchable(self):
        w, _ = self.one(card(extra="  waiting_on: 'the reply'"))
        self.assertEqual(w.waiting_on, "the reply")
        self.assertEqual(launch_label(w, NOW, "en"), "waiting on the reply")
        self.assertEqual(launch_label(w, NOW, "fr"), "attend : the reply")

    def test_waiting_on_with_future_not_before(self):
        w, _ = self.one(card(extra="  waiting_on: 'the reply'\n  not_before: '2026-10-27 12:00'"))
        self.assertEqual(launch_label(w, NOW, "en"), "not before 2026-10-27 12:00 (in 1 d 1 h); waiting on the reply")
        self.assertEqual(launch_label(w, NOW, "fr"), "pas avant 2026-10-27 12:00 (dans 1 j 1 h) ; attend : the reply")

    def test_waiting_on_with_past_not_before_still_waiting(self):
        w, _ = self.one(card(extra="  waiting_on: 'the reply'\n  not_before: '2026-10-20'"))
        self.assertEqual(launch_label(w, NOW, "en"), "waiting on the reply")

    def test_without_waiting_on_unchanged(self):
        w, _ = self.one(card(extra="  not_before: '2026-10-20'"))
        self.assertEqual(launch_label(w, NOW, "en"), "now")


class TestLoading(RegistryCase):
    def test_french_statuses_normalized(self):
        for raw, expected in [("en attente", "waiting"), ("clos", "closed"), ("arrêté", "stopped"),
                              ("ouvert", "open"), ("open", "open"), ("Waiting", "waiting")]:
            w, problems = self.one(card(status=f"'{raw}'"))
            self.assertEqual(w.status, expected, raw)
            self.assertEqual(problems, [])

    def test_unknown_status_reported(self):
        _, problems = self.one(card(status="'CLOS le 07/10 etc'"))
        self.assertEqual(len(problems), 1)
        self.assertIn("a.md", problems[0])
        self.assertIn("status", problems[0])

    def test_missing_done_when_reported(self):
        _, problems = self.one(card(done_when=None))
        self.assertEqual(len(problems), 1)
        self.assertIn("done_when", problems[0])

    def test_unreadable_frontmatter_reported(self):
        self.write("a.md", "---\nmetadata:\n  go_word: 'go a'\n  aliases:\n    - x\n---\n")
        ws, problems = self.load()
        self.assertEqual(ws, [])
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("a.md"))

    def test_files_without_go_word_ignored(self):
        self.write("a.md", card(go_word=None))
        self.write("b.md", "no frontmatter here\n")
        ws, problems = self.load()
        self.assertEqual((ws, problems), ([], []))

    def test_MEMORY_md_ignored(self):
        self.write("MEMORY.md", card())
        ws, problems = self.load()
        self.assertEqual((ws, problems), ([], []))

    def test_non_md_ignored(self):
        self.write("a.txt", card())
        self.assertEqual(self.load(), ([], []))

    def test_duplicate_word_reported(self):
        self.write("a.md", card("go a"))
        self.write("b.md", card("GO A"))
        ws, problems = self.load()
        self.assertEqual(len(ws), 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("go a", problems[0].lower())

    def test_closed_duplicate_not_reported(self):
        self.write("a.md", card("go a"))
        self.write("b.md", card("go a", status="closed"))
        _, problems = self.load()
        self.assertEqual(problems, [])

    def test_scalar_alias_becomes_list(self):
        w, _ = self.one(card(extra="  aliases: 'go b'"))
        self.assertEqual(w.aliases, ["go b"])

    def test_list_aliases_and_fields(self):
        w, _ = self.one(card(extra="  aliases: ['go b', 'go c']"))
        self.assertEqual(w.aliases, ["go b", "go c"])
        self.assertEqual(w.word, "go a")
        self.assertEqual(w.done_when, "it ships")
        self.assertEqual(w.path, os.path.join(self.dir, "a.md"))

    def test_results_sorted_by_filename(self):
        self.write("b.md", card("go b"))
        self.write("a.md", card("go a"))
        ws, _ = self.load()
        self.assertEqual([w.word for w in ws], ["go a", "go b"])


if __name__ == "__main__":
    unittest.main()


class TestLoadingRobustness(RegistryCase):
    def test_invalid_utf8_reported_and_skipped(self):
        with open(os.path.join(self.dir, "bad.md"), "wb") as f:
            f.write(b"---\nname: \xff\xfe\n---\n")
        self.write("ok.md", card())
        ws, problems = self.load()
        self.assertEqual([w.word for w in ws], ["go a"])
        self.assertTrue(any(p.startswith("bad.md") for p in problems))

    def test_directory_named_md_reported_and_skipped(self):
        os.mkdir(os.path.join(self.dir, "dir.md"))
        self.write("ok.md", card())
        ws, problems = self.load()
        self.assertEqual(len(ws), 1)
        self.assertTrue(any(p.startswith("dir.md") for p in problems))

    def test_bom_card_is_loaded(self):
        self.write("b.md", "\ufeff" + card())
        ws, _ = self.load()
        self.assertEqual(len(ws), 1)

    def test_documented_template_loads_without_problem(self):
        text = (
            "---\nname: x\ndescription: \"d\"\nmetadata:\n  type: project\n  go_word: 'go x'\n"
            "  aliases: ['go y']        # optional\n  status: 'open'                  # open | waiting\n"
            "  next_due: '2026-10-27'          # optional\n  not_before: '2026-10-26 12:00'  # optional\n"
            "  done_when: 'it ships'\n---\nbody"
        )
        self.write("t.md", text)
        ws, problems = self.load()
        self.assertEqual(problems, [])
        self.assertEqual(ws[0].aliases, ["go y"])
        self.assertEqual(ws[0].status, "open")
