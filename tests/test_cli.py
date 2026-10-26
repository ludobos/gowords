import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import gowords
from gowords_core import encode_project_path, load_workstreams, read_options, render_hook, render_list, resolve_memory_dir

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 26, 10, 59, tzinfo=PARIS)


def card(word, status="open", due=None, aliases=None, done="'it ships'"):
    lines = ["---", "name: n", "metadata:", f"  go_word: '{word}'", f"  status: {status}", f"  done_when: {done}"]
    if due:
        lines.append(f"  next_due: '{due}'")
    if aliases:
        lines.append("  aliases: [" + ", ".join(f"'{a}'" for a in aliases) + "]")
    lines += ["---", "body"]
    return "\n".join(lines)


def git(*args, cwd):
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
    )


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = os.path.realpath(tmp.name)
        self.mem = os.path.join(self.tmp, "mem")
        os.makedirs(self.mem)
        self.env = {"HOME": self.tmp, "CLAUDE_PLUGIN_OPTION_MEMORY_DIR": self.mem,
                    "CLAUDE_PLUGIN_OPTION_TIMEZONE": "Europe/Paris"}

    def write(self, name, text):
        with open(os.path.join(self.mem, name), "w", encoding="utf-8") as f:
            f.write(text)

    def run_cli(self, argv, env=None, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin)):
            code = gowords.main(argv, env if env is not None else self.env, now=NOW)
        return code, out.getvalue(), err.getvalue()


def _hook_text(self, out):
    return json.loads(out)["systemMessage"]


Base.hook_text = _hook_text


class MemoryDirCase(Base):
    def test_encode_project_path(self):
        self.assertEqual(encode_project_path("/home/u/my-repo"), "-home-u-my-repo")
        self.assertEqual(encode_project_path("/home/u/repo/.claude/worktrees/w"), "-home-u-repo--claude-worktrees-w")

    def test_worktree_resolves_to_main_checkout(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        git("init", "-q", cwd=repo)
        git("commit", "--allow-empty", "-q", "-m", "i", cwd=repo)
        wt = os.path.join(self.tmp, "wt")
        git("worktree", "add", "-q", wt, "-b", "b", cwd=repo)
        expected = os.path.join(self.tmp, ".claude", "projects", encode_project_path(repo), "memory")
        os.makedirs(expected)
        env = {"HOME": self.tmp}
        self.assertEqual(resolve_memory_dir(wt, env), expected)

    def test_option_memory_dir_wins(self):
        self.assertEqual(resolve_memory_dir("/nowhere", self.env), self.mem)

    def test_option_memory_dir_read_through_options(self):
        env = {"HOME": self.tmp, "CLAUDE_PLUGIN_OPTION_MEMORY_DIR": "  " + self.mem + "  "}
        self.assertEqual(read_options(env)["memory_dir"], self.mem)
        self.assertEqual(resolve_memory_dir(self.tmp, env), self.mem)

    def test_unresolved_option_placeholder_counts_as_unset(self):
        env = {k: "${user_config.x}" for k in (
            "CLAUDE_PLUGIN_OPTION_TIMEZONE", "CLAUDE_PLUGIN_OPTION_LANGUAGE", "CLAUDE_PLUGIN_OPTION_STALE_DAYS",
            "CLAUDE_PLUGIN_OPTION_MEMORY_DIR", "CLAUDE_PLUGIN_OPTION_SESSION_ALERT")}
        self.assertEqual(read_options(env), {
            "timezone": "", "language": "en", "stale_days": 14, "memory_dir": "", "session_alert": True})

    def test_non_repo_falls_back_to_cwd(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        expected = os.path.join(self.tmp, ".claude", "projects", encode_project_path(plain), "memory")
        os.makedirs(expected)
        self.assertEqual(resolve_memory_dir(plain, {"HOME": self.tmp}), expected)

    def test_missing_dir_is_none(self):
        self.assertIsNone(resolve_memory_dir(self.tmp, {"HOME": self.tmp}))


class CliCase(Base):
    def test_list_without_memory_dir_prints_hint(self):
        env = {"HOME": self.tmp}
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gowords.main(["list"], env, now=NOW, cwd=self.tmp)
        self.assertEqual(code, 0)
        self.assertIn("go new", out.getvalue())
        self.assertIn(os.path.join(self.tmp, ".claude", "projects"), out.getvalue())

    def test_hook_silent_without_deadlines(self):
        self.write("a.md", card("go a", due="2026-12-01"))
        self.write("b.md", card("go b"))
        code, out, _ = self.run_cli(["hook"], stdin="{}")
        self.assertEqual((code, out), (0, ""))

    def test_hook_silent_without_memory_dir(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO("{}")):
            code = gowords.main(["hook"], {"HOME": self.tmp}, now=NOW, cwd=self.tmp)
        self.assertEqual((code, out.getvalue()), (0, ""))

    def test_hook_max_five_lines(self):
        for i in range(7):
            self.write(f"f{i}.md", card(f"go w{i}", due="2026-10-25"))
        code, out, _ = self.run_cli(["hook"], stdin=json.dumps({"cwd": self.tmp}))
        lines = self.hook_text(out).split("\n")
        self.assertEqual(len(lines), 7)  # header + 5 + more
        self.assertIn("… 2 more", lines[-1])
        self.assertIn("OVERDUE", lines[1])

    def test_hook_bad_stdin_does_not_crash(self):
        self.write("a.md", card("go a", due="2026-10-26 12:00"))
        code, out, _ = self.run_cli(["hook"], stdin="not json")
        self.assertEqual(code, 0)
        self.assertIn("go a", self.hook_text(out))

    def test_hook_json_shape(self):
        self.write("a.md", card("go a", due="2026-10-26 12:00"))
        code, out, _ = self.run_cli(["hook"], stdin="{}")
        data = json.loads(out)
        text = data["systemMessage"]
        self.assertIn("go a", text)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(data["hookSpecificOutput"]["additionalContext"], text)
        self.assertEqual(set(data), {"systemMessage", "hookSpecificOutput"})

    def test_hook_silent_for_stopped_and_closed_overdue(self):
        self.write("a.md", card("go a", status="stopped", due="2026-10-20"))
        self.write("b.md", card("go b", status="closed", due="2026-10-20"))
        code, out, _ = self.run_cli(["hook"], stdin="{}")
        self.assertEqual((code, out), (0, ""))

    def test_list_keeps_stopped_in_active_table(self):
        self.write("a.md", card("go a", status="stopped", due="2026-10-20"))
        code, out, _ = self.run_cli(["list"])
        self.assertIn("| go a | stopped |", out)

    def test_stale_days_float_string(self):
        self.assertEqual(read_options({"CLAUDE_PLUGIN_OPTION_STALE_DAYS": "14.0"})["stale_days"], 14)
        self.assertEqual(read_options({"CLAUDE_PLUGIN_OPTION_STALE_DAYS": "30.0"})["stale_days"], 30)
        self.assertEqual(read_options({"CLAUDE_PLUGIN_OPTION_STALE_DAYS": "abc"})["stale_days"], 14)
        self.assertEqual(read_options({"CLAUDE_PLUGIN_OPTION_STALE_DAYS": "nan"})["stale_days"], 14)

    def test_session_alert_off(self):
        self.write("a.md", card("go a", due="2026-10-25"))
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_SESSION_ALERT": "off"}
        code, out, _ = self.run_cli(["hook"], env=env, stdin="{}")
        self.assertEqual((code, out), (0, ""))

    def test_find_by_alias_and_without_prefix(self):
        self.write("a.md", card("go alpha", aliases=["al"]))
        for q in ("go alpha", "ALPHA", "go al", "Al"):
            code, out, _ = self.run_cli(["find", q])
            self.assertEqual(code, 0, q)
            self.assertEqual(out.strip(), os.path.join(self.mem, "a.md"))
        code, out, err = self.run_cli(["find", "zzz"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().split("\n")), 1)

    def test_find_several_matches_exit_2(self):
        self.write("a.md", card("go alpha"))
        self.write("b.md", card("go alpha"))
        code, out, _ = self.run_cli(["find", "alpha"])
        self.assertEqual(code, 2)
        self.assertEqual(len(out.strip().split("\n")), 2)

    def test_where(self):
        code, out, _ = self.run_cli(["where"])
        self.assertEqual((code, out.strip()), (0, self.mem))

    def test_list_sections(self):
        self.write("late.md", card("go late", due="2026-11-30"))
        self.write("soon.md", card("go soon", due="2026-10-27 09:00"))
        self.write("none.md", card("go none"))
        self.write("done.md", card("go done", status="closed"))
        old = os.path.join(self.mem, "none.md")
        ts = (NOW - timedelta(days=20)).timestamp()
        os.utime(old, (ts, ts))
        code, out, _ = self.run_cli(["list", "--closed"])
        self.assertEqual(code, 0)
        lines = out.split("\n")
        self.assertEqual(lines[0], "Now: 2026-10-26 10:59, Europe/Paris — 3 active, 1 closed")
        self.assertIn("| Word | Status | Launchable | Due | Delay from now | Done when |", out)
        self.assertLess(out.index("go soon"), out.index("go late"))
        self.assertLess(out.index("go late"), out.index("go none"))
        self.assertLess(out.index("go none"), out.index("## Closed"))
        self.assertIn("go done", out.split("## Closed")[1])
        self.assertIn("in 22 h 01", out)
        self.assertIn("no due date, card unchanged for 20 d", out)

    def test_list_french_and_problems(self):
        self.write("a.md", card("go a", due="2026-10-25"))
        self.write("bad.md", "---\nmetadata:\n  go_word: 'go x'\n  status: weird\n  done_when: 'x'\n---\n")
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        code, out, _ = self.run_cli(["list"], env=env)
        self.assertIn("Maintenant : 2026-10-26 10:59, Europe/Paris — 2 actifs, 0 clos", out)
        self.assertIn("DÉPASSÉE", out)
        self.assertIn("Problèmes :", out)

    def test_list_duplicates_reported(self):
        self.write("a.md", card("go a"))
        self.write("b.md", card("go a"))
        code, out, _ = self.run_cli(["list"])
        self.assertIn("several open workstreams", out)


class ClosedListCase(Base):
    def setUp(self):
        super().setUp()
        self.write("a.md", card("go a"))
        self.write("b.md", card("go b", status="closed", done="'shipped'"))
        self.write("c.md", card("go c", status="closed"))

    def test_closed_hidden_by_default(self):
        _, out, _ = self.run_cli(["list"])
        self.assertNotIn("## Closed", out)
        self.assertNotIn("shipped", out)
        self.assertIn("2 closed — list --closed to show them", out)

    def test_closed_hidden_french(self):
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        _, out, _ = self.run_cli(["list"], env=env)
        self.assertNotIn("## Clos", out)
        self.assertIn("2 clos — list --closed pour les afficher", out)

    def test_closed_shown_with_flag(self):
        _, out, _ = self.run_cli(["list", "--closed"])
        self.assertIn("## Closed", out)
        self.assertIn("| go b | shipped |", out)
        self.assertNotIn("list --closed to show", out)

    def test_no_closed_line_when_none(self):
        os.remove(os.path.join(self.mem, "b.md"))
        os.remove(os.path.join(self.mem, "c.md"))
        _, out, _ = self.run_cli(["list"])
        self.assertNotIn("closed —", out)


class HookCutCase(Base):
    def test_long_done_when_is_cut(self):
        self.write("a.md", card("go a", due="2026-10-25", done="'" + "word " * 60 + "'"))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        line = self.hook_text(out).split("\n")[1]
        crit = line.split(" — ", 1)[1]
        self.assertLessEqual(len(crit), 121)
        self.assertTrue(crit.endswith("…"))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["additionalContext"], self.hook_text(out))

    def test_cut_without_space_after_80_is_hard(self):
        self.write("a.md", card("go a", due="2026-10-25", done="'" + "x" * 300 + "'"))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        crit = self.hook_text(out).split("\n")[1].split(" — ", 1)[1]
        self.assertEqual(crit, "x" * 120 + "…")

    def test_short_done_when_unchanged(self):
        self.write("a.md", card("go a", due="2026-10-25", done="'it ships'"))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        self.assertTrue(self.hook_text(out).split("\n")[1].endswith("— it ships"))


def waiting_card(word, extra, status="open", due=None):
    return card(word, status=status, due=due).replace("  done_when:", extra + "\n  done_when:")


class WaitingHookCase(Base):
    def test_hook_waiting_en(self):
        self.write("a.md", waiting_card("go a", "  waiting_on: 'Bob'", due="2026-10-25"))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        line = self.hook_text(out).split("\n")[1]
        self.assertIn("not launchable, waiting on Bob", line)
        self.assertNotIn("; launchable", line)

    def test_hook_waiting_fr(self):
        self.write("a.md", waiting_card("go a", "  waiting_on: 'Bob'", due="2026-10-25"))
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        _, out, _ = self.run_cli(["hook"], env=env, stdin="{}")
        line = self.hook_text(out).split("\n")[1]
        self.assertIn("non lançable, attend : Bob", line)
        self.assertNotIn("; lançable", line)

    def test_hook_waiting_with_future_not_before(self):
        self.write("a.md", waiting_card("go a", "  waiting_on: 'Bob'\n  not_before: '2026-10-27 12:00'", due="2026-10-25"))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        self.assertIn("not launchable, not before 2026-10-27 12:00 (in 1 d 1 h); waiting on Bob",
                      self.hook_text(out))

    def test_list_waiting_with_past_not_before(self):
        self.write("a.md", waiting_card("go a", "  waiting_on: 'Bob'\n  not_before: '2026-10-20'"))
        _, out, _ = self.run_cli(["list"])
        row = [ln for ln in out.split("\n") if ln.startswith("| go a")][0]
        self.assertIn("| waiting on Bob |", row)


class HygieneStatusCase(Base):
    def test_stopped_kept_closed_excluded(self):
        self.write("s.md", card("go s", status="stopped").replace("body", "x" * 30000))
        self.write("c.md", card("go c", status="closed").replace("body", "x" * 30000))
        _, out, _ = self.run_cli(["list"])
        self.assertIn("Heavy files (> 20 KB): go s (30 KB)", out)
        self.assertNotIn("go c (", out)


class HygieneCase(Base):
    def test_heavy_and_long_lines_en(self):
        self.write("a.md", card("go a") .replace("body", "x" * 115000))
        self.write("b.md", card("go b").replace("body", "x" * 27000))
        self.write("c.md", card("go c", done="'" + "y" * 369 + "'"))
        self.write("d.md", card("go d", done="'" + "y" * 297 + "'"))
        self.write("e.md", card("go e", status="closed", done="'" + "y" * 400 + "'").replace("body", "x" * 90000))
        _, out, _ = self.run_cli(["list", "--closed"])
        self.assertIn("Heavy files (> 20 KB): go a (115 KB), go b (27 KB)", out)
        self.assertIn("Long done_when (> 250 chars): go c (369), go d (297)", out)
        self.assertNotIn("go e (", out)

    def test_heavy_and_long_lines_fr(self):
        self.write("a.md", card("go a").replace("body", "x" * 21000))
        self.write("c.md", card("go c", done="'" + "y" * 251 + "'"))
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        _, out, _ = self.run_cli(["list"], env=env)
        self.assertIn("Fiches lourdes (> 20 Ko) : go a (21 Ko)", out)
        self.assertIn("done_when longs (> 250 car.) : go c (251)", out)

    def test_no_line_below_thresholds(self):
        self.write("a.md", card("go a", done="'" + "y" * 250 + "'"))
        _, out, _ = self.run_cli(["list"])
        self.assertNotIn("Heavy", out)
        self.assertNotIn("Long done_when", out)

    def test_not_in_hook(self):
        self.write("a.md", card("go a", due="2026-10-25").replace("body", "x" * 30000))
        _, out, _ = self.run_cli(["hook"], stdin="{}")
        self.assertNotIn("Heavy", out)

    def test_french_problem_lines(self):
        self.write("bad.md", "---\nmetadata:\n  go_word: 'go x'\n  status: weird\n  next_due: 'nope'\n---\n")
        self.write("worse.md", "---\nmetadata:\n  go_word: 'go y'\n  aliases:\n    - x\n---\n")
        self.write("d1.md", card("go d"))
        self.write("d2.md", card("go d"))
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_LANGUAGE": "fr"}
        _, out, _ = self.run_cli(["list"], env=env)
        for frag in ("bad.md: statut inconnu", "bad.md: next_due : date illisible", "bad.md: done_when absent",
                     "worse.md: frontmatter illisible", "d1.md: mot 'go d' porté par plusieurs fiches"):
            self.assertIn(frag, out)
        self.assertNotIn("is missing", out)

    def test_english_problem_lines_unchanged(self):
        self.write("bad.md", "---\nmetadata:\n  go_word: 'go x'\n  status: weird\n---\n")
        _, out, _ = self.run_cli(["list"])
        self.assertIn("bad.md: unknown status 'weird'", out)
        self.assertIn("bad.md: done_when is missing", out)


class RenderCase(unittest.TestCase):
    def test_render_hook_empty(self):
        self.assertEqual(render_hook([], NOW, "en"), "")


if __name__ == "__main__":
    unittest.main()
