"""Shared process-wide HTTP connection pools.

Every adapter that talks to an external HTTP API borrows its client from here
instead of constructing (and tearing down) a fresh ``httpx.AsyncClient`` per
request — connection reuse is the whole point, and it means a single
``aclose()`` at shutdown closes every pool.
"""
import httpx


class HttpClientManager:
    """Lazily-built, process-wide ``httpx.AsyncClient`` per service.

    Clients are created on first use (so importing the module has no side
    effects) and reused until ``aclose`` is called from the app lifespan.
    """

    _clients: dict[str, httpx.AsyncClient] = {}

    @classmethod
    def get_client(cls, service: str, *, timeout: float = 30.0) -> httpx.AsyncClient:
        client = cls._clients.get(service)
        if client is None:
            client = httpx.AsyncClient(timeout=timeout)
            cls._clients[service] = client
        return client

    @classmethod
    async def aclose(cls) -> None:
        for client in cls._clients.values():
            await client.aclose()
        cls._clients.clear()
