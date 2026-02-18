import os
import json
import time
import logging
import aio_pika
import asyncio
import signal

from playwright.async_api import async_playwright, Playwright, Browser
from aio_pika.abc import AbstractIncomingMessage
from typing import Optional
from worker.types.worker_types import PayloadSession
from worker.session_processing import (
    process_analyser_job,
    process_checker_job,
)
from utils.redis_commands import get_session_status
from worker.utils.logging_utils import get_session_logger
from playwright_stealth import Stealth  # type: ignore
from dependencies import (
    init_postgres_pool,
    close_postgres_pool,
    WORKER_ID,
    RABBITMQ_URL,
)

# -------------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------------
os.makedirs("./logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            f"./logs/worker_{WORKER_ID}.log", mode="a", encoding="utf-8"
        ),
        # logging.StreamHandler(),
    ],
)

logger = logging.getLogger(f"worker_{WORKER_ID}")

# -------------------------------------------------------------------
# WORKER STATE
# -------------------------------------------------------------------
class WorkerState:
    def __init__(self) -> None:
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.shutdown_event = asyncio.Event()
        self.sessions_running: int = 0
        self.sessions_lock = asyncio.Lock()
        self.browser_lock = asyncio.Lock()

worker_state = WorkerState()


# -------------------------------------------------------------------
# SIGNAL HANDLING
# -------------------------------------------------------------------
def handle_shutdown_signal(signum, frame):
    logger.info(f"Received signal {signum}, initiating shutdown...")
    if worker_state.loop:
        worker_state.loop.call_soon_threadsafe(worker_state.shutdown_event.set)

signal.signal(signal.SIGINT, handle_shutdown_signal)
signal.signal(signal.SIGTERM, handle_shutdown_signal)

# -------------------------------------------------------------------
# BROWSER with STEALTH
# -------------------------------------------------------------------
async def launch_stealth_browser(p: Playwright) -> Browser:
    """Helper to launch Chromium with stealth args."""
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote",
            "--no-first-run",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    return browser

async def restart_stealth_browser(
    playwright_instance: Optional[Playwright] = None,
) -> Browser:
    """
    Restart a stealth-enabled Playwright browser.
    Reuses existing playwright instance if available.
    """
    stealth = Stealth()

    if playwright_instance is None:
        async with stealth.use_async(async_playwright()) as p:
            browser = await launch_stealth_browser(p)
        return browser
    else:
        browser = await launch_stealth_browser(playwright_instance)
        return browser

async def ensure_browser():
    async with worker_state.browser_lock:
        if not worker_state.browser or not worker_state.browser.is_connected():
            logger.warning("Browser not connected — restarting")
            if worker_state.playwright:
                worker_state.browser = await launch_stealth_browser(
                    worker_state.playwright
                )
                
# -------------------------------------------------------------------
# RABBITMQ
# -------------------------------------------------------------------
async def connect_rabbitmq():
    return await aio_pika.connect_robust(RABBITMQ_URL)

async def handle_message(message: AbstractIncomingMessage):
    async with message.process(requeue=False):
        
        async with worker_state.sessions_lock:
            worker_state.sessions_running += 1

        try:
            
            channel = message.channel
            payload: PayloadSession = json.loads(message.body)
            company_id = payload["company_id"]
            company_name = payload["company_name"]

            logger.info(f"Received session, company ID: {company_id}")

            await ensure_browser()

            session_logger = get_session_logger(WORKER_ID, company_id, company_name)
            logger.info(f"Processing job for {company_name} ({company_id})")

            session_key = f"{'company_jobs' if WORKER_ID == 'analyser' else 'check_jobs'}:{company_id}"
            status_info = await get_session_status(session_key)
            retries = int(status_info.get("retries", 0))
            status = status_info.get("status", "new")

            if WORKER_ID == "analyser":
                
                await process_analyser_job(
                    company_id,
                    company_name,
                    session_logger,
                    worker_state.browser,
                    session_key,
                    retries,
                    status,
                    channel
                )
            
            else:
                
                await process_checker_job(
                    company_id,
                    company_name,
                    session_logger,
                    worker_state.browser,
                    session_key,
                    retries,
                    status,
                    channel
                )

            logger.info(f"Job completed for company ID: {company_id}")
                    
        finally:

            async with worker_state.sessions_lock:
                worker_state.sessions_running -= 1
                should_rotate = worker_state.sessions_running == 0

            if should_rotate:

                async with worker_state.sessions_lock:
                    if worker_state.sessions_running != 0:
                        return

                logger.info("No active sessions — rotating browser")

                async with worker_state.browser_lock:
                    try:
                        if worker_state.browser:
                            await worker_state.browser.close()
                    except Exception:
                        logger.warning("Failed to close browser cleanly")

                    if worker_state.playwright:
                        worker_state.browser = await launch_stealth_browser(
                            worker_state.playwright
                        )
                                    
async def consume_messages():
    connection = await connect_rabbitmq()
    channel = await connection.channel()

    # Increase here for parallel sessions
    await channel.set_qos(prefetch_count=1)

    queue_name = "company_jobs" if WORKER_ID == "analyser" else "check_jobs"
    queue = await channel.declare_queue(queue_name, durable=True)

    logger.info("Waiting for crawl jobs...")
    await queue.consume(handle_message)
    
    await worker_state.shutdown_event.wait()

    await connection.close()
                        
# -------------------------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------------------------
async def main():
    """Global async entrypoint: launch stealth-enabled browser once."""

    await init_postgres_pool()
    logger.info("PostgreSQL pool ready")

    async with Stealth().use_async(async_playwright()) as p:
        worker_state.playwright = p
        worker_state.browser = await launch_stealth_browser(p)
        worker_state.loop = asyncio.get_running_loop()
        
        try:
            await consume_messages()
            
        except asyncio.CancelledError:
            
            logger.info("Worker cancelled")
        
        finally:
                        
            if worker_state.browser:
            
                await worker_state.browser.close()
            
            await close_postgres_pool()
            
            await p.stop()

        logger.info("Worker shutdown complete")
        
if __name__ == "__main__":
    try:
        logger.info(f"Starting worker '{WORKER_ID}'...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user.")
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
