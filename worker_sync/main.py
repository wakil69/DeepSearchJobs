import os
import json
import time
import logging
import pika
import psycopg
import redis

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Playwright, Browser
from pika.exceptions import (
    AMQPConnectionError,
    StreamLostError,
    ConnectionClosedByBroker,
    AMQPHeartbeatTimeout,
    ConnectionClosed,
)
from pika.spec import BasicProperties
from typing import Any, Optional
from worker_sync.message_processing import (
    process_analyser_job,
    process_checker_job,
    handle_failed_job,
    get_job_status
)
from pika.adapters.blocking_connection import BlockingConnection, BlockingChannel
from functools import partial
from worker_sync.logging_utils import get_job_logger 

load_dotenv()

# -------------------------------------------------------------------
# LOGGING SETUP
# -------------------------------------------------------------------
os.makedirs("./logs", exist_ok=True)

WORKER_ID = os.getenv("WORKER_ID", "unknown")
NODE_ENV = os.getenv("NODE_ENV", "unknown")

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
# ENVIRONMENT SETUP
# -------------------------------------------------------------------

prefix = "DEV" if NODE_ENV == "development" else ""
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
RABBITMQ_HOST = os.getenv(f"RABBITMQ_HOST_{prefix}", os.getenv("RABBITMQ_HOST", "localhost"))
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


# -------------------------------------------------------------------
# DB CONNECTION TEST
# -------------------------------------------------------------------

try:
    with psycopg.connect(**connection_params) as conn:
        logger.info("Database connection successful!")
except Exception as e:
    logger.error(f"Database connection failed: {e}")

# -------------------------------------------------------------------
# REDIS CLIENT
# -------------------------------------------------------------------
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True,
)

logger.info("Connected to Redis")

# -------------------------------------------------------------------
# GLOBAL STATE
# -------------------------------------------------------------------
playwright: Optional[Playwright] = None
browser: Optional[Browser] = None
job_counter: int = 0
RESTART_BROWSER_EVERY: int = 5


def start_browser_playwright() -> None:
    """Start or restart a Playwright Chromium browser."""
    global browser, playwright

    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass

    if playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass

    playwright = sync_playwright().start() 
    browser = playwright.chromium.launch( 
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
    logger.info("Started new Playwright browser instance.")

def connect_to_rabbitmq() -> BlockingConnection:
    """Continuously try to connect to RabbitMQ with stable, long-running settings."""
    retry_delay: int = 2  # seconds

    while True:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=3600,  # 1 hour heartbeat
                    blocked_connection_timeout=7200,  # 2 hours max block
                    socket_timeout=30,
                )
            )
            logger.info("Connected to RabbitMQ.")
            return connection
        except Exception as e:
            logger.warning(
                f"RabbitMQ connection failed ({type(e).__name__}: {e}), retrying in {retry_delay}s..."
            )
            time.sleep(retry_delay)

def send_heartbeat_periodically(ch, interval=300) -> None:
    """Send a RabbitMQ heartbeat every few minutes to keep connection alive."""
    try:
        ch.connection.process_data_events()
    except Exception as e:
        logger.warning(f"Heartbeat failed ({type(e).__name__}): {e}")

def on_message(ch: BlockingChannel, method, properties: BasicProperties, body: bytes):
    """Main message handler for both workers."""
    global job_counter

    job_data = json.loads(body)
    company_id = job_data.get("company_id")
    company_name = job_data.get("company_name")

    if not company_id or not company_name:
        logger.warning("Invalid job data (missing company_id or company_name).")
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    
    job_logger = get_job_logger(WORKER_ID, company_id, company_name)

    if WORKER_ID == "analyser":
        job_key = f"company_jobs:{company_id}"
        status_info = get_job_status(job_key, redis_client)
        retries = int(status_info.get("retries", 0))
        status = status_info.get("status", "new")

        try:
            process_analyser_job(ch, company_id, company_name, job_logger, method, connection_params, redis_client, browser, job_key, retries, status)

            # Restart browser every N jobs
            job_counter += 1
            if job_counter >= RESTART_BROWSER_EVERY:
                logger.info(f"Restarting browser after {job_counter} jobs...")
                start_browser_playwright()
                job_counter = 0

        except Exception as e:
            logger.error(f"Error processing job: {e}")
            handle_failed_job(ch, job_key, job_data, retries, redis_client, job_logger, method)
    
    elif WORKER_ID == "checker":
        job_key = f"check_jobs:{company_id}"
        status_info = get_job_status(job_key, redis_client)
        retries = int(status_info.get("retries", 0))
        status = status_info.get("status", "new")
        
        try:
            
            process_checker_job(ch, company_id, company_name, job_logger, method, connection_params, redis_client, browser, job_key, retries, status)

            # Restart browser every N jobs
            job_counter += 1
            if job_counter >= RESTART_BROWSER_EVERY:
                logger.info(f"Restarting browser after {job_counter} jobs...")
                start_browser_playwright()
                job_counter = 0

        except Exception as e:
            logger.error(f"Error processing job: {e}")
            handle_failed_job(ch, job_key, job_data, retries, redis_client, job_logger, method)

        else:
            logger.warning(f"Unknown WORKER_ID: {WORKER_ID}")
            ch.basic_ack(delivery_tag=method.delivery_tag)

def main() -> None:
    global browser, playwright, job_counter

    time.sleep(10)

    logger.info("Starting Job Worker...")

    start_browser_playwright()

    while True:
        connection = None
        channel = None

        try:
            connection = connect_to_rabbitmq()
            channel = connection.channel()
            if WORKER_ID == "analyser":
                channel.queue_declare(queue="company_jobs", durable=True)
                channel.queue_declare(queue="dead_letter_analyser_companies", durable=True)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue="company_jobs", on_message_callback=partial(on_message))

            if WORKER_ID == "checker":
                channel.queue_declare(queue="check_jobs", durable=True)
                channel.queue_declare(queue="dead_letter_checker_jobs", durable=True)
                channel.basic_qos(prefetch_count=1)
                channel.basic_consume(queue="check_jobs", on_message_callback=partial(on_message))

            logger.info("Waiting for jobs...")
            channel.start_consuming()

        except (
            AMQPConnectionError,
            StreamLostError,
            ConnectionClosedByBroker,
            AMQPHeartbeatTimeout,
            ConnectionClosed,
            OSError,
        ) as e:
            logger.warning(
                f"RabbitMQ connection error ({type(e).__name__}): {e}. Reconnecting in 5s..."
            )

        except KeyboardInterrupt:
            logger.info("Worker stopped by user.")
            break

        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")

        finally:
            try:
                if channel and channel.is_open:
                    channel.close()
            except Exception:
                pass

            try:
                if connection and connection.is_open:
                    connection.close()
            except Exception:
                pass

            # logger.info("RabbitMQ cleanup completed, reconnecting in 5s...")
            # time.sleep(5)
            break

    # Cleanup Playwright
    logger.info("Shutting down browser and Playwright...")
    try:
        if browser:
            browser.close()
    except Exception:
        pass
    try:
        if playwright:
            playwright.stop()
    except Exception:
        pass


if __name__ == "__main__":
    main()