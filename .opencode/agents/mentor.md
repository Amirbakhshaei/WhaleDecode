---
description: WhaleAgent learning coach — teach by tracing code paths, running examples
mode: subagent
color: "#F39C12"
temperature: 0.5
permission:
  read: allow
  edit: ask
  glob: allow
  grep: allow
  list: allow
  bash:
    "*": ask
    "cat *": allow
    "ls *": allow
    "find *": allow
    "grep *": allow
    "pytest *": allow
  webfetch: allow
  websearch: allow
  filesystem_*: allow
  git_*: allow
  shell_*: allow
  sqlite_*: allow
---

{file:../prompts/v1/agents/mentor.txt}
