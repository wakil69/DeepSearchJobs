import json 

from aio_pika import Message, DeliveryMode
from typing import Optional
from worker.types.worker_types import PayloadSession
from worker.dependencies import WORKER_ID

async def send_to_dead_letter_queue(
    channel, payload: Optional[PayloadSession], session_logger
) -> None:
    """Publish a failed job to the dead-letter queue."""
    try:
        if payload is None:
            session_logger.error("Tried to send None to DLQ — skipping.")
            return
        
        routing_key = (
            "dead_letter_analyser_companies"
            if WORKER_ID == "analyser"
            else "dead_letter_checker_jobs"
        )
        
        message = Message(
            body=json.dumps(payload).encode(),
            delivery_mode=DeliveryMode.PERSISTENT,
        )
                
        await channel.default_exchange.publish(
            message,
            routing_key=routing_key,
        )

        session_logger.warning(
            f"Sent job {payload.get('company_name')} "
            f"(ID={payload.get('company_id')}) to {routing_key}"
        )

    except Exception as e:
        session_logger.error(f"Failed to publish to DLQ: {e}")