import re
import os
import json
import time
import psycopg
import random

from collections import deque, defaultdict
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse, urlunparse
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from worker_sync.worker_types import (
    CareerPagesResponse,
    IsJobListingPageResponse,
    JobListingsResult,
)
from typing import List, DefaultDict, Literal, Optional, Any, Callable
from pika.adapters.blocking_connection import BlockingChannel
from playwright.sync_api import Browser
from worker_sync.core.prompts import (
    get_filter_internal_career_pages_prompt,
    get_filter_external_career_pages_prompt,
    get_filter_career_pages_prompt,
    get_identify_career_page_prompt,
)
from worker_sync.core.llm_utils import call_llm_structured
from worker_sync.base_scraper import BaseScraper
from pathlib import Path

load_dotenv()

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
]

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

blocked_domains_file_path = (
    Path(__file__).resolve().parent.parent / "blocked_domains.json"
)

with open(blocked_domains_file_path, "r", encoding="utf-8") as f:
    blocked_domains: list[str] = json.load(f)


class FetchJobsListingsScraper(BaseScraper):
    def __init__(
        self,
        base_url: str,
        company_id: int,
        company_name: str,
        logger,
        browser: Browser,
        ch: BlockingChannel,
    ):
        super().__init__(company_id, company_name, logger, browser, ch)
        self.base_url = base_url.rstrip("/")
        self.external_job_listing_pages: List[str] = []
        self.internal_job_listing_pages: List[str] = []
        self.external_urls: set[str] = set()
        self.emails: set[str] = set()

    @staticmethod
    def extract_visible_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup(["script", "style", "meta", "svg"]):
            script.decompose()
        return soup.get_text(separator=" ")

    @staticmethod
    def same_domain(url1: str, url2: str):
        """Compare two URLs ignoring www and case."""
        n1 = urlparse(url1).netloc.lower().replace("www.", "")
        n2 = urlparse(url2).netloc.lower().replace("www.", "")
        return n1 == n2

    @staticmethod
    def deduplicate_by_base_url(urls: List[str]) -> List[str]:
        """
        Deduplicate URLs by their base (path + domain), ignoring query strings and fragments.

        This ensures that URLs like:
            https://example.com/jobs?page=1
            https://example.com/jobs?page=2
        are treated as the same base and only the shortest version is kept:
            https://example.com/jobs

        Args:
            urls (List[str]): List of absolute URLs (may include queries/fragments)

        Returns:
            List[str]: Deduplicated URLs with clean, minimal base paths.
        """
        seen: dict[str, str] = {}
        for url in urls:
            parsed = urlparse(url)
            # --- Build a normalized base URL (remove query + fragment)
            base_url = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")

            # --- If we've seen this base before, keep the shortest version
            if base_url not in seen or len(url) < len(seen[base_url]):
                seen[base_url] = url
        return list(seen.values())

    @staticmethod
    def keep_only_roots(urls: set[str]) -> set[str]:
        """
        Keep only the shortest, root-level URLs per domain.

        Removes deeper duplicates so only the highest-level "root" URL
        for each domain remains. Useful to avoid redundant crawling
        (e.g., pagination or nested job pages).

        Example:
            Input:
                [
                    "https://partner.com/jobs",
                    "https://partner.com/jobs/page/2",
                    "https://partner.com/jobs/details/123",
                    "https://another.com/careers",
                    "https://another.com/careers/openings"
                ]
            Output:
                [
                    "https://partner.com/jobs",
                    "https://another.com/careers"
                ]

        Args:
            urls (List[str]): List of full URLs.

        Returns:
            List[str]: Deduplicated root-level URLs.
        """
        cleaned = []
        for url in urls:
            parsed = urlparse(url)
            normalized = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
            if not normalized:  # Guard for empty or invalid URLs
                continue
            cleaned.append(normalized)

        # --- Deduplicate and sort by domain + path length
        cleaned = sorted(
            set(cleaned), key=lambda u: (urlparse(u).netloc, len(urlparse(u).path))
        )

        # --- Keep only the shortest (root) URL per domain
        roots: set[str] = set()
        for url in cleaned:
            parsed = urlparse(url)
            # Check if already covered by an existing root
            if not any(
                parsed.netloc == urlparse(root).netloc and url.startswith(root + "/")
                for root in roots
            ):
                roots.add(url)

        return roots

    def crawl_site_depth(self, base_url: str, max_depth: int = 1) -> List[str]:
        """
        Crawls a site using Playwright to extract emails, subpages, and external links.
        Limits crawling to `max_depth` hierarchical levels.
        """

        # === Initialization ===
        visited_subpages = set()
        queue = deque([(base_url, 0)])
        failed_urls = set()
        first_iteration = True
        pattern_counts: DefaultDict[str, int] = defaultdict(int)

        # === Crawl control constants ===
        MAX_PER_PATTERN = 5  # Prevent over-crawling repetitive URL structures
        SKIP_EXTENSIONS = [".js", ".css", ".jpg", ".jpeg", ".png", ".pdf"]
        VIDEO_KEYWORDS = [
            "youtube",
            "vimeo",
            "dailymotion",
            "wistia",
            "player.",
            "video",
        ]

        # === Helper: Normalize URL into pattern keys ===
        def get_pattern_keys(url: str, depth: int = 2) -> List[str]:
            """
            Normalize a URL into hierarchical pattern keys for rate-limiting.
            Strips language codes like /en/, /de/, /en-US/, /pt-BR/, etc.
            Ensures parent categories also count towards the limit.
            """
            parsed = urlparse(url)
            parts = parsed.path.strip("/").split("/")
            LANG_PATTERN = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")

            # Drop leading language code if present (e.g., /en/, /de/, /en-US/)
            if parts and LANG_PATTERN.match(parts[0]):
                parts = parts[1:]

            # Collapse trailing numeric parts (e.g., /123/)
            while parts and re.fullmatch(r"\d+", parts[-1]):
                parts = parts[:-1]

            # Generate hierarchical pattern keys
            keys = []
            for d in range(min(len(parts), depth), 0, -1):
                path = "/" + "/".join(parts[:d]) + "/"
                keys.append(f"{parsed.scheme}://{parsed.netloc}{path}")
            return keys

        # === Helper: Enqueue internal links safely ===
        def enqueue_if_valid(link_url: str, current_depth: int):
            """Add a same-domain link to the crawl queue if depth and deduplication checks pass."""
            is_same_domain = self.same_domain(link_url, self.base_url)
            if is_same_domain:
                if (
                    link_url not in visited_subpages
                    and all(link_url != q for q, _ in queue)
                    and current_depth + 1 <= max_depth
                ):
                    queue.append((link_url, current_depth + 1))
                return

            self.external_urls.add(link_url)

        # === Crawl Loop ===
        while queue:
            self.send_heartbeat_if_needed()
            url, depth = queue.popleft()
            normalized_url = url.split("#")[0]

            # --- Pattern rate limiting ---
            pattern_keys = get_pattern_keys(normalized_url, depth=2)
            if any(pattern_counts[k] >= MAX_PER_PATTERN for k in pattern_keys):
                self.logger.info(f"⏭️ Skipping {normalized_url}, pattern cap reached")
                continue
            for k in pattern_keys:
                pattern_counts[k] += 1

            # --- Already visited or too deep ---
            if normalized_url in visited_subpages or depth > max_depth:
                continue

            try:
                # === Load the page ===
                self.page.goto(
                    normalized_url, timeout=25000, wait_until="domcontentloaded"
                )

                normalized_url = self.page.url  # handle redirects

                if first_iteration:
                    self.base_url = normalized_url.rstrip("/")
                    self.logger.info(f"🔄 Base URL updated to: {self.base_url}")
                    first_iteration = False

                self.logger.info(f"Visited Url: {normalized_url}")

                visited_subpages.add(normalized_url)

                self.page.wait_for_load_state("networkidle", timeout=5000)

                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                time.sleep(random.uniform(1, 3))  # human-like delay

                # === Extract content ===
                html_content = self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                # Extract and store any visible emails
                visible_text = self.extract_visible_text(html_content)
                new_emails = self.get_emails(visible_text)
                if new_emails:
                    self.logger.info(f"Emails found: {new_emails}")
                    self.emails.update(new_emails)

                # === Process iframes ===
                for iframe in soup.find_all("iframe", src=True):
                    if not isinstance(iframe, Tag):
                        continue

                    src_attr = iframe.get("src")
                    if not isinstance(src_attr, str):
                        continue

                    iframe_src = src_attr.split("#")[0]
                    iframe_url = urljoin(normalized_url, iframe_src)

                    if (
                        any(keyword in iframe_url.lower() for keyword in VIDEO_KEYWORDS)
                        or any(iframe_url.endswith(ext) for ext in SKIP_EXTENSIONS)
                        or iframe_url.startswith("mailto:")
                        or "javascript:void" in iframe_url
                        or iframe_url in visited_subpages
                    ):
                        continue

                    enqueue_if_valid(iframe_url, depth)

                # === Process links (<a> tags) ===
                for link in soup.find_all("a", href=True):
                    if not isinstance(link, Tag):
                        continue

                    href_attr = link.get("href")
                    if not isinstance(href_attr, str):
                        continue

                    href = href_attr.split("#")[0]
                    if not href or href.startswith(("#", "tel:", "javascript:")):
                        continue

                    absolute_link = urljoin(normalized_url, href)
                    if (
                        any(
                            keyword in absolute_link.lower()
                            for keyword in VIDEO_KEYWORDS
                        )
                        or absolute_link in visited_subpages
                        or any(absolute_link.endswith(ext) for ext in SKIP_EXTENSIONS)
                        or absolute_link.startswith("mailto:")
                        or "javascript:void" in absolute_link
                    ):
                        continue

                    enqueue_if_valid(absolute_link, depth)

            # === Timeout handling ===
            except PlaywrightTimeoutError as e:
                self.logger.warning(f"⚠️ Timeout on {normalized_url}: {e}")
                if normalized_url not in failed_urls:
                    failed_urls.add(normalized_url)
                    backoff = 2 * len(failed_urls)
                    self.logger.info(
                        f"🔁 Restarting browser and retrying after {backoff}s..."
                    )
                    time.sleep(backoff)
                    self.restart_context()
                    queue.append((url, depth))
                else:
                    self.logger.warning(
                        "❌ Already retried once, skipping permanently."
                    )
                continue

            # === General exception handling ===
            except Exception as e:
                self.logger.error(f"⚠️ Unexpected error on {normalized_url}: {e}")
                continue

        # === Return crawled pages ===
        return list(visited_subpages)

    def crawl_site_path_prefix_only(self, base_url: str, max_depth=1) -> List[str]:
        """
        Crawls a site using Playwright to extract emails, subpages, and external links.
        Only visits URLs that match the base_url path prefix.
        Limits crawling to `max_depth` hierarchical levels.
        """

        # === Initialization ===
        visited_subpages = set()
        queue = deque([(base_url, 0)])
        failed_urls = set()

        base_parsed = urlparse(base_url)
        base_path_prefix = base_parsed.path.rstrip("/") or "/"

        # === Constants ===
        SKIP_EXTENSIONS = [".js", ".css", ".jpg", ".jpeg", ".png", ".pdf"]
        VIDEO_KEYWORDS = [
            "youtube",
            "vimeo",
            "dailymotion",
            "wistia",
            "player.",
            "video",
        ]

        while queue:

            self.send_heartbeat_if_needed()

            url, depth = queue.popleft()
            normalized_url = url.split("#")[0]

            if normalized_url in visited_subpages or depth > max_depth:
                continue

            try:

                self.page.goto(
                    normalized_url, timeout=15000, wait_until="domcontentloaded"
                )
                self.page.wait_for_load_state("networkidle", timeout=10000)

                self.logger.info(f"Visited Url: {self.page.url}")

                time.sleep(random.uniform(1, 3))

                self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                visited_subpages.add(normalized_url)

                # === Parse content ===
                html_content = self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                # === Extract and store emails ===
                visible_text = self.extract_visible_text(html_content)
                new_emails = self.get_emails(visible_text)
                if new_emails:
                    self.logger.info(f"Emails found: {new_emails}")
                    self.emails.update(new_emails)

                # === Helper function for enqueueing internal URLs ===
                def enqueue_if_valid(link_url: str):
                    """Enqueue a same-domain, prefix-matching URL if depth allows."""
                    is_same_domain = self.same_domain(link_url, base_url)
                    if is_same_domain:
                        if (
                            urlparse(link_url).path.startswith(base_path_prefix)
                            and link_url not in visited_subpages
                            and all(link_url != queued for queued, _ in queue)
                            and depth + 1 <= max_depth
                        ):
                            queue.append((link_url, depth + 1))

                        return
                    self.external_urls.add(link_url)

                # === Process iframes ===
                for iframe in soup.find_all("iframe", src=True):
                    if not isinstance(iframe, Tag):
                        continue

                    src_attr = iframe.get("src")
                    if not isinstance(src_attr, str):
                        continue

                    iframe_src = src_attr.split("#")[0]
                    iframe_url = urljoin(normalized_url, iframe_src)

                    if (
                        any(keyword in iframe_url.lower() for keyword in VIDEO_KEYWORDS)
                        or any(iframe_url.endswith(ext) for ext in SKIP_EXTENSIONS)
                        or iframe_url.startswith("mailto:")
                        or "javascript:void" in iframe_url
                    ):
                        continue

                    enqueue_if_valid(iframe_url)

                # === Process <a> links ===
                for link in soup.find_all("a", href=True):
                    if not isinstance(link, Tag):
                        continue

                    href_attr = link.get("href")
                    if not isinstance(href_attr, str):
                        continue

                    href = href_attr.split("#")[0]
                    if not href or href.startswith(("#", "tel:", "javascript:")):
                        continue

                    absolute_link = urljoin(normalized_url, href)

                    if (
                        any(
                            keyword in absolute_link.lower()
                            for keyword in VIDEO_KEYWORDS
                        )
                        or any(absolute_link.endswith(ext) for ext in SKIP_EXTENSIONS)
                        or absolute_link.startswith("mailto:")
                        or "javascript:void" in absolute_link
                    ):
                        continue

                    enqueue_if_valid(absolute_link)

            except PlaywrightTimeoutError as e:
                self.logger.warning(f"Timeout on {normalized_url}: {e}")
                if normalized_url not in failed_urls:
                    failed_urls.add(normalized_url)
                    backoff = 2 * len(failed_urls)
                    self.logger.info(f"Restarting browser after {backoff}s delay...")
                    time.sleep(backoff)
                    self.restart_context()
                    queue.append((url, depth))
                else:
                    self.logger.warning("Already retried once, skipping permanently.")
                continue

            # === Catch-All Error Handling ===
            except Exception as e:
                self.logger.error(f"Unexpected error on {normalized_url}: {e}")
                continue

        return list(visited_subpages)

    def filter_career_pages(
        self,
        pages: set[str],
        scope: Literal["internal", "external", "all"] = "all",
    ) -> List[str]:
        """Ask the LLM to identify career/job listing pages.

        Args:
            pages: List of URLs to evaluate.
            scope: "internal" for company domain pages,
                "external" for third-party sites,
                "all" for mixed or generic filtering.
        """

        # --- Choose the right prompt based on scope
        if scope == "internal":
            prompt = get_filter_internal_career_pages_prompt(self.company_name, pages)
            context = "internal career pages"
        elif scope == "external":
            prompt = get_filter_external_career_pages_prompt(self.company_name, pages)
            context = "external career pages"
        else:  # "all"
            prompt = get_filter_career_pages_prompt(pages)
            context = "job listing pages"

        messages = [
            {
                "role": "system",
                "content": "You are an expert AI assistant helping to identify job listing/career pages.",
            },
            {"role": "user", "content": prompt},
        ]

        # --- Call the LLM (with retry + cleanup)
        result_structured = call_llm_structured(
            llm_client=self.llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.logger,
            max_tokens=1024,
            temperature=0.0,
            retry=True,
            pydantic_model=CareerPagesResponse,
        )

        # --- Handle invalid/empty response
        if not result_structured:
            self.logger.warning(f"LLM returned invalid or empty JSON for {context}.")
            return []

        # --- Validate with Pydantic
        try:
            validated = CareerPagesResponse.model_validate(result_structured)
            return validated.career_pages or []
        except Exception as e:
            self.logger.error(f"Validation failed for {context}: {e}")
            return []

    def identify_job_listing_pages(self, urls: set[str], retries: int = 1) -> List[str]:
        """
        Checks which URLs are job listing pages using an LLM.
        Uses Playwright to fetch HTML content before analysis.
        """

        job_listing_pages: List[str] = []

        for url in urls:
            self.logger.info(f"Testing job listing page URL: {url}")

            attempt = 0
            text_content = None

            # --- Attempt to fetch page content with retries
            while attempt <= retries:

                try:
                    self.send_heartbeat_if_needed()

                    self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    self.page.wait_for_load_state("networkidle", timeout=10000)

                    time.sleep(2)

                    self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                    html_content = self.page.content()
                    soup = BeautifulSoup(html_content, "html.parser")

                    # Remove irrelevant tags
                    for tag in soup(["script", "style", "meta", "svg"]):
                        tag.decompose()

                    text_content = self.extract_structured_text(
                        soup, url, skip_existing_jobs=False
                    )

                    break

                except PlaywrightTimeoutError as e:
                    self.logger.warning(
                        f"Timeout on attempt {attempt + 1} for {url}: {e}"
                    )
                    if attempt < retries:
                        self.logger.info("Restarting browser and retrying...")
                        self.restart_context()
                        attempt += 1
                        continue
                    else:
                        self.logger.error("Retry limit reached. Skipping this URL.")
                        break

                except Exception as e:
                    self.logger.error(f"Unexpected error loading {url}: {e}")
                    break

            # --- Skip if page failed to load
            if not text_content:
                continue

            # --- Build prompts for LLM
            system_prompt, user_prompt = get_identify_career_page_prompt(text_content)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # --- Use shared LLM helper with auto-cleaning JSON handling
            result_structured = call_llm_structured(
                llm_client=self.llm_client,
                model=LLM_MODEL,
                messages=messages,
                logger=self.logger,
                max_tokens=32,
                temperature=0.0,
                retry=True,
                pydantic_model=IsJobListingPageResponse,
            )

            if not result_structured:
                self.logger.warning(f"No valid JSON response from LLM for {url}")
                continue

            # --- Validate response with Pydantic
            try:
                validated = IsJobListingPageResponse.model_validate(result_structured)
            except Exception as e:
                self.logger.error(f"Validation failed for {url}: {e}")
                continue

            # --- Final decision
            if validated.is_job_listing_page == "yes":
                job_listing_pages.append(url)
                self.logger.info(f"Identified as job listing page: {url}")
            else:
                self.logger.info(f"Not a job listing page: {url}")

        return job_listing_pages

    def find_internal_career_pages(self) -> List[str]:
        # --- Crawl the main site and collect all visited URLs
        main_visited_pages = self.crawl_site_depth(self.base_url)

        # --- Prepare container for deduplicated relative paths
        #     We reduce redundancy by normalizing and trimming duplicate base paths
        deduped_main_paths = set()

        root_parsed = urlparse(self.base_url)  # https://careers.example.com/fr
        base_prefix = root_parsed.path.rstrip("/")  # "/fr"

        for url in main_visited_pages:
            url = url.rstrip("/")
            if url == self.base_url:
                continue
            parsed = urlparse(url)  # netloc (domain) + path (after domain)
            if parsed.netloc == root_parsed.netloc and parsed.path:
                # remove base prefix (/fr) so LLM sees clean paths like "/jobs"
                if parsed.path.startswith(base_prefix):
                    relative_path = parsed.path[len(base_prefix) :].rstrip("/") or "/"
                    deduped_main_paths.add(relative_path)

        self.logger.info("Step 2: Identifying Internal Career Pages via LLM...")

        # --- Ask LLM to identify which internal paths are career pages
        internal_pages_filtered = self.filter_career_pages(
            deduped_main_paths, "internal"
        )

        internal_career_pages = set()

        # --- Convert filtered paths to full URLs
        if internal_pages_filtered:
            for path_or_url in internal_pages_filtered:
                path_or_url = path_or_url.strip()
                # --- Ensure we have absolute URLs
                if path_or_url.startswith("http://") or path_or_url.startswith(
                    "https://"
                ):
                    full_url = path_or_url.rstrip("/")
                else:
                    full_url = urljoin(self.base_url + "/", path_or_url.lstrip("/"))
                internal_career_pages.add(full_url)

        # --- Always include the base URL itself as a possible career page
        internal_career_pages.add(self.base_url)

        self.logger.info(
            f"Internal Career Pages Identified Step 1: {internal_career_pages}"
        )

        # --- Ask LLM to identify which internal career pages are job listing pages (vs job detail pages)
        internal_job_listing_pages = self.identify_job_listing_pages(
            internal_career_pages
        )

        # --- Filter out blocked or irrelevant domains (LinkedIn, Indeed, etc.)
        internal_job_listing_pages = [
            url
            for url in internal_job_listing_pages
            if not any(urlparse(url).netloc.endswith(root) for root in blocked_domains)
        ]

        self.logger.info(
            f"Job Listing Pages Identified on Internal Site Step 1: {internal_job_listing_pages}"
        )

        # --- Re-crawl internal job listing pages one level deeper
        #     This helps discover job listings that may live under nested subpages
        self.logger.info("Re-crawling Internal Job Listing Pages One Level Deeper...")

        expanded_paths_internal = set()
        root_parsed = urlparse(self.base_url)
        base_prefix = root_parsed.path

        for job_page_url in internal_job_listing_pages:
            if job_page_url != self.base_url:
                subpages = self.crawl_site_path_prefix_only(job_page_url, max_depth=1)
                for sub_url in subpages:
                    parsed = urlparse(sub_url)
                    if parsed.netloc == root_parsed.netloc:
                        if parsed.path.startswith(base_prefix):
                            relative_path = (
                                parsed.path[len(base_prefix) :].rstrip("/") or "/"
                            )
                            expanded_paths_internal.add(relative_path)
            else:
                parsed = urlparse(job_page_url)
                relative_path = parsed.path[len(base_prefix) :].rstrip("/") or "/"
                expanded_paths_internal.add(relative_path)

        self.logger.info(
            f"Asking LLM Again for Deeper Job Listing Pages ({len(expanded_paths_internal)} paths)..."
        )

        deeper_internal_pages_filtered = self.filter_career_pages(
            expanded_paths_internal, "internal"
        )

        deeper_career_pages_internal = set()

        if deeper_internal_pages_filtered:
            for path_or_url in deeper_internal_pages_filtered:
                path_or_url = path_or_url.strip()
                if path_or_url.startswith("http://") or path_or_url.startswith(
                    "https://"
                ):
                    full_url = path_or_url.rstrip("/")
                else:
                    full_url = urljoin(self.base_url + "/", path_or_url.lstrip("/"))
                deeper_career_pages_internal.add(full_url)

        self.logger.info(
            f"Deeper Internal Career Pages Identified: {deeper_career_pages_internal}"
        )
        self.logger.info(
            f"Identifying Deeper Internal Job Listing Pages ({len(deeper_career_pages_internal)})..."
        )

        deeper_job_pages = self.identify_job_listing_pages(deeper_career_pages_internal)

        deeper_job_pages = [
            url
            for url in deeper_job_pages
            if not any(urlparse(url).netloc.endswith(root) for root in blocked_domains)
        ]

        # --- Merge results with previous internal job listing pages
        internal_job_listing_pages.extend(deeper_job_pages)

        # --- Deduplicate URLs
        internal_job_listing_pages = list(set(internal_job_listing_pages))

        # --- Remove query strings and fragments, keeping only one clean version per base URL
        #     Example:
        #       Input:
        #         ["https://careers.company.com/jobs?page=1", "https://careers.company.com/jobs?page=2"]
        #       Output:
        #         ["https://careers.company.com/jobs"]
        #       → Keeps the shortest, cleanest base URL version
        internal_job_listing_pages = self.deduplicate_by_base_url(
            internal_job_listing_pages
        )

        return internal_job_listing_pages

    def find_external_career_pages(self) -> List[str]:

        self.logger.info("Step 3: Identifying External Career Pages via LLM...")

        self.logger.info(
            f"2 Filtered External Urls found in website: {self.external_urls}"
        )

        # --- Filter out blocked external URLs (convert to set for uniqueness)
        filtered_external_urls: set[str] = {
            url
            for url in self.external_urls
            if not any(urlparse(url).netloc.endswith(root) for root in blocked_domains)
        }

        self.logger.info(
            f"Filtered External Urls found in website: {filtered_external_urls}"
        )

        # --- Call the LLM to classify external URLs as valid career pages
        external_pages_filtered = self.filter_career_pages(
            filtered_external_urls, "external"
        )

        # --- Initialize containers for deduplicated domains and URLs
        external_career_pages_roots = set()
        external_career_pages_not_modified = set()

        # --- Process valid external URLs returned by the LLM
        if external_pages_filtered:
            for url in external_pages_filtered:
                parsed_url = urlparse(url)
                domain = f"{parsed_url.scheme}://{parsed_url.netloc}".rstrip("/")
                domain_parts = parsed_url.netloc.split(".")

                if not any(
                    ".".join(domain_parts[i:]) in blocked_domains
                    for i in range(len(domain_parts) - 1)
                ):
                    external_career_pages_roots.add(domain)
                    external_career_pages_not_modified.add(url.strip("/"))

        # --- Remove any overlap between external and internal job listing pages
        external_career_pages_roots = external_career_pages_roots - set(
            self.internal_job_listing_pages
        )
        external_career_pages_not_modified = external_career_pages_not_modified - set(
            self.internal_job_listing_pages
        )

        self.logger.info(
            f"External Career Pages Roots Identified : {external_career_pages_roots}"
        )

        self.logger.info(
            f"External Career Pages Not Modified Identified : {external_career_pages_not_modified}"
        )

        external_career_pages_not_modified = self.keep_only_roots(
            external_career_pages_not_modified
        )

        self.logger.info(
            f"External Career Pages Not Modified Identified Shortest Path : {external_career_pages_not_modified}"
        )

        self.logger.info(f"Step 4: Crawling External Career Site")

        external_job_listing_pages = []

        for root_url in external_career_pages_not_modified:

            self.logger.info(f"Crawling External Career Site Not modified: {root_url}")

            # --- Crawl the external site to collect all subpages
            external_visited_pages = self.crawl_site_path_prefix_only(root_url)

            # --- Ensure the root URL itself is included
            external_visited_pages.append(root_url)

            # --- Initialize a set to store deduplicated relative paths
            deduped_paths = set()
            root_parsed = urlparse(root_url)
            base_prefix = root_parsed.path.rstrip("/")

            # --- Normalize and deduplicate all discovered URLs
            for url in external_visited_pages:
                parsed = urlparse(url)
                if parsed.netloc == root_parsed.netloc:
                    if parsed.path.startswith(base_prefix):
                        relative_path = (
                            parsed.path[len(base_prefix) :].rstrip("/") or "/"
                        )
                        deduped_paths.add(relative_path)

            self.logger.info(
                f"Identifying External Job Pages from {len(deduped_paths)} paths via LLM..."
            )

            pages_filtered = self.filter_career_pages(deduped_paths, "all")

            # --- Convert relative paths returned by the LLM into full absolute URLs
            pages_filtered_full = set(
                urljoin(root_url + "/", path.lstrip("/")) for path in pages_filtered
            )

            pages_filtered_full.add(root_url)

            all_identified = self.identify_job_listing_pages(pages_filtered_full)

            all_identified = [
                url
                for url in all_identified
                if not any(
                    urlparse(url).netloc.endswith(root) for root in blocked_domains
                )
            ]

            # --- Filter out blocked domains (aggregators like LinkedIn, Indeed, etc.)
            all_identified = self.deduplicate_by_base_url(all_identified)

            # --- Store the identified job listing URLs
            external_job_listing_pages.extend(all_identified)

            self.logger.info(f"Job Pages Identified External: {all_identified}")

        return external_job_listing_pages

    def save_db_job_listing_pages(self) -> int:
        """Save scraping results into the database.
        Returns:
            int: 1 if the update succeeded, raises Exception otherwise.
        """

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                try:
                    external_job_listing_pages: Optional[List[str]] = (
                        self.external_job_listing_pages or None
                    )
                    internal_job_listing_pages: Optional[List[str]] = (
                        self.internal_job_listing_pages or None
                    )
                    emails: Optional[List[str]] = list(self.emails) or None

                    cur.execute(
                        """
                        UPDATE companies
                        SET emails = %s, 
                            external_job_listing_pages = %s, 
                            internal_job_listing_pages = %s
                        WHERE id = %s
                        """,
                        (
                            emails,
                            external_job_listing_pages,
                            internal_job_listing_pages,
                            self.company_id,
                        ),
                    )

                    conn.commit()

                    return 1

                except Exception as e:
                    conn.rollback()
                    self.logger.error(
                        f"Database error for company {self.company_name}: {e}"
                    )
                    raise

    def __call__(self) -> JobListingsResult:
        """Starts the scraping process."""

        self.logger.info("Step 1: Crawling Main Website...")

        # --- Filter the internal career pages
        self.internal_job_listing_pages = self.find_internal_career_pages()

        self.logger.info(
            f"Final Job Pages Identified on Internal Site: {self.internal_job_listing_pages}"
        )

        self.external_job_listing_pages = self.find_external_career_pages()

        self.logger.info(
            f"Final External Pages Identified: {self.external_job_listing_pages}"
        )

        self.clean_contexts_playwright()

        self.save_db_job_listing_pages()

        return {
            "website": self.base_url,
            "internal_job_listing_pages": self.internal_job_listing_pages,
            "external_job_listing_pages": self.external_job_listing_pages,
            "emails": self.emails,
            "containers_html": {},
        }
