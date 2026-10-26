#!/usr/bin/env python3
"""gowords command line: list [--closed] | hook | find <word> | where. Standard library only."""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gowords_core import (  # noqa: E402
    candidate_memory_dir, load_workstreams, read_options, render_hint, render_hook,
    render_list, resolve_memory_dir, resolve_tz,
)

USAGE = "usage: gowords.py list [--closed] | hook | find <word> | where"


def _normalize(word):
    w = word.strip().casefold()
    return w[3:].strip() if w.startswith("go ") else w


def _names(w):
    return {_normalize(n) for n in [w.word, *w.aliases]}


def main(argv, env=None, now=None, cwd=None):
    env = os.environ if env is None else env
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2
    cmd = argv[0]
    opts = read_options(env)
    tz = resolve_tz(opts["timezone"], env)
    now = now.astimezone(tz) if now else datetime.now(tz)
    lang = opts["language"]

    if cmd == "hook":
        if not opts["session_alert"]:
            return 0
        try:
            data = json.loads(sys.stdin.read() or "{}")
            cwd = (data.get("cwd") if isinstance(data, dict) else None) or cwd
        except (ValueError, OSError):
            pass
        mem = resolve_memory_dir(cwd or os.getcwd(), env)
        if not mem:
            return 0
        ws, _ = load_workstreams(mem, tz, now, lang)
        text = render_hook(ws, now, lang)
        if text:
            print(json.dumps({
                "systemMessage": text,
                "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text},
            }, ensure_ascii=False))
        return 0

    cwd = cwd or os.getcwd()
    wanted = candidate_memory_dir(cwd, env)
    mem = resolve_memory_dir(cwd, env)

    if cmd == "where":
        if not mem:
            print(f"no memory directory at {wanted}", file=sys.stderr)
            return 1
        print(mem)
        return 0
    if cmd == "list":
        if not mem:
            print(render_hint(wanted, lang))
            return 0
        ws, problems = load_workstreams(mem, tz, now, lang)
        print(render_list(ws, problems, now, lang, opts["stale_days"], show_closed="--closed" in argv[1:]))
        return 0
    if cmd == "find" and len(argv) == 2:
        if not mem:
            print(f"no memory directory at {wanted}", file=sys.stderr)
            return 1
        ws, _ = load_workstreams(mem, tz, now)
        target = _normalize(argv[1])
        hits = [w for w in ws if target in _names(w)]
        if not hits:
            print(f"no workstream matches {argv[1]!r}", file=sys.stderr)
            return 1
        for w in hits:
            print(os.path.abspath(w.path))
        return 0 if len(hits) == 1 else 2
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
