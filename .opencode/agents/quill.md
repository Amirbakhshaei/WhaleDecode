---
description: WhaleAgent auditor — produce audit reports, risk notes, architecture compliance
mode: primary
color: "#9B59B6"
temperature: 0.1
permission:
  read: allow
  edit: deny
  glob: allow
  grep: allow
  list: allow
  bash:
    "*": ask
    "git diff*": allow
    "git log*": allow
    "git show*": allow
    "grep *": allow
  webfetch: deny
  websearch: deny
  git_*: allow
  filesystem_*: allow
  memory_*: allow
  shell_*: allow
---

{file:../prompts/v1/agents/quill.txt}
