"""Verify seed wallet addresses have on-chain activity before DB ingestion.

Run manually:  python -m whaledecode.scripts.verify_seed
Or via CLI:   whaledecode verify-seed
Optional:     whaledecode sync-webhook --webhook-id wh_xxx --verified-file wallets_verified.json
"""
import json
import logging
from pathlib import Path

from web3 import Web3
from web3.exceptions import Web3Exception
from whaledecode.config.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def verify_on_chain_activity(wallets: list[dict], rpc_urls: dict[str, str]) -> list[dict]:
    """Filter wallets to only those with non-zero transaction count on-chain."""
    w3_clients = {
        chain: Web3(Web3.HTTPProvider(url))
        for chain, url in rpc_urls.items()
        if url
    }

    valid = []
    for w in wallets:
        chain = w.get("chain", "").upper()
        address = w.get("address", "")
        w3 = w3_clients.get(chain)

        if not w3 or not w3.is_connected():
            logger.error(f"Cannot connect to {chain} RPC. Skipping {address}.")
            continue

        try:
            chk_address = Web3.to_checksum_address(address)
            nonce = w3.eth.get_transaction_count(chk_address)
            if nonce > 0:
                logger.info(f"[VALID] {chain} | {address} | Nonce: {nonce}")
                valid.append(w)
            else:
                logger.warning(f"[DEAD] {chain} | {address} | Zero transactions found.")
        except Web3Exception as e:
            logger.error(f"RPC Error for {address} on {chain}: {e}")

    return valid


def load_verified_addresses(path: Path) -> list[str]:
    with open(path) as f:
        wallets = json.load(f)
    return [w["address"] for w in wallets]


def main() -> int:
    settings = Settings()

    rpc_urls = {
        "ETH": settings.ETH_RPC_URL or "",
        "BASE": settings.BASE_RPC_URL or "",
        "ARB": settings.ARB_RPC_URL or "",
    }

    seed_path = Path("data/wallets_seed.json")
    if not seed_path.exists():
        logger.error(f"Seed file {seed_path} not found.")
        return 1

    with open(seed_path) as f:
        wallets = json.load(f)

    logger.info(f"Loaded {len(wallets)} addresses from {seed_path}")
    verified = verify_on_chain_activity(wallets, rpc_urls)
    logger.info(f"Retained {len(verified)} active addresses. Pruned {len(wallets) - len(verified)} dead links.")

    out_path = Path("wallets_verified.json")
    with open(out_path, "w") as f:
        json.dump(verified, f, indent=2)
    logger.info(f"Verified list written to {out_path}")
    return 0


async def sync_webhook(webhook_id: str, verified_file: Path) -> int:
    """Sync verified addresses to an Alchemy webhook."""
    settings = Settings()
    auth_token = settings.ALCHEMY_AUTH_TOKEN
    if not auth_token:
        logger.error("ALCHEMY_AUTH_TOKEN not set in env.")
        return 1

    from whaledecode.adapters.alchemy.webhook_manager import AlchemyWebhookManager

    addresses = load_verified_addresses(verified_file)
    mgr = AlchemyWebhookManager(auth_token)
    await mgr.sync_webhook_addresses(webhook_id, addresses)
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sync-webhook":
        import asyncio
        if len(sys.argv) != 4:
            print("Usage: python -m whaledecode.scripts.verify_seed sync-webhook <webhook_id> <verified_file>")
            sys.exit(1)
        exit(asyncio.run(sync_webhook(sys.argv[2], Path(sys.argv[3]))))
    exit(main())

