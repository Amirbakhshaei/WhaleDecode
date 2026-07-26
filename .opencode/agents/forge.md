---
description: WhaleAgent implementer — build vertical slices, code + tests + migrations
mode: primary
color: "#50C878"
temperature: 0.3
permission:
  read: allow
  edit: allow
  glob: allow
  grep: allow
  list: allow
  bash: allow
  webfetch: allow
  websearch: allow
  filesystem_*: allow
  git_*: allow
  shell_*: allow
  fetch_*: allow
  sequential-thinking_*: allow
  memory_*: allow
  sqlite_*: allow
  postgres_*: allow
  task:
    "*": deny
    atlas: allow
    prism: allow
    quill: allow
    scout: allow
    mentor: allow
---

{file:../prompts/v1/agents/forge.txt}
