---
description: WhaleAgent AEGIS — guardrail/trust policy stage, overrides all user-facing output
mode: subagent
color: "#E67E22"
temperature: 0.0
permission:
  read: allow
  edit: allow
  glob: allow
  grep: allow
  list: allow
  bash: deny
  filesystem_*: allow
  git_*: allow
  memory_*: allow
---

{file:../prompts/v1/agents/aegis.txt}
