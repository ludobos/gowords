---
name: go-scheduled-check
description: "Check the result of a scheduled run on Wednesday after it has finished"
metadata:
  type: project
  go_word: 'go scheduled-check'
  status: 'waiting'
  next_due: '2026-10-28 18:00'
  not_before: '2026-10-28 13:00'
  done_when: 'The Wednesday run has been read, and its result is either accepted or logged as a defect'
---

A scheduled job runs on Wednesday at 12:30. Its output is empty before then, so
looking earlier produces nothing. `not_before` is set to 13:00, which keeps the
word out of the "launch now" picks until the run has finished.

Next action: open the run's output, compare it with the previous run, and close
this workstream with `status: 'closed'`.
