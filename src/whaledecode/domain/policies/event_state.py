"""Event state machine — arch §4.3."""

VALID_TRANSITIONS = {
    "NEW": {"SCORING"},
    "SCORING": {"AGENT_QUEUED", "DROPPED"},
    "AGENT_QUEUED": {"AGENT_RUNNING", "FAILED"},
    "AGENT_RUNNING": {"ALERT_CREATED", "FAILED"},
    "ALERT_CREATED": {"PENDING_DISPATCH"},
    "PENDING_DISPATCH": {"SENT", "FAILED", "SUPPRESSED"},
    "SENT": set(),
    "SUPPRESSED": set(),
    "FAILED": {"PENDING_DISPATCH"},
    "DROPPED": set(),
}


def transition(current: str, target: str) -> str:
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition: {current} -> {target}")
    return target
