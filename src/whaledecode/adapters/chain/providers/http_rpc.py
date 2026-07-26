import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class HttpRpcProvider:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30) -> None:
        self._url = f"{base_url}/{api_key}" if api_key and "/" not in base_url[-3:] else base_url
        self._client = httpx.AsyncClient(timeout=timeout)
        self._timeout = timeout

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=10))
    async def rpc_call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": int(time.time())}
        resp = await self._client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ValueError(f"RPC error: {data['error']}")
        return data.get("result")

    async def close(self) -> None:
        await self._client.aclose()
