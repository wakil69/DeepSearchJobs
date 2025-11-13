import os
import psycopg

from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from psycopg.types.json import Json
from playwright.sync_api import Browser
from pika.adapters.blocking_connection import BlockingChannel
from typing import List, Any, cast, Tuple, Optional
from worker_sync.worker_types import (
    Job,
    JobListingsResult,
    JobsResponse,
)
from worker_sync.base_scraper import BaseScraper
from worker_sync.core.prompts import (
    PROMPT_EXTRACT_JOBS,
)
from worker_sync.core.llm_utils import call_llm_structured
from worker_sync.core.show_more_button_detector import ShowMoreButtonDetector
from worker_sync.core.pagination_detector import PaginationDetector
from worker_sync.core.post_process_jobs import PostProcessingJobs


load_dotenv()


LLM_MODEL: str = os.getenv("LLM_MODEL", "")

NODE_ENV = os.getenv("NODE_ENV", "unknown")

prefix = "DEV" if NODE_ENV == "development" else ""

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


class EmailJobsScraper(BaseScraper):
    def __init__(
        self,
        crawl_results: JobListingsResult,
        company_id: int,
        company_name: str,
        logger,
        browser: Browser,
        ch: BlockingChannel,
    ):
        super().__init__(company_id, company_name, logger, browser, ch)
        self.website = crawl_results.get("website")
        self.internal_job_listing_pages = crawl_results.get(
            "internal_job_listing_pages", []
        )
        self.external_job_listing_pages = crawl_results.get(
            "external_job_listing_pages", []
        )
        self.emails = crawl_results["emails"]
        self.containers_html = crawl_results["containers_html"]
        self.job_offers: List[Job] = []
        self.company_description: Optional[str] = None

        shared_deps = {
            "logger": self.logger,
            "page": self.page,
            "llm_client": self.llm_client,
            "llm_model": LLM_MODEL,
            "restart_context": self.restart_context,
        }

        self.show_more_button_detector = ShowMoreButtonDetector(
            **shared_deps,
            hash_page_content=self.hash_page_content,
        )

        self.pagination_detector = PaginationDetector(
            **shared_deps,
            containers_html=self.containers_html,
            process_page_job_listing_with_pagination=self.process_page_job_listing_with_pagination,
            normalize_url=self.normalize_url,
        )

        self.post_processor_jobs = PostProcessingJobs(
            **shared_deps,
            emails=self.emails,
            get_emails=self.get_emails,
            send_heartbeat_if_needed=self.send_heartbeat_if_needed,
            company_name=self.company_name,
            company_id=self.company_id,
            user_agents=self.user_agents,
            job_offers=self.job_offers,
            company_description=self.company_description
        )

    def extract_structured_text_chunks(
        self, soup: BeautifulSoup, url: str
    ) -> List[str]:
        """
        Extracts structured text from single-page or 'load more'-style career pages
        and splits it into LLM-friendly chunks for job extraction or analysis.

        Args:
            soup (BeautifulSoup): Parsed HTML content of the career page.
            url (str): Base URL used to resolve relative links.

        Returns:
            List[str]: List of formatted text chunks (~2000 chars each),
            preserving document hierarchy and readability for LLM input.
        """

        structured_content = []
        seen_links = set()
        verified_existing_jobs = [job["job_url"] for job in self.job_offers]

        MAX_ITEMS_PER_BLOCK = 15

        def get_associated_link(element):
            """Finds the nearest anchor link within or related to the element."""
            link = element.find("a", href=True)
            if link:
                link = self.normalize_url(url, link["href"])
                seen_links.add(link)
                return link
            return ""

        def handle_link(link: Optional[str], text: str):
            """Decide whether to include in structured_content or verified_existing_jobs."""
            if link in verified_existing_jobs:
                return None
            return text

        # --- Headings (batch individually, each heading is its own block) ---
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            link = get_associated_link(heading)
            text = (
                f"### {heading.get_text(strip=True)}{f' ({link})' if link else ''} ###"
            )
            result = handle_link(link, text)
            if result:
                headings.append(result)
        for i in range(0, len(headings), MAX_ITEMS_PER_BLOCK):
            structured_content.append("\n".join(headings[i : i + MAX_ITEMS_PER_BLOCK]))

        # --- Paragraphs ---
        paragraphs = []
        for paragraph in soup.find_all("p"):
            link = get_associated_link(paragraph)
            text = f"- {paragraph.get_text(strip=True)}{f' ({link})' if link else ''}"
            result = handle_link(link, text)
            if result:
                paragraphs.append(result)
        for i in range(0, len(paragraphs), MAX_ITEMS_PER_BLOCK):
            structured_content.append(
                "\n".join(paragraphs[i : i + MAX_ITEMS_PER_BLOCK])
            )

        # --- Lists (UL/LI) ---
        for ul in soup.find_all("ul"):
            if not isinstance(ul, Tag):
                continue
            items = []
            for li in ul.find_all("li"):
                if not isinstance(li, Tag):
                    continue
                link_el = li.find("a", href=True)
                if isinstance(link_el, Tag) and link_el.has_attr("href"):
                    link = self.normalize_url(url, str(link_el["href"]))
                    seen_links.add(link)
                    text = f"  • {li.get_text(strip=True)} ({link})"
                    result = handle_link(link, text)
                    if result:
                        items.append(result)
            for i in range(0, len(items), MAX_ITEMS_PER_BLOCK):
                structured_content.append("\n".join(items[i : i + MAX_ITEMS_PER_BLOCK]))

        # --- Tables ---
        table_rows = []
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            for row in table.find_all("tr"):
                if not isinstance(row, Tag):
                    continue
                cells = []
                for td in row.find_all(["td", "th"]):
                    if not isinstance(td, Tag):
                        continue
                    link_el = td.find("a", href=True)
                    if isinstance(link_el, Tag) and link_el.has_attr("href"):
                        link = self.normalize_url(url, str(link_el["href"]))
                        seen_links.add(link)
                        text = f"{td.get_text(strip=True)} ({link})"
                        result = handle_link(link, text)
                        if result:
                            cells.append(result)
                if cells:
                    table_rows.append(" | ".join(cells))
        for i in range(0, len(table_rows), MAX_ITEMS_PER_BLOCK):
            structured_content.append(
                "\n".join(table_rows[i : i + MAX_ITEMS_PER_BLOCK])
            )

        # --- Orphan links ---
        links = []
        for a in soup.find_all("a", href=True):
            if isinstance(a, Tag):
                href = str(a.get("href"))
                if href.startswith("mailto:"):
                    continue
                link = self.normalize_url(url, href)
                if (
                    not a.find_parent(
                        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "li", "table"]
                    )
                    and link not in seen_links
                ):
                    text = f"- [{a.get_text(strip=True)}]({link})"
                    result = handle_link(link, text)
                    if result:
                        links.append(result)
        for i in range(0, len(links), MAX_ITEMS_PER_BLOCK):
            link_block = links[i : i + MAX_ITEMS_PER_BLOCK]
            structured_content.append("\n### Links ###\n" + "\n".join(link_block))

        # --- Chunking by character length (still applied globally) ---
        chunks = []
        current_chunk: list[str] = []
        current_len = 0
        MAX_CHUNK_SIZE = 2000

        for block in structured_content:
            block_len = len(block) + 1
            if current_len + block_len > MAX_CHUNK_SIZE and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [block]
                current_len = block_len
            else:
                current_chunk.append(block)
                current_len += block_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    def process_page_job_listing_without_pagination(self, url: str, retries=1) -> None:
        """
        Extracts job listings from a single-page career site or a page using
        a 'Show more' button (no traditional pagination links).

        Args:
            url: The job listing page URL.
            retries: Number of retry attempts in case of Playwright timeouts.

        Returns:
            None. Updates self.job_offers in place.
        """
        self.logger.info(f"Extracting jobs from: {url}")

        show_more_button = (
            self.show_more_button_detector.check_if_show_more_pagination_button(url)
        )

        if show_more_button:

            self.show_more_button_detector.process_page_with_show_more_button(
                url, show_more_button
            )

        attempt = 0
        text_chunks = []

        while attempt <= retries:
            try:
                self.send_heartbeat_if_needed()

                html_content = self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                for tag in soup(["script", "style", "meta", "noscript", "svg"]):
                    tag.decompose()

                text_chunks = self.extract_structured_text_chunks(soup, url)
                
                if text_chunks:
                    break

            except PlaywrightTimeoutError as e:
                self.logger.warning(
                    f"Playwright timeout on attempt {attempt + 1}/{retries} for {url}: {e}"
                )

            except Exception as e:
                self.logger.warning(
                    f"Unexpected Playwright error on attempt {attempt + 1}/{retries} for {url}: {e}"
                )

            attempt += 1
            
            if attempt <= retries:
                self.logger.info(
                    f"Restarting browser (attempt {attempt}/{retries}) and retrying..."
                )
                self.restart_context()
                
            else:
                self.logger.error(
                    f"Retry limit ({retries}) reached for {url}. Skipping page."
                )
                return None

        all_jobs: List[Job] = []

        for i, chunk in enumerate(text_chunks, start=1):

            self.send_heartbeat_if_needed()

            prompt = f"""
            ### **Extracted Text Content (chunk {i}/{len(text_chunks)}):**
            {chunk}
            """

            messages = [
                {"role": "system", "content": PROMPT_EXTRACT_JOBS},
                {"role": "user", "content": prompt},
            ]

            result_structured = call_llm_structured(
                llm_client=self.llm_client,
                model=LLM_MODEL,
                messages=messages,
                logger=self.logger,
                max_tokens=8192,
                temperature=0.0,
                retry=True,
                pydantic_model=JobsResponse
            )

            try:
                validated = JobsResponse.model_validate(result_structured)
                self.logger.info(
                    f"Found {len(validated.jobs)} job(s) in chunk {i}: {validated.jobs}"
                )
                all_jobs.extend(
                    cast(List[Job], [job.model_dump() for job in validated.jobs])
                )

            except Exception as e:
                self.logger.error(f"Validation failed for {result_structured}: {e}")
                continue

        if len(all_jobs) == 0:
            self.logger.info(f"Removed url because new jobs empty : {url}")
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
                self.logger.warning(
                    f"Skipping job due to missing required fields: {job}"
                )
                continue

            if job_url and not job_url.startswith(("http://", "https://", "mailto:")):
                job_url = self.normalize_url(url, job_url)

            if job_url and (job_title, job_url) not in existing_jobs:
                job["job_url"] = job_url
                self.job_offers.append(job)

        self.logger.info("Current number of job offers found: ")
        self.logger.info(len(self.job_offers))

        return

    def process_page_job_listing_with_pagination(
        self, url: str, base_url: str, dynamic_pagination=False, retries=1
    ) -> None:
        """
        Crawl job listings from a page with pagination (standard or dynamic 'click more').

        Args:
            url: The page URL to process.
            base_url: The base company or career site URL.
            dynamic_pagination: Whether pagination is JavaScript-based.
            retries: Number of retry attempts for Playwright timeouts.
        """
        if url in self.visited_pages and dynamic_pagination == False:
            return

        self.visited_pages.add(url)

        self.logger.info(f"Extracting jobs from: {url}")

        text_content = ""
        pagination_buttons = []

        for attempt in range(retries + 1):
            try:
                self.send_heartbeat_if_needed()

                if not dynamic_pagination:
                    self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
                    self.page.wait_for_load_state("networkidle", timeout=10000)

                self.page.wait_for_timeout(2000)

                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                html_content = self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                # Clean soup for text extraction
                for tag in soup(["script", "style", "meta", "noscript", "svg"]):
                    tag.decompose()

                text_content = self.extract_structured_text(soup, url)
                page_hash = self.hash_page_content(text_content)

                # Avoid duplicate pages by content hash
                if page_hash in self.visited_hashes:
                    self.logger.info(f"Skipping {url} (duplicate content).")
                    return

                self.visited_hashes.add(page_hash)

                # Extract pagination buttons
                pagination_data = self.pagination_detector.extract_pagination_buttons(
                    soup, base_url
                )

                pagination_buttons = pagination_data.get("pagination_buttons", [])

                # Prevent revisiting pages with same pagination layout
                if not dynamic_pagination:
                    fingerprint = tuple(sorted(pagination_buttons))
                    if fingerprint in self.visited_buttons:
                        self.logger.info(
                            f"Skipping {url} (duplicate pagination buttons)."
                        )
                        return
                    self.visited_buttons.add(fingerprint)

                break

            except PlaywrightTimeoutError as e:
                self.logger.warning(
                    f"Playwright timeout ({attempt + 1}/{retries}) at {url}: {e}"
                )
                if attempt < retries:
                    self.logger.info("Restarting browser and retrying...")
                    self.restart_context()
                    continue
                self.logger.error("Retry limit reached. Skipping page.")
                return

            except Exception as e:
                self.logger.error(f"Unexpected error on {url}: {e}")
                return

        if not text_content:
            return

        messages = [
            {"role": "system", "content": PROMPT_EXTRACT_JOBS},
            {"role": "user", "content": f"### Extracted Text Content:\n{text_content}"},
        ]

        result_structured = call_llm_structured(
            llm_client=self.llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.logger,
            max_tokens=8192,
            temperature=0.0,
            retry=True,
            pydantic_model=JobsResponse
        )

        try:
            validated = JobsResponse.model_validate(result_structured)
            job_data: list[Job] = cast(
                list[Job], [job.model_dump() for job in validated.jobs]
            )
            self.logger.info(f"Found {len(job_data)} job(s): {job_data}")
        except Exception as e:
            self.logger.error(f"Validation failed for {result_structured}: {e}")
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
                self.logger.warning(
                    f"Skipping job due to missing required fields: {job}"
                )
                continue

            job_url_normalized = (
                self.normalize_url(url, job_url, False)
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
            self.logger.info("All job listings already exist. Skipping.")
            return

        self.job_offers.extend(new_jobs)

        self.logger.info(f"Total job offers: {len(self.job_offers)}")

        for button_xpath in pagination_buttons:
            try:
                if "[@href=" in button_xpath:
                    self.pagination_detector.handle_standard_pagination(
                        button_xpath, url, base_url
                    )
                else:
                    self.pagination_detector.handle_dynamic_pagination(
                        button_xpath, url, base_url
                    )
            except Exception as e:
                self.logger.warning(
                    f"Error handling pagination button {button_xpath}: {type(e).__name__}: {e}"
                )

        return

    def extract_job_listings(self, job_pages: List[str]) -> None:
        """Extracts job listings from identified job pages and follows pagination."""
        self.visited_pages: set[str] = set()
        self.visited_hashes: set[str] = set()
        self.visited_buttons: set[Tuple[str, ...]] = set()

        self.logger.info(f"Final job pages about to process: {job_pages}")

        for i, job_page in enumerate(job_pages, 1):

            self.logger.info(f"Processing URL {i}/{len(job_pages)}: {job_page}")

            base_url = job_page

            try:

                self.logger.info(f"Checking pagination from: {job_page}")

                pagination_buttons = (
                    self.pagination_detector.check_if_pagination_buttons(job_page)
                )

                if pagination_buttons:

                    self.logger.info(f"Pagination in this page: {pagination_buttons}")

                    self.process_page_job_listing_with_pagination(job_page, base_url)

                    self.visited_buttons = set()

                else:

                    self.logger.info(
                        f"No pagination in this page: {pagination_buttons}"
                    )

                    self.process_page_job_listing_without_pagination(job_page)

            except Exception as e:
                self.logger.error(f"Error processing {job_page}: {e}", exc_info=True)
                continue

        return

    def insert_jobs_and_emails_in_db(self, conn) -> None:
        """Insert jobs and emails into the DB (companies and all_jobs tables)."""
        try:
            with conn.cursor() as cur:
                website = self.website
                emails = list(self.emails) or None
                external_job_listing_pages = self.external_job_listing_pages or None
                internal_job_listing_pages = self.internal_job_listing_pages or None
                containers_html = {
                    base_url: list(containers_html)
                    for base_url, containers_html in self.containers_html.items()
                }

                cur.execute(
                    """
                    UPDATE companies
                    SET website = %s, emails = %s, description = %s, external_job_listing_pages = %s, internal_job_listing_pages = %s, containers_html = %s
                    WHERE id = %s
                    """,
                    (
                        website,
                        emails,
                        self.company_description,
                        external_job_listing_pages,
                        internal_job_listing_pages,
                        Json(containers_html),
                        self.company_id,
                    ),
                )

                jobs = self.job_offers
                if not jobs:
                    self.logger.info("No job offers to insert for this company.")
                    return
                
                job_urls = [job["job_url"] for job in jobs if job.get("job_url")]


                cur.execute(
                    """
                    SELECT job_url
                    FROM all_jobs
                    WHERE job_url = ANY(%s)
                    AND is_existing = TRUE;
                    """,
                    (job_urls,),
                )
                existing_urls = {row[0] for row in cur.fetchall()}

                self.logger.info(
                    f"Found {len(existing_urls)} existing active jobs for this company."
                )
            
                for job in jobs:
                    job_url = job.get("job_url")
                    if not job_url:
                        continue

                    job_record = (
                        self.company_id,
                        job.get("job_title"),
                        job.get("location_country"),
                        job.get("location_region"),
                        job_url,
                        job.get("job_description"),
                        job.get("skills_required"),
                        job.get("contract_type"),
                        job.get("salary"),
                        job.get("job_title_vector"),
                    )

                    try:
                        if job_url in existing_urls:
                            # Update existing job
                            cur.execute(
                                """
                                UPDATE all_jobs
                                SET
                                    company_id = %s,
                                    job_title = %s,
                                    location_country = %s,
                                    location_region = %s,
                                    job_description = %s,
                                    skills_required = %s,
                                    contract_type = %s,
                                    salary = %s,
                                    job_title_vectors = %s,
                                    is_existing = TRUE
                                WHERE job_url = %s
                                AND is_existing = TRUE;
                                """,
                                (*job_record[:4], *job_record[5:10], job_record[4]),
                            )
                        else:
                            # Insert new job
                            cur.execute(
                                """
                                INSERT INTO all_jobs (
                                    company_id, job_title, location_country, location_region,
                                    job_url, job_description, skills_required, contract_type,
                                    salary, job_title_vectors, is_existing
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE);
                                """,
                                job_record,
                            )

                    except Exception as job_error:
                        self.logger.warning(
                            f"⚠️ Skipped job due to error: {job_error} — {job}"
                        )

                self.logger.info("✅ Successfully inserted/updated all job offers for company.")
                
        except psycopg.IntegrityError as e:
            self.logger.error(f"IntegrityError: {e} - Possible constraint violation")
        except psycopg.OperationalError as e:
            self.logger.error(f"OperationalError: {e}")
        except Exception as e:
            self.logger.error(f"Error inserting company: {e}")

    def update_old_jobs(self, conn) -> None:
        """Set is_existing to False for all jobs of a specific company."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE all_jobs
                    SET is_existing = FALSE
                    WHERE company_id = %s
                    RETURNING id
                    """,
                    (self.company_id,),
                )

                updated_job_ids = [row[0] for row in cur.fetchall()]

                self.logger.info(
                    f"Updated {len(updated_job_ids)} old jobs opportunities"
                )

        except psycopg.OperationalError as e:
            self.logger.error(f"🔴 Database Connection Error: {e}")
        except Exception as e:
            self.logger.error(f"Error updating old jobs: {e}")

    def save_db_results(self) -> None:
        """Save scraping results into the database."""

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                try:
                    self.update_old_jobs(conn)

                    self.insert_jobs_and_emails_in_db(conn)

                    conn.commit()

                    return 

                except Exception as e:
                    conn.rollback()
                    self.logger.error(
                        f"Database error for company {self.company_name}: {e}"
                    )
                    raise

    def __call__(self):
        """Starts the jobs scraping processes."""

        job_listing_pages_to_process = (
            self.internal_job_listing_pages + self.external_job_listing_pages
        )

        self.extract_job_listings(job_listing_pages_to_process)
        
        self.post_processor_jobs.post_process()
        
        self.company_description = self.post_processor_jobs.company_description
    
        self.logger.info("\nFinal Results:")
        self.logger.info(f"Emails {len(list(self.emails))} : {self.emails}")
        self.logger.info(
            f"Job Offers {len(self.job_offers)}: {[(item["job_title"], item["job_url"]) for item in self.job_offers]}"
        )

        self.clean_contexts_playwright()

        self.save_db_results()

        return len(self.job_offers)
