---
description: WhaleAgent MERIDIAN — ChatInvestigationGraph concierge, user-facing investigation
mode: subagent
color: "#27AE60"
temperature: 0.3
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

{file:../prompts/v1/agents/meridian.txt}
