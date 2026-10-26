---
name: go
description: "Registry of resumable workstreams (go words) read from memory files, sorted by due date, with alerts. Triggers: \"/gowords:go\", \"go next\", \"go <word>\", \"go new <word>\", \"list my workstreams\", \"what can I launch now\", and in French \"liste les go\", \"mes mots de reprise\", \"go en cours\"."
---

# go: registry of workstreams

A go word names one workstream, for example `go scheduled-check`. Each workstream is a markdown file
with a YAML frontmatter, stored in the workstream directory. This skill lists them, recommends what
to launch now, resumes one, and creates new ones.

## Running the script

Plugin options are not in the environment of shell commands run by Claude, so every call to the
script passes them inline. Use exactly this prefix, called RUN below:

```
CLAUDE_PLUGIN_OPTION_TIMEZONE='${user_config.timezone}' CLAUDE_PLUGIN_OPTION_LANGUAGE='${user_config.language}' CLAUDE_PLUGIN_OPTION_STALE_DAYS='${user_config.stale_days}' CLAUDE_PLUGIN_OPTION_MEMORY_DIR='${user_config.memory_dir}' CLAUDE_PLUGIN_OPTION_SESSION_ALERT='${user_config.session_alert}' python3 "${CLAUDE_PLUGIN_ROOT}"/scripts/gowords.py
```

Commands: `RUN list`, `RUN list --closed`, `RUN find <word>`, `RUN where`.

Peer step option: `peers` = `${user_config.peers}`. It takes `ask`, `on` or `off`. If it shows as
an unresolved placeholder, is empty or is any other value, treat it as `ask`. The user can also say
"no peers" to skip the step.

## Listing (`/gowords:go`, "list my workstreams", "liste les go")

1. **Ask neighbouring sessions first.** If the `peers` option is `off`, or the `ListAgents` tool is
   absent, returns an error or returns no session, say so in one line and go to step 2. Otherwise
   call `ListAgents`. Sessions in other projects are unrelated to this registry, so:
   - `ask` (default): list the sessions `ListAgents` returned, say how many would be messaged, and
     send nothing until the user has said yes in this conversation. If the answer is no, skip in one
     line.
   - `on`: send without asking.

   Send each session this question with `SendMessage`, answer in 3 lines: "which workstream are you
   on, which files or resources are you changing, what are you leaving free?" Read the replies, then
   mark in the list the words already taken by a session. A session that does not answer is marked
   "no answer", never counted as free.
2. Run `RUN list`. Its closed table is omitted: the output ends the active table with a line that
   counts the closed workstreams. Run `RUN list --closed` only when the user asks for the closed ones.
3. Render its tables as they are, without rewriting them into prose, and add a "taken by" column
   from step 1. The source of truth is the frontmatter of each file: `metadata.go_word`, `aliases`,
   `status` (`open`, `waiting`, `closed`, `stopped`; French `ouvert`, `en attente`, `clos`,
   `arrêté`), `next_due`, `not_before`, `waiting_on` and `done_when`.
4. Everything is relative to the current time in the configured time zone. The script prints "Now"
   and, for a due date that is overdue or within 48 hours, the delay from that instant; beyond 48
   hours the delay column is empty, so compute it yourself from the printed date. In the rendered text, never give a bare UTC
   time: convert a time found in a file to the configured zone and add the delay from now ("at
   13:00, in 3 h 22"). An action that can already be done is written "now". The "Launchable" column
   comes from `not_before`.
5. A word that is open, has no `next_due`, and whose file has not changed for more than the
   configured number of days is flagged. The age comes from the file's modification date, not from a
   field.

## `go next`

After the tables, recommend the **3 tasks to launch now** from the active go words. This is what can
start now, not what is most important.

Write the criteria BEFORE the sorting table:

- (0) launchable now: no `not_before` in the future, no `waiting_on`, and the status is not
  `stopped` or `closed`. A workstream with `waiting_on` is never launchable now, whatever its
  `not_before`: it goes in the "later" line with what it waits on. Stopped workstreams are never candidates, although `list` still shows them in the active table. A word whose `not_before` is in the future is
  not among the 3; it goes in a "later" line with its time in the configured zone and its delay.
- (a) overdue or due within 48 h of now comes first; among due dates on the same day, the action
  that can be done earliest.
- (b) not taken by a neighbouring session (step 1 of "Listing").
- (c) on equal due dates, the task that unblocks another one, then the most reversible and cheapest
  to open.

Then:

1. A sorting table with one row per retained candidate and per rejected candidate among the 5 best,
   one column per criterion (a) (b) (c), and a verdict on every row.
2. The 3 recommended tasks, each with its first concrete action and its cost if it is paid.
3. The "later" line for words with a future `not_before` or a `waiting_on`.
4. If fewer than 3 free candidates exist, say so with the exact number instead of padding with
   invented tasks.

A paid or irreversible action is recommended, never launched.

## `go <word>`

1. Run `RUN find <word>` (the word or one of its aliases, with or without the leading "go").
   Exit code 0 prints one path; exit 1 means no match, so say so and offer `go new <word>`; exit 2
   prints several paths, so show them and ask which one.
2. Read the whole file.
3. Show its status, its `done_when`, and its next action, with dates converted as in "Listing".
4. Resume the work described in the file.

## `go new <word>`

1. Ask for the `done_when` criterion first. Do not write anything before the user has answered.
2. Find the target directory with `RUN where`. If it prints nothing or fails, ask the user where the
   workstream files live; do not guess. (The `memory_dir` option or the automatic memory directory
   of the project must exist; the directory is created only if the user asks for it.)
3. Write `<directory>/<slug>.md`, where the slug is the word in lowercase with hyphens. Never
   overwrite an existing file: if the path exists, stop and tell the user.
4. Use this frontmatter, then one paragraph of body that states the goal and the next action:

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
```

## Rules for writing a workstream file

- One word is one workstream. A merge keeps the old word in `aliases`.
- `done_when` is written at creation. "Not written" is a visible debt, not a valid value.
- Close with `status: closed`; never delete the file.
- Set `not_before` as soon as the next action waits for a time or a day (scheduled run, scheduled
  mail, measurement window, dated reminder, "tonight"), in the same format as `next_due`. A bare date
  means 00:00. No waiting means no field.
- A waiting workstream gets `not_before` when the wait has a date, and `waiting_on` (the person or
  event, in a few words) when it waits for a person or an event without a date. Clear `waiting_on`
  once the wait is over.
- Always put `next_due` in single quotes (otherwise YAML turns it into a date), as `YYYY-MM-DD`
  (due during that day) or `YYYY-MM-DD HH:MM` in local time when the action depends on a time. No
  due date means no field.
- Put `description` in double quotes as soon as it contains `: `, otherwise YAML rejects the file.
