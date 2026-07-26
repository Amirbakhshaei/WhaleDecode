---
description: WhaleAgent LEDGER — BriefingGraph editor, daily briefing generation
mode: subagent
color: "#8E44AD"
temperature: 0.3
permission:
  read: allow
  edit: ask
  glob: allow
  grep: allow
  list: allow
  bash: deny
  filesystem_*: allow
  git_*: allow
  memory_*: allow
  sequential-thinking_*: allow
---

{file:../prompts/v1/agents/ledger.txt}
