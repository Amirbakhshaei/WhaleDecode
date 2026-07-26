---
description: WhaleAgent architect — design, ADRs, interfaces, hexagonal boundaries
mode: primary
color: "#4A90D9"
temperature: 0.1
permission:
  read: allow
  edit: ask
  glob: allow
  grep: allow
  list: allow
  webfetch: allow
  websearch: allow
  bash:
    "*": deny
    "cat *": allow
    "ls *": allow
    "find *": allow
    "grep *": allow
  filesystem_*: allow
  memory_*: allow
  git_*: allow
  task:
    "*": deny
    forge: allow
    prism: allow
    quill: allow
    scout: allow
---

{file:../prompts/v1/agents/atlas.txt}
