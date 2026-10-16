"""Unit test for the HTTP health check endpoint used by Render Web Services."""

import asyncio
import aiohttp
import pytest
from bot import start_http_server


def test_health_server_endpoints():
    async def _test():
        port = 18088
        runner = await start_http_server(host="127.0.0.1", port=port)

        try:
            async with aiohttp.ClientSession() as session:
                # Test root endpoint
                async with session.get(f"http://127.0.0.1:{port}/") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["status"] == "ok"
                    assert "arab_tili" in data["service"]

                # Test /health endpoint
                async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["status"] == "ok"
        finally:
            await runner.cleanup()

    asyncio.run(_test())
