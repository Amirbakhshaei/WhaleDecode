---
description: WhaleAgent SENTINEL — deterministic detection, rules-based event scoring, zero LLM
mode: subagent
color: "#E74C3C"
temperature: 0.0
permission:
  read: allow
  edit: deny
  glob: allow
  grep: allow
  list: allow
  bash: deny
  filesystem_*: allow
  git_*: allow
---

{file:../prompts/v1/agents/sentinel.txt}
