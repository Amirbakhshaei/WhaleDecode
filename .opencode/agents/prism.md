---
description: WhaleAgent reviewer — correctness, architecture boundaries, async safety, missing tests
mode: primary
color: "#FF6B6B"
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
  shell_*: allow
  sequential-thinking_*: allow
---

{file:../prompts/v1/agents/prism.txt}
