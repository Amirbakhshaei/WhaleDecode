class WhaleAgentError(Exception):
    """Base domain exception."""


class PlanLimitExceededError(WhaleAgentError):
    """User has reached their plan limit."""


class AlertDeduplicatedError(WhaleAgentError):
    """Duplicate alert suppressed."""


class ConfigError(WhaleAgentError):
    """Configuration error."""


class ToolError(WhaleAgentError):
    """Tool execution error."""


class ChainError(WhaleAgentError):
    """Blockchain provider error."""


class InvalidTransitionError(WhaleAgentError):
    """Invalid event state transition."""


__all__ = [
    "WhaleAgentError",
    "PlanLimitExceededError",
    "AlertDeduplicatedError",
    "ConfigError",
    "ToolError",
    "ChainError",
    "InvalidTransitionError",
]
