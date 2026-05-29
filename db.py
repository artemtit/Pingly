from supabase import AsyncClient, acreate_client
from config import SUPABASE_URL, SUPABASE_KEY

_client: AsyncClient | None = None


async def init_db() -> None:
    global _client
    _client = await acreate_client(SUPABASE_URL, SUPABASE_KEY)


def _db() -> AsyncClient:
    assert _client is not None, "DB not initialized"
    return _client

def client() -> AsyncClient:
    """Infrastructure entrypoint. UI layers must not call this directly."""
    return _db()
