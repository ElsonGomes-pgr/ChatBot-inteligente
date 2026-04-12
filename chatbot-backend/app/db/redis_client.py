import json
import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()

_redis_pool: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_pool


class SessionCache:
    """Cache de sessão de conversa no Redis."""

    def __init__(self, client: redis.Redis):
        self.client = client
        self.ttl = settings.session_ttl_seconds

    def _key(self, conversation_id: str) -> str:
        return f"session:{conversation_id}"

    async def get(self, conversation_id: str) -> dict | None:
        raw = await self.client.get(self._key(conversation_id))
        if raw:
            return json.loads(raw)
        return None

    async def set(self, conversation_id: str, data: dict) -> None:
        await self.client.set(
            self._key(conversation_id),
            json.dumps(data),
            ex=self.ttl,
        )

    async def update(self, conversation_id: str, updates: dict) -> None:
        current = await self.get(conversation_id)
        if current:
            current.update(updates)
            await self.set(conversation_id, current)

    async def set_human_mode(self, conversation_id: str, agent_id: str) -> None:
        await self.update(conversation_id, {
            "human_mode": True,
            "assigned_agent_id": agent_id,
        })

    async def delete(self, conversation_id: str) -> None:
        await self.client.delete(self._key(conversation_id))
