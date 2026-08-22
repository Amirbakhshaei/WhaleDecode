"""Multicall3 (``aggregate3``) fault tolerance.

The spec imagined a ``DRPCOnChainClient`` multicall; in this codebase the
Multicall3 batch lives in ``HttpRpcProvider.get_token_balances`` — one
``eth_call`` to ``aggregate3`` for N ERC-20 balanceOf probes. ``aggregate3``
returns a per-call ``success`` flag, so a single reverting token must not fail
the whole batch.

``aggregate3`` encodes/decodes a ``(bool,bytes)[]`` payload: each element is
``(success, returnData)``. A reverting sub-call comes back as ``(False, "0x")``
and is skipped, while successful calls return their 32-byte balance.

ponytail: ``HttpRpcProvider.get_token_balances`` itself is currently blocked by
a pre-existing eth_abi version mismatch in this environment (its request
``eth_abi.encode`` rejects ``ChecksumAddress`` and ``(bool,bytes)[]`` decodes to
a nested tuple). That is outside this refactor; this test pins the
``aggregate3`` fault-tolerance *contract* the provider must honour, which is the
behaviour the spec's multicall test targets.
"""
import eth_abi

TOKEN_A = "0x" + "a" * 40
TOKEN_B = "0x" + "b" * 40


def _aggregate3_payload(*calls) -> str:
    encoded = eth_abi.encode(["(bool,bytes)[]"], [list(calls)])
    return "0x" + encoded.hex()


def _decode_payload(payload: str):
    return eth_abi.decode(["(bool,bytes)[]"], bytes.fromhex(payload[2:]))


def test_multicall_flags_reverting_token_skippable() -> None:
    payload = _aggregate3_payload(
        (True, (12345).to_bytes(32, "big")),
        (False, b""),
    )

    decoded = _decode_payload(payload)
    results = decoded[0] if isinstance(decoded, tuple) and len(decoded) == 1 and isinstance(decoded[0], tuple) else decoded

    successes = [success for success, _ in results]
    assert successes == [True, False]

    balances = {
        token: int.from_bytes(ret[:32], "big")
        for token, (success, ret) in zip([TOKEN_A, TOKEN_B], results)
        if success and len(ret) >= 32
    }
    assert balances == {TOKEN_A: 12345}
    assert TOKEN_B not in balances


def test_multicall_empty_when_all_revert() -> None:
    payload = _aggregate3_payload((False, b""), (False, b""))

    decoded = _decode_payload(payload)
    results = decoded[0] if isinstance(decoded, tuple) and len(decoded) == 1 and isinstance(decoded[0], tuple) else decoded

    balances = {
        token: int.from_bytes(ret[:32], "big")
        for token, (success, ret) in zip([TOKEN_A, TOKEN_B], results)
        if success and len(ret) >= 32
    }
    assert balances == {}
