# gowords

A go word names one workstream, for example `go scheduled-check` or `go follow-up`. Each workstream is a markdown file with a short YAML frontmatter that holds its status, its due date, the earliest time its next action can produce anything (`not_before`), and the condition that closes it (`done_when`). The `/gowords:go` skill lists these files sorted by due date, recommends the 3 tasks that can start now, resumes one when you type `go <word>`, and writes a new one when you type `go new <word>`. A session-start hook prints the 3 workstreams that can start now (overdue or due within 48 hours first), then the ones that open or fall due within 48 hours; `gowords.py next` prints the same text. The files live in Claude Code's memory directory for the project, so every session on the same repository reads the same list.

The plugin is a skill, a hook and a Python script (3.9 or later) that uses the standard library only. There is no database and no server.

## Install

From the marketplace:

```
claude plugin marketplace add ludobos/gowords
claude plugin install gowords@gowords
```

The command is then `/gowords:go`. Phrases such as `go next`, `go <word>` or `list my workstreams` also trigger the skill through its description.

### Manual copy, for a bare `/go`

A plugin skill always carries the plugin prefix. To get `/go` without it, copy the skill and the scripts by hand, from a clone of this repository:

```
cp -R plugins/gowords/skills/go ~/.claude/skills/go
cp -R plugins/gowords/scripts ~/.claude/skills/go/scripts
```

Then edit `~/.claude/skills/go/SKILL.md`. In the command line under "Running the script", replace `"${CLAUDE_PLUGIN_ROOT}"/scripts/gowords.py` with `~/.claude/skills/go/scripts/gowords.py`. This edit is required: outside a plugin the variable is empty, and the shell would look for `/scripts/gowords.py`.

The `${user_config.*}` placeholders on the same line can stay. The script reads an unreplaced placeholder as an unset option and uses the default. To set an option, replace its placeholder with the value, for example `CLAUDE_PLUGIN_OPTION_TIMEZONE='Europe/Paris'`.

The manual copy does not install the session-start alert. To get it, add a `SessionStart` hook to `~/.claude/settings.json` that runs `python3 ~/.claude/skills/go/scripts/gowords.py hook`. Its output still names `/gowords:go` as the full list.

## The workstream file

One markdown file per workstream, in the memory directory of the project (`~/.claude/projects/<encoded path>/memory/`), or in the directory set by the `memory_dir` option:

```yaml
---
name: <slug>
description: "<one line>"
metadata:
  type: project
  go_word: 'go <word>'
  aliases: ['go <other>']        # optional
  status: 'open'                  # open | waiting | closed | stopped
  next_due: 'YYYY-MM-DD'          # or 'YYYY-MM-DD HH:MM', local time; optional
  not_before: 'YYYY-MM-DD HH:MM'  # optional; a bare date means 00:00
  waiting_on: '<person or event>' # optional; person or event awaited
  done_when: '<end criterion>'
---

One paragraph that states the goal and the next action.
```

The script also accepts the French statuses `ouvert`, `en attente`, `clos` and `arrêté`, whatever the output language. It reads a small subset of YAML: bare or quoted scalars on one line, and inline lists `[...]`. A file it cannot read is reported as a problem in the listing instead of being skipped. It also reports an unreadable date, a word claimed by two files, a missing `done_when`, and an open workstream with no due date whose file has not changed for `stale_days` days (14 by default). Two more lines flag cards that have grown: files over 20 KB and `done_when` over 250 characters, for workstreams that are not closed.

`waiting_on` names the person or event a workstream waits for, when no date is known. A workstream with `waiting_on` is never launchable, whatever `not_before` says, and the listing shows what it waits on. `list` hides closed workstreams and prints their count; `list --closed` prints the closed table. The session-start alert cuts each `done_when` to 120 characters.

A workstream is closed by setting `status: 'closed'`. Its file stays.

## Examples

Eight workstreams, taken from real use and anonymized. Two of them ship as files in [`plugins/gowords/examples/`](plugins/gowords/examples/).

| Word | Workstream | Field it shows |
|---|---|---|
| `go shadow-test` | A variant of an agent runs next to production for 5 days and its output is read every morning | `not_before` set to the time of the next day's run |
| `go contract` | A distribution contract for a series with an app: countersignature, then release | `done_when` with two conditions |
| `go listing-request` | A platform asks to be listed; one question about its rights was sent; 7 days of silence mean it is not listed | closed by the "silence" criterion |
| `go interview` | Questions sent to an interviewee, who promised answers by a given date | `not_before` set to the promised date |
| `go merger-watch` | A rumoured merger between two platforms, followed until the first official source | `done_when` with two outcomes and a window ending on 31 December |
| `go quarterly-letter` | The quarterly letter of a listed company, to be read when it comes out | `not_before` 3 months ahead |
| `go scheduled-check` | Check the result of a run scheduled on Wednesday at 12:30 | `not_before` set to Wednesday 13:00 |
| `go follow-up` | One dated reminder to a partner; no answer means the matter is dropped | `not_before` set to the reminder date |

None of these waits on code. Most of them wait on a person or on a date.

## How it differs from beads and taskmd

beads lists work with no open blockers through `bd ready`, and taskmd recommends tasks through `taskmd next`. Both work from dependencies between tasks. gowords does three other things:

- `not_before` and `waiting_on`: a workstream whose next action waits for a time, or for a person or event, leaves the "launch now" list until then.
- Waits outside code: an email reply, a scheduled run, a document published on a given date.
- Peer sessions: before recommending, the skill asks the other running Claude Code sessions which workstream they hold, and marks those words as taken.

## Options

Claude Code asks for these values when the plugin is enabled and saves them under `pluginConfigs` in your `settings.json`. Recent versions also show each option as a row in `/config`.

| Option | Default | Effect |
|---|---|---|
| `timezone` | system zone | IANA zone for dates and delays, for example `Europe/Paris` |
| `language` | `en` | Language of the script's tables and alerts: `en` or `fr` |
| `stale_days` | `14` | An open workstream with no due date is flagged after this many days without a change to its file |
| `memory_dir` | project memory directory | Directory that holds the workstream files |
| `session_alert` | `on` | `off` disables the session-start alert |
| `peers` | `ask` | `ask` lists the running sessions and waits for your yes before messaging them; `on` messages them without asking; `off` skips the step |

## Known limits

- Project paths that contain `_` or a space: the encoding of the path into the memory directory name is unverified. Set `memory_dir` to point at the directory directly.
- Without a `timezone` option, and without `TZ` or `/etc/localtime`, the script falls back to a fixed offset, which does not follow daylight saving time.
- The `language` option sets the script's tables. The language of the conversation sets Claude's prose around them.
- The peer-session step needs Claude Code 2.1.224 or later, on macOS or Linux. Elsewhere it is skipped in one line.
- Windows paths are not handled by the encoding of the project path into the memory directory name. Set `memory_dir` to point at the directory directly.
- Peer sessions in other projects are listed by `ListAgents` too. The default `ask` shows how many would be messaged and sends nothing without your yes.
- `gowords.py hook` reads stdin. Run by hand in a terminal, it waits for input.

## About the author

gowords is written by Ludovic Bostral. His own registry held 25 active and 44 closed workstreams on 26 October 2026, worked from several Claude Code sessions in parallel and from scheduled agents on a server.

- [Streaming Radar](https://www.streaming-radar.com), a French-language newsletter on the economics of streaming: 60 numbered editions as of 26 October 2026.
- [Streaming Lens](https://lens.streaming-radar.com), an MCP server of streaming-market data, listed in the claude.ai connectors directory as a Community connector since 1 October 2026.
- [verticaldrama.tv](https://verticaldrama.tv), an English-language news site on vertical drama.
- Two reports: Africa Streaming 2026 and Vertical Invasion 2026.
- Vertical What?, a 9-episode vertical series made with AI tools, live in a microdrama app since 25 October 2026.

Book a call: [www.bostral.com/call](https://www.bostral.com/call)

## License

MIT. See [LICENSE](LICENSE).
