import worker.dependencies as deps

from typing import Optional
from worker.types.worker_types import (
    CompanyRecord,
    JobListingsResult,
)
from worker.utils.redis_commands import mark_session_status
from worker.core.jobs_scraper import EmailJobsScraper
from worker.core.job_listings_scraper import FetchJobsListingsScraper
from worker.core.website_scraper import WebsiteScraper
from worker.dependencies import redis_client
from worker.utils.dlq import send_to_dead_letter_queue


async def fetch_company_from_db(
    company_id: int, session_logger
) -> Optional[CompanyRecord]:
    """Fetch full company info from the database based on company_id."""
    try:
        if deps.pool_postgres is None:
            raise RuntimeError("PostgreSQL pool not initialized")

        async with deps.pool_postgres.connection() as conn:
            async with conn.cursor() as cur:

                await cur.execute(
                    """
                    SELECT website, internal_job_listing_pages, external_job_listing_pages, emails, containers_html
                    FROM companies
                    WHERE id = %s
                    """,
                    (company_id,),
                )

                company_row = await cur.fetchone()
                
                if not company_row:
                    session_logger.warning(f"Company ID {company_id} not found.")
                    return None
                
                (
                    website,
                    internal_job_listing_pages,
                    external_job_listing_pages,
                    emails,
                    containers_html,
                ) = company_row

                await cur.execute(
                    """
                    SELECT job_url
                    FROM all_jobs
                    WHERE is_existing = TRUE
                    AND company_id = %s
                    """,
                    (company_id,),
                )

                job_urls: set[str] = {r[0] for r in await cur.fetchall() if r[0]}

            
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
                    "current_job_offers": job_urls,
                }

    except Exception as e:
        
        session_logger.error(f"Error fetching company {company_id}: {e}")
        
        return None

async def perform_job_listing_step(
    company,
    company_name,
    company_id,
    session_key,
    session_logger,
    browser,
) -> JobListingsResult:
    """Handle the job listings scraping step."""

    job_listings_step_done = await redis_client.hget(session_key, "job_listings_step_done")

    if job_listings_step_done != "true":
        session_logger.info(
            f"Starting job listings crawl for {company_name} (ID {company_id})..."
        )
        
        if browser is None:
            raise RuntimeError("Browser not initialized.")
        
        job_listing_scraper = FetchJobsListingsScraper(
            company["website"], company_id, company_name, session_logger, browser
        )
        crawl_results = await job_listing_scraper()
        await redis_client.hset(session_key, "job_listings_step_done", "true")
        session_logger.info(f"Job listings crawl completed for {company_name}.")
        return crawl_results
    else:
        session_logger.info(
            f"Skipping job listings crawl for {company_name} (already done)."
        )
        return {
            "website": company["website"],
            "internal_job_listing_pages": company["internal_job_listing_pages"],
            "external_job_listing_pages": company["external_job_listing_pages"],
            "emails": company["emails"],
            "containers_html": company["containers_html"],
            "current_job_offers": company["current_job_offers"],
        }

async def process_analyser_job(
    company_id: int,
    company_name: str,
    session_logger,
    browser,
    session_key: str,
    retries: int,
    status: str,
    channel,
):
    """Process 'analyser' type job."""

    if status in ["in_progress"]:
        session_logger.info(f"{company_name} already {status}, skipping.")
        await redis_client.delete(session_key)
        return

    if status == "failed" and retries >= 2:
        session_logger.info(f"{company_name} failed twice, sending to DLQ.")
        await send_to_dead_letter_queue(
            channel,
            {"company_id": company_id, "company_name": company_name},
            session_logger,
        )
        await redis_client.delete(session_key)
        return

    await mark_session_status(session_key, "in_progress", retries)

    session_logger.info(f"Started analysis for {company_name} (attempt {retries + 1})")

    company = await fetch_company_from_db(company_id, session_logger)

    if not company:
        await redis_client.hset(session_key, "status", "failed")
        return

    if not company.get("website"):
        
        websiteScraper = WebsiteScraper(
            company_id, company_name, session_logger, browser
        )
        
        company["website"] = await websiteScraper()

    crawl_results = await perform_job_listing_step(
        company,
        company_name,
        company_id,
        session_key,
        session_logger,
        browser,
    )

    jobs_scraper = EmailJobsScraper(
        crawl_results, company_id, company_name, session_logger, browser
    )

    number_jobs_extracted = await jobs_scraper()

    session_logger.info(f"Extracted {number_jobs_extracted} jobs for {company_name}")

    await redis_client.hset(
        session_key,
        mapping={
            "status": "done",
            "retries": retries,
            "job_listings_step_done": "false",
        },
    )

    session_logger.info(f"Company analysis done for {company_name}")

async def process_checker_job(
    company_id: int,
    company_name: str,
    session_logger,
    browser,
    session_key: str,
    retries: int,
    status: str,
    channel,
):
    """Process 'checker' type job."""

    if status in ["in_progress"]:
        session_logger.info(f"{company_name} already {status} — skipping.")
        await redis_client.delete(session_key)
        return

    if status == "failed" and retries >= 2:
        session_logger.info(f"{company_name} failed twice — sending to DLQ.")
        await send_to_dead_letter_queue(
            channel, {"company_id": company_id, "company_name": company_name}, session_logger
        )
        await redis_client.delete(session_key)
        return

    await mark_session_status(session_key, "in_progress", retries)

    session_logger.info(
        f"Started checking jobs for {company_name} (attempt {retries + 1})"
    )

    company = await fetch_company_from_db(company_id, session_logger)

    if not company:
        return

    crawl_results: JobListingsResult = {
        "website": company["website"],
        "internal_job_listing_pages": company["internal_job_listing_pages"],
        "external_job_listing_pages": company["external_job_listing_pages"],
        "emails": company["emails"],
        "containers_html": company["containers_html"],
        "current_job_offers": company["current_job_offers"],
    }

    jobs_scraper = EmailJobsScraper(
        crawl_results, company_id, company_name, session_logger, browser
    )
    number_jobs_extracted = await jobs_scraper()

    session_logger.info(f"Extracted {number_jobs_extracted} jobs for {company_name}")

    await redis_client.hset(session_key, mapping={"status": "done", "retries": retries})

    session_logger.info(f"Check job done for {company_name}")
