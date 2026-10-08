"""Behaviour test for the health feature."""

import asyncio

import httpx

from app.app import app


async def fetch_health() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


def test_health_answers_ok() -> None:
    response = asyncio.run(fetch_health())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
