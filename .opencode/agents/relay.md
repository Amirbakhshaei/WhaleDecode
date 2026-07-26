---
description: WhaleAgent RELAY — Telegram formatter, no new claims, strict MarkdownV2 formatting
mode: subagent
color: "#3498DB"
temperature: 0.1
permission:
  read: allow
  edit: ask
  glob: allow
  grep: allow
  list: allow
  bash: deny
  filesystem_*: allow
  git_*: allow
---

{file:../prompts/v1/agents/relay.txt}
