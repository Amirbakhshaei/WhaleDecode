---
description: WhaleAgent research agent — verify library APIs, version constraints, recommended patterns
mode: subagent
color: "#1ABC9C"
temperature: 0.2
permission:
  read: allow
  edit: deny
  glob: allow
  grep: allow
  list: allow
  bash:
    "*": ask
    "cat *": allow
    "ls *": allow
    "pip *": allow
    "npm *": allow
  webfetch: allow
  websearch: allow
  filesystem_*: allow
  shell_*: allow
  git_*: allow
---

{file:../prompts/v1/agents/scout.txt}
