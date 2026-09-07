"""Deactivate CEX hot wallets and bridge SpokePools so they're excluded from polling.

Marks the three infrastructure contracts (Binance 14, Across Base SpokePool,
Across ARB SpokePool) as ``is_exchange=True`` so CuratedWalletRepository.list_active
filters them out of eth_getLogs polling, while keeping them visible to the
funding-trace / LLM as origin labels. Also deactivates any tracked_wallets
rows pointing at those addresses so user-facing trackers never subscribe to a
contract firehose.

Revision ID: 0015_purge_cex_bridge_addresses
Revises: 0014_add_is_exchange
Create Date: 2026-09-07
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


# ponytail: lower-cased so a one-time LOWER() in the SQL matches mixed-case rows
# that the upstream syncer inserted verbatim. Addresses the user asked to be
# removed from polling entirely.
_FUNDING_ONLY_ADDRESSES_LC = (
    "0x28c6c06298d514db089934071355e5743bf21d60",  # Binance Hot 14
    "0x09aea4b2242abc8bb4bb78d537a67a245a7bec64",  # Across Base SpokePool
    "0xe35e9842fceaca96570b734083f4a58e8f7c5f2a",  # Across ARB SpokePool
    "0xce16f69375520ab01377ce7b88f5ba8c48f8d666",  # Axelar Gateway
    "0xf326e4de8f66a0bdc0970b79e0924e33c79f1915",  # MetaMask Fee Collector
)


def upgrade() -> None:
    addr_list = ",".join(f"'{a}'" for a in _FUNDING_ONLY_ADDRESSES_LC)

    # Mark contracts as is_exchange=True so list_active() skips polling.
    op.execute(
        f"""
        UPDATE curated_wallets
        SET is_exchange = TRUE
        WHERE LOWER(address) IN ({addr_list})
        """
    )

    # Deactivate any per-user tracker rows pointing at these addresses.
    op.execute(
        f"""
        UPDATE tracked_wallets
        SET is_active = FALSE
        WHERE LOWER(
            (SELECT address FROM curated_wallets WHERE curated_wallets.id = tracked_wallets.wallet_id)
        ) IN ({addr_list})
        """
    )


def downgrade() -> None:
    addr_list = ",".join(f"'{a}'" for a in _FUNDING_ONLY_ADDRESSES_LC)
    op.execute(
        f"""
        UPDATE tracked_wallets
        SET is_active = TRUE
        WHERE LOWER(
            (SELECT address FROM curated_wallets WHERE curated_wallets.id = tracked_wallets.wallet_id)
        ) IN ({addr_list})
        """
    )
    op.execute(
        f"""
        UPDATE curated_wallets
        SET is_exchange = FALSE
        WHERE LOWER(address) IN ({addr_list})
        """
    )
