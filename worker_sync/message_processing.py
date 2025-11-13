import psycopg
import os
import json

from typing import Any, Optional, cast
from worker_sync.worker_types import CompanyRecord, JobData, JobStatus, JobListingsResult
from dotenv import load_dotenv
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import BasicProperties
from worker_sync.core.jobs_scraper import EmailJobsScraper
from worker_sync.core.job_listings_scraper import FetchJobsListingsScraper
from worker_sync.core.website_scraper import WebsiteScraper

load_dotenv()

WORKER_ID = os.getenv("WORKER_ID", "unknown")

def fetch_company_from_db(
    company_id: int, connection_params: dict[str, Any], job_logger
) -> Optional[CompanyRecord]:
    """Fetch full company info from the database based on company_id."""
    try:
        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT website, internal_job_listing_pages, external_job_listing_pages, emails, containers_html
                    FROM companies
                    WHERE id = %s
                    """,
                    (company_id,),
                )

                row = cur.fetchone()

                if not row:
                    job_logger.warning(f"Company ID {company_id} not found.")
                    return None

                (
                    website,
                    internal_job_listing_pages,
                    external_job_listing_pages,
                    emails,
                    containers_html,
                ) = row

                return {
                    "website": website,
                    "internal_job_listing_pages": internal_job_listing_pages or [],
                    "external_job_listing_pages": external_job_listing_pages or [],
                    "emails": set(emails) if emails else set(),
                    "containers_html": (
                        {k: set(v) for k, v in containers_html.items()}
                        if containers_html
                        else {}
                    ),
                }

    except Exception as e:
        job_logger.error(f"Error fetching company {company_id}: {e}")
        return None


def get_job_status(job_key: str, redis_client) -> JobStatus:
    """Retrieve job status and retry count from Redis."""
    job_status = cast(JobStatus, redis_client.hgetall(job_key))

    return {
        "status": job_status.get("status", "new"),
        "retries": int(job_status.get("retries", 0)),
    }


def mark_job_status(
    job_key: str, status: str, redis_client, retries: int = 0
) -> None:
    """Update job status in Redis."""
    redis_client.hset(job_key, mapping={"status": status, "retries": retries})


def handle_failed_job(
    ch, job_key: str, job_data: JobData, retries: int, redis_client, job_logger, method
) -> bool:
    """
    Handle a failed job: increment retries or send to DLQ.
    Returns True if job was sent to DLQ.
    """
    retries += 1
    redis_client.hset(job_key, "retries", retries)
    if retries < 2:
        redis_client.hset(job_key, "status", "failed")
        job_logger.warning(f"{job_key} failed once — requeuing.")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        return False
    else:
        redis_client.hset(job_key, "status", "failed")
        job_logger.warning(f"{job_key} failed twice — sending to DLQ.")
        send_to_dead_letter_queue(ch, job_data, job_logger)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return True


def send_to_dead_letter_queue(
    ch: BlockingChannel, job_data: Optional[JobData], job_logger
) -> None:
    """Publish a failed job to the dead-letter queue."""
    try:
        if job_data is None:
            job_logger.error("Tried to send None to DLQ — skipping.")
            return
        if WORKER_ID == "analyser":
            ch.basic_publish(
                exchange="",
                routing_key="dead_letter_analyser_companies",
                body=json.dumps(job_data),
                properties=BasicProperties(delivery_mode=2),
            )
            job_logger.warning(
                f"Sent job {job_data.get('company_name')} (ID={job_data.get('company_id')}) to Dead Letter Queue Analyser"
            )
        if WORKER_ID == "checker":
            ch.basic_publish(
                exchange="",
                routing_key="dead_letter_checker_jobs",
                body=json.dumps(job_data),
                properties=BasicProperties(delivery_mode=2),
            )
            job_logger.warning(
                f"Sent job {job_data.get('company_name')} (ID={job_data.get('company_id')}) to Dead Letter Queue Checker"
            )

    except Exception as e:
        job_logger.error(f"Failed to publish to DLQ: {e}")


def perform_job_listing_step(
    company, company_name, company_id, job_key, job_logger, ch, redis_client, browser
) -> JobListingsResult:
    """Handle the job listings scraping step."""
    job_listings_step_done = redis_client.hget(job_key, "job_listings_step_done")
    if job_listings_step_done != "true":
        job_logger.info(
            f"Starting job listings crawl for {company_name} (ID {company_id})..."
        )
        if browser is None:
            raise RuntimeError("Browser not initialized.")
        job_listing_scraper = FetchJobsListingsScraper(
            company["website"], company_id, company_name, job_logger, browser, ch
        )
        crawl_results = job_listing_scraper()
        redis_client.hset(job_key, "job_listings_step_done", "true")
        job_logger.info(f"Job listings crawl completed for {company_name}.")
        return crawl_results
    else:
        job_logger.info(
            f"Skipping job listings crawl for {company_name} (already done)."
        )
        return {
            "website": company["website"],
            "internal_job_listing_pages": company["internal_job_listing_pages"],
            "external_job_listing_pages": company["external_job_listing_pages"],
            "emails": company["emails"],
            "containers_html": company["containers_html"],
        }


def process_analyser_job(
    ch,
    company_id: int,
    company_name: str,
    job_logger,
    method,
    connection_params,
    redis_client,
    browser,
    job_key,
    retries,
    status,
):
    """Process 'analyser' type job."""

    if status in ["in_progress", "done"]:
        job_logger.info(f"{company_name} already {status} — skipping.")
        redis_client.delete(job_key)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    if status == "failed" and retries >= 2:
        job_logger.info(f"{company_name} failed twice — sending to DLQ.")
        send_to_dead_letter_queue(
            ch, {"company_id": company_id, "company_name": company_name}, job_logger
        )
        redis_client.delete(job_key)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    mark_job_status(job_key, "in_progress", redis_client, retries)

    job_logger.info(f"Started analysis for {company_name} (attempt {retries + 1})")

    company = fetch_company_from_db(company_id, connection_params, job_logger)

    if not company:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    job_logger.info(company)

    if not company.get("website"):
        websiteScraper = WebsiteScraper(company_id, company_name, job_logger, browser, ch)
        company["website"] = websiteScraper()
                
    crawl_results = perform_job_listing_step(
        company,
        company_name,
        company_id,
        job_key,
        job_logger,
        ch,
        redis_client,
        browser,
    )
    jobs_scraper = EmailJobsScraper(
        crawl_results, company_id, company_name, job_logger, browser, ch
    )
    number_jobs_extracted = jobs_scraper()
    job_logger.info(f"Extracted {number_jobs_extracted} jobs for {company_name}")

    redis_client.hset(job_key, mapping={"status": "done", "retries": retries})
    
    ch.basic_ack(delivery_tag=method.delivery_tag)
    
    job_logger.info(f"Company analysis done for {company_name} — Redis key removed")


def process_checker_job(
    ch,
    company_id: int,
    company_name: str,
    job_logger,
    method,
    connection_params,
    redis_client,
    browser,
    job_key,
    retries,
    status,
):
    """Process 'checker' type job."""

    if status in ["in_progress", "done"]:
        job_logger.info(f"{company_name} already {status} — skipping.")
        redis_client.delete(job_key)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    if status == "failed" and retries >= 2:
        job_logger.info(f"{company_name} failed twice — sending to DLQ.")
        send_to_dead_letter_queue(
            ch, {"company_id": company_id, "company_name": company_name}, job_logger
        )
        redis_client.delete(job_key)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    mark_job_status(job_key, "in_progress", redis_client, retries)

    job_logger.info(f"Started checking jobs for {company_name} (attempt {retries + 1})")

    company = fetch_company_from_db(company_id, connection_params, job_logger)
    if not company:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    crawl_results: JobListingsResult = {
        "website": company["website"],
        "internal_job_listing_pages": company["internal_job_listing_pages"],
        "external_job_listing_pages": company["external_job_listing_pages"],
        "emails": company["emails"],
        "containers_html": company["containers_html"],
    }

    jobs_scraper = EmailJobsScraper(
        crawl_results, company_id, company_name, job_logger, browser, ch
    )
    
    number_jobs_extracted = jobs_scraper()
    
    job_logger.info(f"Extracted {number_jobs_extracted} jobs for {company_name}")

    redis_client.hset(job_key, mapping={"status": "done", "retries": retries})
    
    ch.basic_ack(delivery_tag=method.delivery_tag)
    
    job_logger.info(f"Check job done for {company_name} — Redis key removed")
