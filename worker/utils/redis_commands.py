from typing import cast
from worker.dependencies import redis_client
from worker.types.worker_types import SessionStatus

async def get_session_status(session_key: str) -> SessionStatus:
    """Retrieve session status and retry count from Redis."""
    session_status = cast(SessionStatus, await redis_client.hgetall(session_key))

    return {
        "status": session_status.get("status", "new"),
        "retries": int(session_status.get("retries", 0)),
    }


async def mark_session_status(session_key: str, status: str, retries: int = 0) -> None:
    """Update session status in Redis."""
    await redis_client.hset(session_key, mapping={"status": status, "retries": retries})
