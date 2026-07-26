---
description: WhaleAgent ORION — EventInvestigationGraph investigator, smart-money event analysis
mode: subagent
color: "#2E86C1"
temperature: 0.2
permission:
  read: allow
  edit: deny
  glob: allow
  grep: allow
  list: allow
  bash: deny
  filesystem_*: allow
  git_*: allow
  memory_*: allow
  sequential-thinking_*: allow
---

{file:../prompts/v1/agents/orion.txt}
