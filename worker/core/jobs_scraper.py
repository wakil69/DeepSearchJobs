import random

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Browser, Page
from typing import List, cast, Tuple, Optional
from worker.types.worker_types import (
    Job,
    JobListingsResult,
    JobsResponse,
)
from worker.base_scraper import BaseScraper
from worker.constants.prompts import (
    PROMPT_EXTRACT_JOBS,
)
from worker.utils.llm_utils import call_llm_structured
from worker.core.show_more_button_detector import ShowMoreButtonDetector
from worker.core.pagination_detector.pagination_detector import PaginationDetector
from worker.core.post_process_jobs.post_process_jobs import PostProcessingJobs
from worker.dependencies import llm_client, LLM_MODEL, WORKER_ID
from worker.core.db_ops import DBOps
from worker.utils.url_utils import normalize_url
from worker.utils.text_utils import (
    extract_structured_text_chunks,
    extract_structured_text,
    hash_page_content,
)
from worker.core.page_processing.page_processing import PageProcessing
from worker.core.lazy_loading_detector import LazyLoadingPageDetector
from worker.core.pagination_detector.pagination_detector import PaginationDetector


class EmailJobsScraper(BaseScraper):
    def __init__(
        self,
        crawl_results: JobListingsResult,
        company_id: int,
        company_name: str,
        session_logger,
        browser: Browser,
        timeout=20000,
    ):
        """Initialize the scraper with crawl results, company details, and all sub-component instances."""
        super().__init__(company_id, company_name, session_logger, browser)
        self.website = crawl_results.get("website")
        self.internal_job_listing_pages = crawl_results.get(
            "internal_job_listing_pages", []
        )
        self.external_job_listing_pages = crawl_results.get(
            "external_job_listing_pages", []
        )
        self.emails = crawl_results["emails"]
        self.containers_pagination_html = crawl_results["containers_html"]
        self.job_offers: List[Job] = []
        self.old_job_offers: List[str] = []  # old job urls
        self.new_job_offers: List[Job] = []
        self.current_job_offers = crawl_results["current_job_offers"]
        self.company_description: Optional[str] = None
        self.timeout = timeout

        self.db_ops = DBOps(session_logger=self.session_logger)

        self.page_processing = PageProcessing(session_logger=self.session_logger)
        
        self.show_more_button_detector = ShowMoreButtonDetector(
            session_logger=self.session_logger
        )

        self.page_processing = PageProcessing(session_logger=self.session_logger)

        self.lazy_loading_detector = LazyLoadingPageDetector(
            session_logger=self.session_logger,
        )

        self.pagination_detector = PaginationDetector(
            session_logger=self.session_logger,
            containers_pagination_html=self.containers_pagination_html,
        )

        self.post_processor_jobs = PostProcessingJobs(
            session_logger=self.session_logger,
            emails=self.emails,
            company_name=self.company_name,
            company_id=self.company_id,
            job_offers=self.job_offers,
            old_job_offers=self.old_job_offers,
            new_job_offers=self.new_job_offers,
            company_description=self.company_description,
            current_job_offers=self.current_job_offers,
        )

    async def process_page_job_listing_without_pagination(
        self, page: Page, url: str, retries=1
    ) -> None:
        """
        Extracts job listings from a single-page career site or a page using
        a 'Show more' button (no traditional pagination links).

        Args:
            url: The job listing page URL.
            retries: Number of retry attempts in case of Playwright timeouts.

        Returns:
            None. Updates self.job_offers in place.
        """
        self.session_logger.info(f"Extracting jobs from: {url}")

        show_more_button = (
            await self.show_more_button_detector.check_if_show_more_pagination_button(
                page, url
            )
        )

        if show_more_button:

            await self.show_more_button_detector.process_page_with_show_more_button(
                page, url, show_more_button
            )

        attempt = 0
        text_chunks = []

        while attempt <= retries:
            try:


                _, soup = await self.page_processing.return_soup(page)

                text_chunks = extract_structured_text_chunks(self.job_offers, soup, url)

                if text_chunks:
                    break


            except PlaywrightTimeoutError as e:
                self.session_logger.warning(
                    f"Playwright timeout on attempt {attempt + 1}/{retries} for {url}: {e}"
                )

            except Exception as e:
                self.session_logger.warning(
                    f"Unexpected Playwright error on attempt {attempt + 1}/{retries} for {url}: {e}"
                )

            attempt += 1

            if attempt <= retries:
                
                self.session_logger.info(
                    f"Restarting browser (attempt {attempt}/{retries}) and retrying..."
                )
                
                # await self.restart_context()

            else:
                self.session_logger.error(
                    f"Retry limit ({retries}) reached for {url}. Skipping page."
                )
                return None

        all_jobs: List[Job] = []

        for i, chunk in enumerate(text_chunks, start=1):

            prompt = f"""
            ### **Extracted Text Content (chunk {i}/{len(text_chunks)}):**
            {chunk}
            """

            messages = [
                {"role": "system", "content": PROMPT_EXTRACT_JOBS},
                {"role": "user", "content": prompt},
            ]

            result_structured = await call_llm_structured(
                llm_client=llm_client,
                model=LLM_MODEL,
                messages=messages,
                logger=self.session_logger,
                max_tokens=8192,
                temperature=0.0,
                retry=True,
                pydantic_model=JobsResponse,
            )

            if result_structured is None:
                self.session_logger.info("LLM returned no structured result")
                continue

            try:
                all_jobs.extend(
                    cast(
                        List[Job], [job.model_dump() for job in result_structured.jobs]
                    )
                )

            except Exception as e:
                self.session_logger.error(f"Validation failed for {result_structured}: {e}")
                continue

        if len(all_jobs) == 0 and WORKER_ID == "analyser":
            self.session_logger.info(f"Removed url because new jobs empty : {url}")
            if url in self.internal_job_listing_pages:
                self.internal_job_listing_pages.remove(url)
            if url in self.external_job_listing_pages:
                self.external_job_listing_pages.remove(url)
            return

        existing_jobs = {(job["job_title"], job["job_url"]) for job in self.job_offers}

        for job in all_jobs:

            job_title = job.get("job_title")
            job_url = job.get("job_url")

            if not isinstance(job, dict) or not job_title or not job_url:
                self.session_logger.warning(
                    f"Skipping job due to missing required fields: {job}"
                )
                continue

            if job_url and not job_url.startswith(("http://", "https://", "mailto:")):
                job_url = normalize_url(url, job_url)

            if job_url and (job_title, job_url) not in existing_jobs:
                job["job_url"] = job_url
                self.job_offers.append(job)

        self.session_logger.info("Current number of job offers found: ")
        self.session_logger.info(len(self.job_offers))

        return

    async def process_page_job_listing_with_pagination(
        self,
        page: Page,
        url: str,
        base_url: str,
        dynamic_pagination=False,
        max_pages=500,
        retries=1,
    ) -> None:
        """
        Crawl job listings from a page with pagination (standard or dynamic 'click more').

        Args:
            url: The page URL to process.
            base_url: The base company or career site URL.
            dynamic_pagination: Whether pagination is JavaScript-based.
            retries: Number of retry attempts for Playwright timeouts.
        """

        self.session_logger.info(
            "Processing page | url=%s | base_url=%s | dynamic_pagination=%s | retries=%s",
            url,
            base_url,
            dynamic_pagination,
            retries,
        )

        if url in self.visited_pages and dynamic_pagination is False:
            self.session_logger.info("Skipping already visited page: %s", url)
            return

        if (
            len(self.visited_pages) >= max_pages
            or len(self.visited_hashes) >= max_pages
        ):

            self.session_logger.warning(
                "Max pages reached | visited_pages=%s | visited_hashes=%s | MAX_PAGES=%s",
                len(self.visited_pages),
                len(self.visited_hashes),
                max_pages,
            )

            return

        self.visited_pages.add(url)

        self.session_logger.info(f"Extracting jobs from: {url}")

        text_content = ""
        pagination_buttons = []

        for attempt in range(retries + 1):
            try:

                if not dynamic_pagination:

                    await self.page_processing.go_to_page(page, url)

                await page.wait_for_timeout(random.uniform(2000, 5000))

                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )

                _, soup = await self.page_processing.return_soup(page)

                text_content = soup.get_text(separator="\n", strip=True)

                if not text_content:
                    continue

                text_content = extract_structured_text(soup, url, self.job_offers)

                page_hash = hash_page_content(text_content)

                # Avoid duplicate pages by content hash
                if page_hash in self.visited_hashes:
                    self.session_logger.info(f"Skipping {url} (duplicate content).")
                    return

                self.visited_hashes.add(page_hash)

                # Extract pagination buttons
                pagination_data = (
                    await self.pagination_detector.extract_pagination_buttons(
                        page, soup, base_url
                    )
                )

                pagination_buttons = pagination_data.get("selectors", [])

                # Prevent revisiting pages with same pagination layout
                if not dynamic_pagination:
                    fingerprint = tuple(
                        sorted(
                            (btn["type"], btn["value"]) for btn in pagination_buttons
                        )
                    )

                    # Prevent revisiting pages with same pagination layout
                    if fingerprint in self.visited_buttons:
                        self.session_logger.info(
                            f"Skipping {url} (duplicate pagination buttons)."
                        )
                        return

                    self.visited_buttons.add(fingerprint)

                break

            except PlaywrightTimeoutError as e:
                self.session_logger.warning(
                    f"Playwright timeout ({attempt + 1}/{retries}) at {url}: {e}"
                )
                if attempt < retries:
                    self.session_logger.info("Restarting browser and retrying...")
                    # await self.restart_context()
                    continue
                self.session_logger.error("Retry limit reached. Skipping page.")
                return

            except Exception as e:
                self.session_logger.error(f"Unexpected error on {url}: {e}")
                return

        if not text_content:
            return

        messages = [
            {"role": "system", "content": PROMPT_EXTRACT_JOBS},
            {"role": "user", "content": f"### Extracted Text Content:\n{text_content}"},
        ]

        result_structured = await call_llm_structured(
            llm_client=llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.session_logger,
            max_tokens=8192,
            temperature=0.0,
            retry=True,
            pydantic_model=JobsResponse,
        )

        if result_structured is None:
            self.session_logger.info("LLM returned no structured result")
            return

        try:
            job_data: List[Job] = cast(
                List[Job],
                [job.model_dump() for job in result_structured.jobs],
            )

            self.session_logger.info(f"Found {len(job_data)} job(s): {job_data}")

        except Exception as e:
            self.session_logger.error(f"Processing failed for {result_structured}: {e}")
            return


        existing_jobs = {
            (
                job["job_title"],
                job["job_url"],
            )
            for job in self.job_offers
        }

        new_jobs = []

        for job in job_data:

            job_url = job["job_url"]
            job_title = job["job_title"]

            if not isinstance(job, dict) or not job_title or not job_url:
                self.session_logger.warning(
                    f"Skipping job due to missing required fields: {job}"
                )
                continue

            job_url_normalized = (
                normalize_url(url, job_url, False)
                if not job_url.startswith(("http://", "https://", "mailto:"))
                else job_url
            )

            if (
                job_url_normalized
                and (
                    job_title,
                    job_url_normalized,
                )
                not in existing_jobs
            ):
                job["job_url"] = job_url_normalized
                new_jobs.append(job)

        if not new_jobs:
            self.session_logger.info("All job listings already exist. Skipping.")
            return

        self.job_offers.extend(new_jobs)

        self.session_logger.info(f"Total job offers: {len(self.job_offers)}")

        for button in pagination_buttons:

            try:

                if "[@href=" in button.get("value", ""):

                    new_url = await self.pagination_detector.handle_standard_pagination(
                        page, button, url, base_url
                    )

                    if new_url:

                        await self.process_page_job_listing_with_pagination(
                            page, new_url, base_url, False
                        )

                else:

                    new_url = await self.pagination_detector.handle_dynamic_pagination(
                        page, button
                    )

                    if new_url:

                        await self.process_page_job_listing_with_pagination(
                            page, new_url, base_url, True
                        )

            except Exception as e:
                self.session_logger.warning(
                    f"Error handling pagination button {button}: {type(e).__name__}: {e}"
                )

        return

    async def extract_job_listings(self, job_pages: List[str]) -> None:
        """Extracts job listings from identified job pages and follows pagination."""
        self.visited_pages: set[str] = set()
        self.visited_hashes: set[str] = set()
        self.visited_buttons: set[tuple] = set()

        self.session_logger.info(f"Final job pages about to process: {job_pages}")
        
        max_attempts = 2

        for i, job_page in enumerate(job_pages, 1):

            self.session_logger.info(f"Processing URL {i}/{len(job_pages)}: {job_page}")

            base_url = job_page
            attempt = 0

            while attempt < max_attempts:

                attempt += 1

                page = await self.create_page()

                try:
                    self.session_logger.info(
                        f"Checking pagination from: {job_page} (attempt {attempt}/{max_attempts})"
                    )

                    pagination_buttons_full = (
                        await self.pagination_detector.check_if_pagination_buttons(
                            page, job_page
                        )
                    )

                    pagination_buttons = pagination_buttons_full.get("selectors", [])

                    if pagination_buttons:

                        self.session_logger.info(
                            f"Pagination in this page: {pagination_buttons}"
                        )

                        await self.process_page_job_listing_with_pagination(
                            page, job_page, base_url
                        )

                        self.visited_buttons = set()

                    else:

                        self.session_logger.info(
                            f"No pagination in this page: {pagination_buttons}"
                        )

                        await self.process_page_job_listing_without_pagination(
                            page, job_page
                        )

                    break

                except Exception as e:

                    self.session_logger.error(
                        f"Error processing {job_page} (attempt {attempt}/{max_attempts}): {e}",
                        exc_info=True,
                    )

                    await self.restart_context()

                    if attempt >= max_attempts:
                        self.session_logger.error(
                            f"Failed processing {job_page} after {max_attempts} attempts"
                        )

                finally:

                    await page.close()

        return

    async def __call__(self):
        """Starts the jobs scraping processes."""

        self.session_logger.info("Starting Job Extraction...")

        await self.create_context_with_proxy()

        job_listing_pages_to_process = (
            self.internal_job_listing_pages + self.external_job_listing_pages
        )

        await self.extract_job_listings(job_listing_pages_to_process)

        page = await self.create_page()

        try:

            await self.post_processor_jobs.post_process(page)

        finally:

            await page.close()

        self.company_description = self.post_processor_jobs.company_description

        self.session_logger.info("\nFinal Results:")
        self.session_logger.info(f"Emails {len(list(self.emails))} : {self.emails}")
        self.session_logger.info(
            f"New Job Offers {len(self.new_job_offers)}: {[(item["job_title"], item["job_url"]) for item in self.new_job_offers]}"
        )
        self.session_logger.info(
            f"Old Job Offers {len(self.old_job_offers)}: {[item for item in self.old_job_offers]}"
        )

        await self.clean_contexts_playwright()

        await self.db_ops.save_db_results(
            company_id=self.company_id,
            company_name=self.company_name,
            company_description=self.company_description,
            website=self.website,
            emails=self.emails,
            external_job_listing_pages=self.external_job_listing_pages,
            internal_job_listing_pages=self.internal_job_listing_pages,
            containers_html=self.containers_pagination_html,
            old_job_offers=self.old_job_offers,
            new_job_offers=self.new_job_offers,
        )

        return len(self.new_job_offers)
