class WhaleDecodeError(Exception):
    """Base exception for WhaleDecode domain errors."""


class PlanLimitError(WhaleDecodeError):
    """User has exceeded their plan limit for this action."""


class AlertSuppressedError(WhaleDecodeError):
    """Alert was suppressed due to user preference or policy."""


class InvalidChainError(WhaleDecodeError):
    """Chain identifier is not supported."""


class DuplicateEventError(WhaleDecodeError):
    """Event already exists (dedupe_key collision)."""


class WalletNotFoundError(WhaleDecodeError):
    """Wallet not found in curated or tracked set."""


class AdminOnlyError(WhaleDecodeError):
    """Action requires admin privileges."""


class LLMError(WhaleDecodeError):
    """LLM call failed or returned invalid output."""


class ChainProviderError(WhaleDecodeError):
    """Chain RPC call failed after retries."""
