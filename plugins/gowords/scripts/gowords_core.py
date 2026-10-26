"""Workstream registry: frontmatter reader, workstream model and deadline logic.

Standard library only.
"""
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


class FrontmatterError(ValueError):
    """Raised when the frontmatter uses syntax this reader does not support."""


def _split_items(inner):
    items, cur, quote, i = [], "", None, 0
    while i < len(inner):
        ch = inner[i]
        if quote == "'":
            cur += ch
            if ch == "'":
                if inner[i + 1:i + 2] == "'":
                    cur += "'"
                    i += 1
                else:
                    quote = None
        elif quote == '"':
            cur += ch
            if ch == "\\" and i + 1 < len(inner):
                cur += inner[i + 1]
                i += 1
            elif ch == '"':
                quote = None
        elif ch in "'\"":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    if quote:
        raise FrontmatterError("unterminated quote in list")
    items.append(cur)
    return [s.strip() for s in items if s.strip()]


def _scalar(raw):
    raw = raw.strip()
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            raise FrontmatterError("unterminated single quote: " + raw)
        return raw[1:-1].replace("''", "'")
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"'):
            raise FrontmatterError("unterminated double quote: " + raw)
        out, body, i = "", raw[1:-1], 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out += {"n": "\n", "t": "\t"}.get(nxt, nxt)
                i += 2
            else:
                out += body[i]
                i += 1
        return out
    return raw


def _value(raw):
    raw = raw.strip()
    if raw[:1] in ("|", ">"):
        raise FrontmatterError("block scalars are not supported: " + raw)
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise FrontmatterError("unterminated list: " + raw)
        return [_scalar(s) for s in _split_items(raw[1:-1])]
    return _scalar(raw)


def _quote_end(raw, start):
    """Index just after the quoted string that opens at raw[start], or -1."""
    q, i = raw[start], start + 1
    while i < len(raw):
        ch = raw[i]
        if q == "'" and ch == "'":
            if raw[i + 1:i + 2] == "'":
                i += 2
                continue
            return i + 1
        if q == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                return i + 1
        i += 1
    return -1


def _strip_comment(raw):
    """Drop a trailing ' # comment' that sits outside quotes and outside [...]."""
    raw = raw.strip()
    if raw.startswith("#"):
        return ""
    end = -1
    if raw[:1] in ("'", '"'):
        end = _quote_end(raw, 0)
    elif raw.startswith("["):
        i = 1
        while i < len(raw):
            if raw[i] in "'\"" and raw[i - 1] in "[, \t":
                nxt = _quote_end(raw, i)
                if nxt < 0:
                    return raw
                i = nxt
                continue
            if raw[i] == "]":
                end = i + 1
                break
            i += 1
    else:
        m = re.search(r"\s#", raw)
        return raw[:m.start()].rstrip() if m else raw
    if end < 0:
        return raw
    rest = raw[end:]
    if rest.strip().startswith("#") and (not rest[:1].strip() or rest.lstrip().startswith("#") and rest[:1] in " \t"):
        return raw[:end]
    return raw


def _key_value(line):
    key, sep, rest = line.partition(":")
    if not sep or not key.strip():
        raise FrontmatterError("expected 'key: value': " + line)
    return key.strip(), _strip_comment(rest)


def parse_frontmatter(text):
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise FrontmatterError("frontmatter is not closed")
    body = [ln for ln in lines[1:end] if ln.strip() and not ln.lstrip().startswith("#")]
    result = {}
    i = 0
    while i < len(body):
        line = body[i]
        if line[0] in " \t":
            raise FrontmatterError("unexpected indentation: " + line)
        if line.startswith("-"):
            raise FrontmatterError("block lists are not supported: " + line)
        key, rest = _key_value(line)
        i += 1
        if rest:
            result[key] = _value(rest)
            continue
        children = []
        while i < len(body) and body[i][0] in " \t":
            children.append(body[i])
            i += 1
        if not children:
            result[key] = ""
            continue
        if children[0].strip().startswith("-"):
            raise FrontmatterError("block lists are not supported under: " + key)
        nested = {}
        for child in children:
            if len(child) - len(child.lstrip(" ")) != 2 or child[0] == "\t":
                raise FrontmatterError("nested keys must use 2-space indent: " + child)
            ckey, crest = _key_value(child.strip())
            if not crest:
                raise FrontmatterError("empty or block value under metadata: " + ckey)
            nested[ckey] = _value(crest)
        result[key] = nested
    return result


STATUS_MAP = {
    "open": "open", "ouvert": "open",
    "waiting": "waiting", "en attente": "waiting",
    "closed": "closed", "clos": "closed",
    "stopped": "stopped", "arrêté": "stopped",
}

LABELS = {
    "en": {
        "now": "now", "not_before": "not before {when} (in {delta})",
        "overdue": "OVERDUE by {delta}", "due": "in {delta}",
        "eod": " (end of day)", "d": "d",
        "waiting": "waiting on {who}", "and": "; ",
    },
    "fr": {
        "now": "maintenant", "not_before": "pas avant {when} (dans {delta})",
        "overdue": "DÉPASSÉE de {delta}", "due": "dans {delta}",
        "eod": " (fin de journée)", "d": "j",
        "waiting": "attend : {who}", "and": " ; ",
    },
}


@dataclass
class Workstream:
    word: str
    aliases: list
    status: str
    due: object
    due_timed: bool
    not_before: object
    done_when: str
    path: str
    age_days: int
    not_before_timed: bool = False
    waiting_on: str = ""
    size: int = 0


def parse_due(value, tz, day_time=time(23, 59)):
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' in tz. A bare date gets day_time.

    Returns (aware datetime, carries a time of day) or raises ValueError.
    """
    s = str(value).strip()
    if len(s) == 10:
        return datetime.combine(date.fromisoformat(s), day_time, tz), False
    dt = datetime.fromisoformat(s)
    return (dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)), True


def _real_delta(a, b):
    """a - b in real elapsed time (same-zone aware datetimes subtract by wall clock)."""
    return a.astimezone(timezone.utc) - b.astimezone(timezone.utc)


def format_delta(td, lang="en"):
    minutes = int(abs(td.total_seconds()) // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    unit = LABELS[lang]["d"]
    if days:
        return f"{days} {unit} {hours} h" if hours else f"{days} {unit}"
    return f"{hours} h {minutes:02d}" if hours else f"{minutes} min"


def launch_label(w, now, lang="en"):
    labels = LABELS[lang]
    waiting = labels["waiting"].format(who=w.waiting_on) if w.waiting_on else ""
    if w.not_before is None or w.not_before <= now:
        return waiting or labels["now"]
    tz = now.tzinfo
    nb = w.not_before.astimezone(tz)
    if not w.not_before_timed:
        when = nb.date().isoformat()
    elif nb.date() == now.date():
        when = nb.strftime("%H:%M")
    else:
        when = nb.strftime("%Y-%m-%d %H:%M")
    label = labels["not_before"].format(when=when, delta=format_delta(_real_delta(w.not_before, now), lang))
    return label + labels["and"] + waiting if waiting else label


def due_label(w, now, lang="en"):
    if w.due is None:
        return ""
    labels = LABELS[lang]
    td = _real_delta(w.due, now)
    if td.total_seconds() < 0:
        return labels["overdue"].format(delta=format_delta(td, lang))
    if td <= timedelta(hours=48):
        return labels["due"].format(delta=format_delta(td, lang)) + ("" if w.due_timed else labels["eod"])
    return ""


def _aliases(raw):
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


PROBLEMS = {
    "en": {
        "read": "cannot read file ({reason})",
        "frontmatter": "unreadable frontmatter ({exc})",
        "status": "unknown status {raw!r}",
        "date": "{key} is not a date: {raw!r}",
        "done_when": "done_when is missing",
        "dup": "go_word {word!r} is used by several open workstreams ({files})",
    },
    "fr": {
        "read": "fichier illisible ({reason})",
        "frontmatter": "frontmatter illisible ({exc})",
        "status": "statut inconnu {raw!r}",
        "date": "{key} : date illisible {raw!r}",
        "done_when": "done_when absent",
        "dup": "mot {word!r} porté par plusieurs fiches ouvertes ({files})",
    },
}


def load_workstreams(memory_dir, tz, now, lang="en"):
    """Read every workstream card in memory_dir.

    Returns (workstreams, problems); each problem line starts with the file name.
    The fixed text of the problem lines follows lang.
    """
    pb = PROBLEMS[lang]
    workstreams, problems = [], []
    today = now.astimezone(tz).date()
    for name in sorted(os.listdir(memory_dir)):
        if not name.endswith(".md") or name == "MEMORY.md":
            continue
        path = os.path.join(memory_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
            problems.append(f"{name}: " + pb["read"].format(reason=reason))
            continue
        text = text.lstrip("\ufeff")
        if not text.startswith("---"):
            continue
        try:
            meta = parse_frontmatter(text).get("metadata")
        except FrontmatterError as exc:
            problems.append(f"{name}: " + pb["frontmatter"].format(exc=exc))
            continue
        if not isinstance(meta, dict) or "go_word" not in meta:
            continue

        raw_status = str(meta.get("status", "")).strip()
        status = STATUS_MAP.get(raw_status.lower())
        if status is None:
            problems.append(f"{name}: " + pb["status"].format(raw=raw_status))
            status = raw_status.lower() or "?"

        dates = {}
        for key, day_time in (("next_due", time(23, 59)), ("not_before", time(0, 0))):
            dates[key] = (None, False)
            if meta.get(key):
                try:
                    dates[key] = parse_due(meta[key], tz, day_time)
                except ValueError:
                    problems.append(f"{name}: " + pb["date"].format(key=key, raw=meta[key]))

        done_when = str(meta.get("done_when", "")).strip()
        if not done_when:
            problems.append(f"{name}: " + pb["done_when"])

        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz).date()
        workstreams.append(Workstream(
            word=str(meta["go_word"]).strip(),
            aliases=_aliases(meta.get("aliases")),
            status=status,
            due=dates["next_due"][0],
            due_timed=dates["next_due"][1],
            not_before=dates["not_before"][0],
            done_when=done_when,
            path=path,
            age_days=(today - mtime).days,
            not_before_timed=dates["not_before"][1],
            waiting_on=str(meta.get("waiting_on", "")).strip(),
            size=os.path.getsize(path),
        ))

    seen = {}
    for w in workstreams:
        if w.status != "closed":
            seen.setdefault(w.word.casefold(), []).append(w)
    for group in seen.values():
        if len(group) > 1:
            files = ", ".join(os.path.basename(w.path) for w in group)
            problems.append(f"{os.path.basename(group[0].path)}: " + pb["dup"].format(word=group[0].word, files=files))
    return workstreams, problems


# --- memory directory -------------------------------------------------------

def encode_project_path(path):
    """Claude Code's project folder name: every '/' and '.' becomes '-'.

    Observed for plain paths and for paths with dots. Behaviour for '_' and
    spaces in a path is not verified.
    """
    return path.replace("/", "-").replace(".", "-")


def _home(env):
    return env.get("HOME") or os.path.expanduser("~")


def _main_checkout(cwd):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return cwd
    common = out.stdout.strip()
    if out.returncode != 0 or not common or os.path.basename(common) != ".git":
        return cwd
    return os.path.dirname(common)


def candidate_memory_dir(cwd, env):
    """The directory resolve_memory_dir looks for, whether or not it exists."""
    option = read_options(env)["memory_dir"]
    if option:
        return os.path.expanduser(option)
    root = _main_checkout(cwd)
    return os.path.join(_home(env), ".claude", "projects", encode_project_path(root), "memory")


def resolve_memory_dir(cwd, env):
    path = candidate_memory_dir(cwd, env)
    return path if os.path.isdir(path) else None


# --- options and time zone --------------------------------------------------

def read_options(env):
    """The only place that reads plugin option environment variables."""
    def get(name):
        value = env.get("CLAUDE_PLUGIN_OPTION_" + name, "").strip()
        # An option the user never set reaches the skill as the literal "${user_config.<key>}".
        return "" if value.startswith("${user_config.") else value
    lang = get("LANGUAGE").lower()
    try:
        stale = int(float(get("STALE_DAYS")))
        if stale < 1:
            stale = 14
    except (ValueError, OverflowError):
        stale = 14
    return {
        "timezone": get("TIMEZONE"),
        "language": lang if lang in LABELS else "en",
        "stale_days": stale,
        "memory_dir": get("MEMORY_DIR"),
        "session_alert": get("SESSION_ALERT").lower() != "off",
    }


def _zone(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def resolve_tz(option, env):
    """Configured IANA zone, else the system zone (TZ, /etc/localtime, fixed offset)."""
    tz = _zone(option) if option else None
    if tz:
        return tz
    tz = _zone(env.get("TZ", "").lstrip(":")) if env.get("TZ") else None
    if tz:
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            tz = _zone(target.split("zoneinfo/", 1)[1])
            if tz:
                return tz
    except OSError:
        pass
    return datetime.now().astimezone().tzinfo


def tz_name(tz, now):
    return getattr(tz, "key", None) or now.tzname() or str(tz)


# --- rendering --------------------------------------------------------------

TEXT = {
    "en": {
        "header": "Now: {now}, {zone} — {a} active, {c} closed",
        "active": "## Active, sorted by due date ({zone}; a bare date means due by end of day)",
        "cols": "| Word | Status | Launchable | Due | Delay from now | Done when |",
        "closed": "## Closed", "closed_cols": "| Word | Done when |",
        "alias": " (alias: {a})", "stale": "no due date, card unchanged for {n} {u}",
        "problems": "Problems: ",
        "closed_hidden": "{n} closed — list --closed to show them",
        "heavy": "Heavy files (> 20 KB): {items}",
        "long": "Long done_when (> 250 chars): {items}",
        "hint": "No memory directory found at {path}.\nCreate it by starting a workstream with: go new <word>",
        "hook": "Go words due within 48 h (now: {now}, {zone}) — full list: /gowords:go",
        "line": "- {word}: {due}, {delay}; launchable {launch} — {done}",
        "more": "- … {n} more: /gowords:go",
        "status": {"open": "open", "waiting": "waiting", "closed": "closed", "stopped": "stopped"},
    },
    "fr": {
        "header": "Maintenant : {now}, {zone} — {a} actifs, {c} clos",
        "active": "## Actifs, triés par échéance ({zone} ; une date seule = due dans la journée)",
        "cols": "| Mot | Statut | Lançable | Échéance | Délai depuis maintenant | Critère de fin |",
        "closed": "## Clos", "closed_cols": "| Mot | Critère de fin |",
        "alias": " (alias : {a})", "stale": "sans échéance, fiche inchangée depuis {n} {u}",
        "problems": "Problèmes : ",
        "closed_hidden": "{n} clos — list --closed pour les afficher",
        "heavy": "Fiches lourdes (> 20 Ko) : {items}",
        "long": "done_when longs (> 250 car.) : {items}",
        "hint": "Aucun dossier mémoire trouvé à {path}.\nCréez-le en lançant un chantier : go new <mot>",
        "hook": "Mots « go » à échéance ≤ 48 h (maintenant : {now}, {zone}) — liste complète : /gowords:go",
        "line": "- {word} : {due}, {delay} ; lançable {launch} — {done}",
        "more": "- … {n} de plus : /gowords:go",
        "status": {"open": "ouvert", "waiting": "en attente", "closed": "clos", "stopped": "arrêté"},
    },
}

_FAR = datetime.max.replace(tzinfo=timezone.utc)


def _sort_key(w):
    return (w.due.astimezone(timezone.utc) if w.due else _FAR, w.word.casefold())


def _fmt_due(w, tz):
    if w.due is None:
        return ""
    d = w.due.astimezone(tz)
    return d.strftime("%Y-%m-%d %H:%M") if w.due_timed else d.date().isoformat()


def split_workstreams(ws):
    active = sorted((w for w in ws if w.status != "closed"), key=_sort_key)
    closed = sorted((w for w in ws if w.status == "closed"), key=lambda w: w.word.casefold())
    return active, closed


def render_hint(path, lang="en"):
    return TEXT[lang]["hint"].format(path=path)


HEAVY_BYTES = 20000
LONG_DONE_CHARS = 250
HOOK_DONE_CHARS = 120
HOOK_DONE_WORD_FROM = 80


def _cut_done(text):
    """At most HOOK_DONE_CHARS characters, cut on a word boundary when one follows char 80."""
    if len(text) <= HOOK_DONE_CHARS:
        return text
    head = text[:HOOK_DONE_CHARS]
    space = head.rfind(" ")
    if space > HOOK_DONE_WORD_FROM:
        head = head[:space]
    return head.rstrip() + "…"


def hygiene_lines(active, lang="en"):
    """Up to two lines about heavy cards and long done_when, for non-closed workstreams."""
    t = TEXT[lang]
    unit = "KB" if lang == "en" else "Ko"
    heavy = sorted((w for w in active if w.size > HEAVY_BYTES), key=lambda w: (-w.size, w.word.casefold()))
    long_ = sorted((w for w in active if len(w.done_when) > LONG_DONE_CHARS), key=lambda w: (-len(w.done_when), w.word.casefold()))
    out = []
    if heavy:
        out.append(t["heavy"].format(items=", ".join(f"{w.word} ({round(w.size / 1000)} {unit})" for w in heavy)))
    if long_:
        out.append(t["long"].format(items=", ".join(f"{w.word} ({len(w.done_when)})" for w in long_)))
    return out


def render_list(ws, problems, now, lang="en", stale_days=14, show_closed=False):
    t = TEXT[lang]
    tz = now.tzinfo
    zone = tz_name(tz, now)
    active, closed = split_workstreams(ws)
    out = [t["header"].format(now=now.strftime("%Y-%m-%d %H:%M"), zone=zone, a=len(active), c=len(closed)), "",
           t["active"].format(zone=zone), "", t["cols"], "|---|---|---|---|---|---|"]
    for w in active:
        alias = t["alias"].format(a=", ".join(w.aliases)) if w.aliases else ""
        flag = due_label(w, now, lang) if w.due else ""
        if not w.due and w.status == "open" and w.age_days > stale_days:
            flag = t["stale"].format(n=w.age_days, u=LABELS[lang]["d"])
        status = t["status"].get(w.status, w.status)
        out.append(f"| {w.word}{alias} | {status} | {launch_label(w, now, lang)} | {_fmt_due(w, tz) or '-'} | {flag} | {w.done_when} |")
    if show_closed:
        out += ["", t["closed"], "", t["closed_cols"], "|---|---|"]
        out += [f"| {w.word} | {w.done_when} |" for w in closed]
    elif closed:
        out += ["", t["closed_hidden"].format(n=len(closed))]
    if problems:
        out += ["", t["problems"] + "; ".join(problems)]
    hygiene = hygiene_lines(active, lang)
    if hygiene:
        out += [""] + hygiene
    return "\n".join(out)


def render_hook(ws, now, lang="en"):
    """At most 5 lines of detail; empty when nothing is due within 48 h or overdue."""
    t = TEXT[lang]
    tz = now.tzinfo
    active, _ = split_workstreams(ws)
    active = [w for w in active if w.status != "stopped"]
    soon = [w for w in active if w.due and due_label(w, now, lang)]
    if not soon:
        return ""
    out = [t["hook"].format(now=now.strftime("%Y-%m-%d %H:%M"), zone=tz_name(tz, now))]
    for w in soon[:5]:
        out.append(t["line"].format(word=w.word, due=_fmt_due(w, tz), delay=due_label(w, now, lang),
                                    launch=launch_label(w, now, lang), done=_cut_done(w.done_when)))
    if len(soon) > 5:
        out.append(t["more"].format(n=len(soon) - 5))
    return "\n".join(out)
