import os
import json
import time
import logging
import pika
import psycopg
import redis
import asyncio
import signal
import threading

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Playwright, Browser
from pika.spec import BasicProperties
from pika.adapters.blocking_connection import BlockingConnection, BlockingChannel
from pika.exceptions import (
    AMQPConnectionError,
    StreamLostError,
    ConnectionClosedByBroker,
    AMQPHeartbeatTimeout,
    ConnectionClosed,
)
from typing import Any, Optional
from worker_async.message_processing import (
    process_analyser_job,
    process_checker_job,
    handle_failed_job,
    get_job_status,
)
from worker_async.logging_utils import get_job_logger
from playwright_stealth import Stealth  # type: ignore

# -------------------------------------------------------------------
# ENV + LOGGING
# -------------------------------------------------------------------
load_dotenv()
os.makedirs("./logs", exist_ok=True)

WORKER_ID = os.getenv("WORKER_ID", "unknown")
NODE_ENV = os.getenv("NODE_ENV", "unknown")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            f"./logs/worker_async_{WORKER_ID}.log", mode="a", encoding="utf-8"
        ),
        # logging.StreamHandler(),
    ],
)
logger = logging.getLogger(f"worker_async_{WORKER_ID}")

# -------------------------------------------------------------------
# ENV CONFIG
# -------------------------------------------------------------------
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
prefix = "DEV" if NODE_ENV == "development" else ""

RABBITMQ_HOST = os.getenv(
    f"RABBITMQ_HOST_{prefix}", os.getenv("RABBITMQ_HOST", "localhost")
)
REDIS_HOST = os.getenv(f"REDIS_HOST_{prefix}", os.getenv("REDIS_HOST", "localhost"))
HOST_DB = os.getenv(f"PG_HOST_{prefix}", os.getenv("PG_HOST", "localhost"))
USERNAME = os.getenv(f"PG_USER_{prefix}", os.getenv("PG_USER", "user"))
PASSWORD = os.getenv(f"PG_PASSWORD_{prefix}", os.getenv("PG_PASSWORD", "password"))
DATABASE = os.getenv(f"PG_DATABASE_{prefix}", os.getenv("PG_DATABASE", "database"))
PORT = int(os.getenv("PG_PORT", 5432))

connection_params: dict[str, Any] = {
    "dbname": DATABASE,
    "user": USERNAME,
    "password": PASSWORD,
    "host": HOST_DB,
    "port": PORT,
}

try:
    with psycopg.connect(**connection_params) as conn:
        logger.info("Database connection successful!")
except Exception as e:
    logger.error(f"Database connection failed: {e}")

redis_client = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True
)
logger.info("Connected to Redis")


# -------------------------------------------------------------------
# WORKER STATE
# -------------------------------------------------------------------
class WorkerState:
    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.shutdown_event = asyncio.Event()
        self.job_counter = 0


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
# RABBITMQ SETUP
# -------------------------------------------------------------------
def connect_to_rabbitmq() -> BlockingConnection:
    """Connect to RabbitMQ with retries."""
    while True:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=3600,
                    blocked_connection_timeout=7200,
                    socket_timeout=30,
                )
            )
            logger.info("Connected to RabbitMQ.")
            return connection
        except Exception as e:
            logger.warning(
                f"RabbitMQ connection failed ({type(e).__name__}: {e}), retrying..."
            )
            time.sleep(3)


# -------------------------------------------------------------------
# JOB HANDLERS
# -------------------------------------------------------------------
async def on_message_async(
    ch: BlockingChannel, method, properties: BasicProperties, body: bytes
):
    """Main async job handler."""
    job_data = json.loads(body)
    company_id = job_data.get("company_id")
    company_name = job_data.get("company_name")

    if not company_id or not company_name:
        logger.warning("Invalid job data.")
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    job_logger = get_job_logger(WORKER_ID, company_id, company_name)
    logger.info(f"Processing job for {company_name} ({company_id})")

    job_key = (
        f"{'company_jobs' if WORKER_ID == 'analyser' else 'check_jobs'}:{company_id}"
    )

    status_info = get_job_status(job_key, redis_client)
    retries = int(status_info.get("retries", 0))
    status = status_info.get("status", "new")

    try:

        if WORKER_ID == "analyser":
            await process_analyser_job(
                ch,
                company_id,
                company_name,
                job_logger,
                method,
                connection_params,
                redis_client,
                worker_state.browser,
                job_key,
                retries,
                status,
            )
        else:
            await process_checker_job(
                ch,
                company_id,
                company_name,
                job_logger,
                method,
                connection_params,
                redis_client,
                worker_state.browser,
                job_key,
                retries,
                status,
            )

        worker_state.job_counter += 1
        logger.info(f"Job completed for {company_name}")

    except Exception as e:
        logger.error(f"Error processing job: {e}")
        try:
            handle_failed_job(
                ch, job_key, job_data, retries, redis_client, job_logger, method
            )
        except Exception as e2:
            logger.error(f"Error handling failed job: {e2}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def on_message_sync(ch, method, properties, body):
    """Bridge sync pika to async loop."""
    try:
        if worker_state.loop:
            future = asyncio.run_coroutine_threadsafe(
                on_message_async(ch, method, properties, body),
                worker_state.loop,
            )
            future.result()
    except Exception as e:
        logger.error(f"on_message_sync error: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def consume_forever(channel: BlockingChannel):
    """Run blocking pika consumer in a separate thread."""
    try:
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Consumer thread stopped: {e}")


# -------------------------------------------------------------------
# BROWSER UTILITIES
# -------------------------------------------------------------------
async def _launch_stealth_browser(p: Playwright) -> Browser:
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

async def restart_stealth_browser(playwright_instance: Optional[Playwright] = None) -> Browser:
    """
    Restart a stealth-enabled Playwright browser.
    Reuses existing playwright instance if available.
    """
    stealth = Stealth()

    if playwright_instance is None:
        async with stealth.use_async(async_playwright()) as p:
            browser = await _launch_stealth_browser(p)
        return browser
    else:
        browser = await _launch_stealth_browser(playwright_instance)
        return browser

# -------------------------------------------------------------------
# MAIN LOOP
# -------------------------------------------------------------------
async def run_rabbitmq_loop(browser: Browser, rotate_every_jobs=5):
    """Main job consumption loop."""
    worker_state.browser = browser
    worker_state.loop = asyncio.get_running_loop()
    jobs_since_rotation = 0

    while not worker_state.shutdown_event.is_set():
        connection = None
        channel = None
        consumer_thread = None

        try:
            connection = connect_to_rabbitmq()
            channel = connection.channel()

            queue = "company_jobs" if WORKER_ID == "analyser" else "check_jobs"
            dead_queue = (
                "dead_letter_analyser_companies"
                if WORKER_ID == "analyser"
                else "dead_letter_checker_jobs"
            )

            channel.queue_declare(queue=queue, durable=True)
            channel.queue_declare(queue=dead_queue, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(
                queue=queue, on_message_callback=on_message_sync, auto_ack=False
            )

            logger.info(f"Waiting for jobs on queue '{queue}'... (Ctrl+C to stop)")

            consumer_thread = threading.Thread(
                target=consume_forever, args=(channel,), daemon=True
            )
            consumer_thread.start()

            while (
                consumer_thread.is_alive() and not worker_state.shutdown_event.is_set()
            ):
                await asyncio.sleep(1)

                jobs_since_rotation = worker_state.job_counter

                if jobs_since_rotation >= rotate_every_jobs:
                    logger.warning(f"Rotating stealth browser - jobs: {jobs_since_rotation}")

                    try:
                        await worker_state.browser.close()
                    except Exception as e:
                        logger.error(f"Error closing old browser: {e}")

                    worker_state.browser = await restart_stealth_browser(
                        worker_state.playwright
                    )
                    worker_state.job_counter = 0
                    logger.info("Stealth browser restarted successfully.")

        except Exception as e:
            logger.warning(f"⚠️ RabbitMQ loop error: {e}")
            await asyncio.sleep(5)

        finally:
            if channel and channel.is_open:
                try:
                    channel.stop_consuming()
                    channel.close()
                except Exception:
                    pass
            if connection and connection.is_open:
                connection.close()
            if consumer_thread and consumer_thread.is_alive():
                consumer_thread.join(timeout=2)


# -------------------------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------------------------
async def main():
    """Global async entrypoint: launch stealth-enabled browser once."""
    async with Stealth().use_async(async_playwright()) as p:
        worker_state.playwright = p
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

        logger.info("Stealth browser launched and ready.")
        await run_rabbitmq_loop(browser)

        logger.info("Shutting down browser and Playwright...")
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    try:
        logger.info(f"Starting worker '{WORKER_ID}'...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user.")
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
