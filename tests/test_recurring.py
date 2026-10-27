"""Recurring workstreams, closed follow-up, stopped filed with the closed ones (0.4.0)."""
import json
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from gowords_core import load_workstreams
from .test_cli import Base, card

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 26, 10, 59, tzinfo=PARIS)


def rec(word, cadence="'monthly'", next_run=None, status="'recurring'", extra=""):
    lines = ["---", "name: n", "metadata:", f"  go_word: '{word}'", f"  status: {status}",
             "  done_when: 'run done'"]
    if cadence is not None:
        lines.append(f"  cadence: {cadence}")
    if next_run:
        lines.append(f"  next_run: '{next_run}'")
    if extra:
        lines.append(extra)
    lines += ["---", "body"]
    return "\n".join(lines)


class LoadCase(Base):
    def load(self):
        return load_workstreams(self.mem, PARIS, NOW)

    def test_statuses_normalized(self):
        for raw in ("recurring", "récurrent", "recurrent", "Récurrent"):
            self.write("a.md", rec("go a", status=f"'{raw}'", next_run="2026-11-11"))
            ws, problems = self.load()
            self.assertEqual(ws[0].status, "recurring", raw)
            self.assertEqual(problems, [], raw)

    def test_fields(self):
        self.write("a.md", rec("go a", cadence="'2nd Wednesday'", next_run="2026-11-11 09:00"))
        w = self.load()[0][0]
        self.assertEqual(w.cadence, "2nd Wednesday")
        self.assertEqual(w.next_run, datetime(2026, 11, 11, 9, 0, tzinfo=PARIS))
        self.assertTrue(w.next_run_timed)

    def test_bare_next_run_is_midnight(self):
        self.write("a.md", rec("go a", next_run="2026-11-11"))
        w = self.load()[0][0]
        self.assertEqual(w.next_run, datetime(2026, 11, 11, 0, 0, tzinfo=PARIS))
        self.assertFalse(w.next_run_timed)

    def test_on_demand_needs_no_next_run(self):
        for cadence in ("'on demand'", "'sur demande'", "'Sur demande'"):
            self.write("a.md", rec("go a", cadence=cadence))
            self.assertEqual(self.load()[1], [], cadence)

    def test_missing_next_run_reported(self):
        self.write("a.md", rec("go a"))
        problems = self.load()[1]
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("a.md: "))
        self.assertIn("next_run", problems[0])

    def test_missing_cadence_reported(self):
        self.write("a.md", rec("go a", cadence=None, next_run="2026-11-11"))
        problems = self.load()[1]
        self.assertEqual(len(problems), 1)
        self.assertIn("cadence", problems[0])

    def test_next_due_on_recurring_reported(self):
        self.write("a.md", rec("go a", next_run="2026-11-11", extra="  next_due: '2026-11-11'"))
        problems = self.load()[1]
        self.assertEqual(len(problems), 1)
        self.assertIn("next_due", problems[0])

    def test_unreadable_next_run_reported(self):
        self.write("a.md", rec("go a", next_run="soon"))
        ws, problems = self.load()
        self.assertIsNone(ws[0].next_run)
        self.assertTrue(any("next_run" in p for p in problems))

    def test_recurring_duplicate_reported(self):
        self.write("a.md", rec("go a", next_run="2026-11-11"))
        self.write("b.md", card("go a"))
        self.assertEqual(len(self.load()[1]), 1)

    def test_follow_up_on_closed(self):
        self.write("a.md", card("go a", status="closed").replace(
            "  done_when:", "  follow_up: 'post scheduled 10-29 07:30'\n  done_when:"))
        ws, problems = self.load()
        self.assertEqual(ws[0].follow_up, "post scheduled 10-29 07:30")
        self.assertEqual(problems, [])


class ListCase(Base):
    def setUp(self):
        super().setUp()
        self.write("o.md", card("go open"))
        self.write("r.md", rec("go monthly", cadence="'2nd Wednesday 09:00'", next_run="2026-11-11 09:00"))
        self.write("d.md", rec("go demand", cadence="'on demand'"))
        self.write("c.md", card("go done", status="closed"))
        self.write("s.md", card("go halted", status="stopped"))

    def test_header_counts_three_states(self):
        _, out, _ = self.run_cli(["list"])
        self.assertEqual(out.split("\n")[0], "Now: 2026-10-26 10:59, Europe/Paris — 1 active, 2 recurring, 2 closed")

    def test_header_fr(self):
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        _, out, _ = self.run_cli(["list"], env=env)
        self.assertIn("— 1 actifs, 2 récurrents, 2 clos", out.split("\n")[0])
        self.assertIn("## Récurrents", out)
        self.assertIn("| Mot | Cadence | Prochain run | Délai depuis maintenant | Critère par run |", out)

    def test_recurring_table_apart(self):
        _, out, _ = self.run_cli(["list"])
        active, rest = out.split("## Recurring")
        self.assertIn("| go open |", active)
        self.assertNotIn("go monthly", active)
        self.assertIn("| Word | Cadence | Next run | Delay from now | Done when (per run) |", rest)
        self.assertIn("| go monthly | 2nd Wednesday 09:00 | 2026-11-11 09:00 |  | run done |", rest)
        self.assertIn("| go demand | on demand | - |  | run done |", rest)

    def test_stopped_filed_with_closed(self):
        _, out, _ = self.run_cli(["list"])
        self.assertNotIn("go halted", out)
        _, out, _ = self.run_cli(["list", "--closed"])
        closed = out.split("## Closed")[1]
        self.assertIn("| go halted (stopped) |", closed)

    def test_closed_follow_up_column(self):
        self.write("c.md", card("go done", status="closed", done="'shipped'").replace(
            "  done_when:", "  follow_up: 'post at 07:30'\n  done_when:"))
        _, out, _ = self.run_cli(["list", "--closed"])
        self.assertIn("| Word | Done when | Follow-up |", out)
        self.assertIn("| go done | shipped | post at 07:30 |", out)

    def test_recurring_not_stale_nor_hygiene(self):
        self.write("r.md", rec("go monthly", cadence="'m'", next_run="2026-11-11").replace("body", "x" * 30000))
        ts = datetime(2026, 9, 1, tzinfo=PARIS).timestamp()
        os.utime(os.path.join(self.mem, "r.md"), (ts, ts))
        _, out, _ = self.run_cli(["list"])
        self.assertNotIn("Heavy", out)
        self.assertNotIn("card unchanged", out)

    def test_recurring_delay_when_run_reached(self):
        self.write("r.md", rec("go monthly", next_run="2026-10-26 09:00"))
        _, out, _ = self.run_cli(["list"])
        row = [ln for ln in out.split("\n") if ln.startswith("| go monthly")][0]
        self.assertIn("| OVERDUE by 1 h 59 |", row)


class HookCase(Base):
    def lines(self, argv=("hook",)):
        code, out, _ = self.run_cli(list(argv), stdin="{}")
        return json.loads(out)["systemMessage"].split("\n") if out else []

    def test_recurring_absent_before_its_run(self):
        self.write("r.md", rec("go monthly", next_run="2026-10-27 09:00"))
        self.assertEqual(self.lines(), [])

    def test_on_demand_never_in_hook(self):
        self.write("r.md", rec("go demand", cadence="'on demand'"))
        self.assertEqual(self.lines(), [])

    def test_recurring_launchable_once_run_reached(self):
        self.write("o.md", card("go open"))
        self.write("r.md", rec("go monthly", next_run="2026-10-26 09:00"))
        lines = self.lines()
        self.assertEqual(lines[2], "- go monthly: run due 2026-10-26 09:00, OVERDUE by 1 h 59 — run done")
        self.assertEqual(lines[3], "- go open: no due date — it ships")

    def test_recurring_launchable_fr(self):
        self.write("r.md", rec("go monthly", next_run="2026-10-26"))
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        code, out, _ = self.run_cli(["hook"], env=env, stdin="{}")
        lines = json.loads(out)["systemMessage"].split("\n")
        self.assertEqual(lines[2], "- go monthly : run prévu 2026-10-26, DÉPASSÉE de 10 h 59 — run done")

    def test_stopped_and_closed_with_follow_up_silent(self):
        self.write("s.md", card("go halted", status="stopped", due="2026-10-25"))
        self.write("c.md", card("go done", status="closed").replace(
            "  done_when:", "  follow_up: 'post at 07:30'\n  done_when:"))
        self.assertEqual(self.lines(), [])


if __name__ == "__main__":
    unittest.main()
