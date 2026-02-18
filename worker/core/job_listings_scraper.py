import re
import random
import asyncio

from worker.constants.blocked_domains import BLOCKED_DOMAINS
from collections import deque, defaultdict
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Browser
from worker.types.worker_types import (
    CareerPagesResponse,
    IsJobListingPageResponse,
    JobListingsResult,
)
from typing import List, DefaultDict, Literal
from worker.constants.prompts import (
    get_filter_internal_career_pages_prompt,
    get_filter_external_career_pages_prompt,
    get_filter_career_pages_prompt,
    get_identify_career_page_prompt,
)
from worker.utils.llm_utils import call_llm_structured
from worker.base_scraper import BaseScraper
from worker.core.db_ops import DBOps
from worker.utils.url_utils import same_domain, deduplicate_by_base_url, keep_only_roots
from worker.dependencies import llm_client, LLM_MODEL
from worker.utils.text_utils import get_emails, extract_structured_text, extract_visible_text

class FetchJobsListingsScraper(BaseScraper):
    def __init__(
        self,
        base_url: str,
        company_id: int,
        company_name: str,
        session_logger,
        browser: Browser,
        timeout=20000,
    ):
        super().__init__(company_id, company_name, session_logger, browser)
        self.base_url = base_url.rstrip("/")
        self.external_job_listing_pages: List[str] = []
        self.internal_job_listing_pages: List[str] = []
        self.external_urls: set[str] = set()
        self.emails: set[str] = set()
        self.timeout = timeout

        self.db_ops = DBOps(session_logger)

   
    async def crawl_site_depth(self, base_url: str, max_depth: int = 1) -> List[str]:
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
            is_same_domain = same_domain(link_url, self.base_url)
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
            url, depth = queue.popleft()
            normalized_url = url.split("#")[0]

            # --- Pattern rate limiting ---
            pattern_keys = get_pattern_keys(normalized_url, depth=2)
            if any(pattern_counts[k] >= MAX_PER_PATTERN for k in pattern_keys):
                self.session_logger.info(
                    f"⏭️ Skipping {normalized_url}, pattern cap reached"
                )
                continue
            for k in pattern_keys:
                pattern_counts[k] += 1

            # --- Already visited or too deep ---
            if normalized_url in visited_subpages or depth > max_depth:
                continue

            assert self.page is not None, "Page not initialized"

            try:

                await self.page.goto(
                    normalized_url, timeout=self.timeout, wait_until="load"
                )

                await self.page.wait_for_timeout(random.uniform(1000, 3000))

                normalized_url = self.page.url  # handle redirects

                if first_iteration:
                    self.base_url = normalized_url.rstrip("/")
                    self.session_logger.info(f"🔄 Base URL updated to: {self.base_url}")
                    first_iteration = False

                self.session_logger.info(f"Visited Url: {normalized_url}")

                visited_subpages.add(normalized_url)

                await self.page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )

                await self.page.wait_for_timeout(
                    random.uniform(1000, 3000)
                )  # human-like delay

                # === Extract content ===
                html_content = await self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                # Extract and store any visible emails
                visible_text = extract_visible_text(html_content)
                new_emails = get_emails(visible_text)
                if new_emails:
                    self.session_logger.info(f"Emails found: {new_emails}")
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
                self.session_logger.warning(f"Timeout on {normalized_url}: {e}")
                if normalized_url not in failed_urls:
                    failed_urls.add(normalized_url)
                    backoff = 2 * len(failed_urls)
                    self.session_logger.info(
                        f"Restarting browser and retrying after {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    await self.restart_context()
                    queue.append((url, depth))
                else:
                    self.session_logger.warning(
                        "Already retried once, skipping permanently."
                    )
                continue

            # === General exception handling ===
            except Exception as e:
                self.session_logger.error(
                    f"⚠️ Unexpected error on {normalized_url}: {e}"
                )
                continue

        # === Return crawled pages ===
        return list(visited_subpages)

    async def crawl_site_path_prefix_only(
        self, base_url: str, max_depth=1
    ) -> List[str]:
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
            url, depth = queue.popleft()
            normalized_url = url.split("#")[0]

            if normalized_url in visited_subpages or depth > max_depth:
                continue

            try:
                assert self.page is not None, "Page not initialized"

                await self.page.goto(
                    normalized_url, timeout=self.timeout, wait_until="load"
                )

                await self.page.wait_for_timeout(random.uniform(1000, 3000))

                self.session_logger.info(f"Visited Url: {self.page.url}")

                await self.page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )

                visited_subpages.add(normalized_url)

                # === Parse content ===
                html_content = await self.page.content()
                soup = BeautifulSoup(html_content, "html.parser")

                # === Extract and store emails ===
                visible_text = extract_visible_text(html_content)
                new_emails = get_emails(visible_text)
                if new_emails:
                    self.session_logger.info(f"Emails found: {new_emails}")
                    self.emails.update(new_emails)

                # === Helper function for enqueueing internal URLs ===
                def enqueue_if_valid(link_url: str):
                    """Enqueue a same-domain, prefix-matching URL if depth allows."""
                    is_same_domain = same_domain(link_url, base_url)
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
                self.session_logger.warning(f"Timeout on {normalized_url}: {e}")
                if normalized_url not in failed_urls:
                    failed_urls.add(normalized_url)
                    backoff = 2 * len(failed_urls)
                    self.session_logger.info(
                        f"Restarting browser after {backoff}s delay..."
                    )
                    await asyncio.sleep(backoff)
                    await self.restart_context()
                    queue.append((url, depth))
                else:
                    self.session_logger.warning(
                        "Already retried once, skipping permanently."
                    )
                continue

            # === Catch-All Error Handling ===
            except Exception as e:
                self.session_logger.error(f"Unexpected error on {normalized_url}: {e}")
                continue

        return list(visited_subpages)

    async def filter_career_pages(
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
        result_structured = await call_llm_structured(
            llm_client=llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.session_logger,
            max_tokens=1024,
            temperature=0.0,
            retry=True,
            pydantic_model=CareerPagesResponse,
        )

        # --- Handle invalid/empty response
        if not result_structured:
            self.session_logger.warning(
                f"LLM returned invalid or empty JSON for {context}."
            )
            return []

        # --- Validate with Pydantic
        try:
            validated = CareerPagesResponse.model_validate(result_structured)
            return validated.career_pages or []
        except Exception as e:
            self.session_logger.error(f"Validation failed for {context}: {e}")
            return []

    async def identify_job_listing_pages(
        self, urls: set[str], retries: int = 1
    ) -> List[str]:
        """
        Checks which URLs are job listing pages using an LLM.
        Uses Playwright to fetch HTML content before analysis.
        """

        job_listing_pages: List[str] = []

        for url in urls:
            self.session_logger.info(f"Testing job listing page URL: {url}")

            attempt = 0
            text_content = None

            # --- Attempt to fetch page content with retries
            while attempt <= retries:

                try:

                    assert self.page is not None, "Page not initialized"

                    await self.page.goto(url, timeout=self.timeout, wait_until="load")

                    await self.page.wait_for_timeout(random.uniform(1000, 3000))

                    await self.page.evaluate(
                        "window.scrollTo(0, document.body.scrollHeight)"
                    )

                    html_content = await self.page.content()
                    soup = BeautifulSoup(html_content, "html.parser")

                    # Remove irrelevant tags
                    for tag in soup(["script", "style", "meta", "svg"]):
                        tag.decompose()

                    text_content = extract_structured_text(
                        soup, url, skip_existing_jobs=False
                    )

                    break

                except PlaywrightTimeoutError as e:
                    self.session_logger.warning(
                        f"Timeout on attempt {attempt + 1} for {url}: {e}"
                    )
                    if attempt < retries:
                        self.session_logger.info("Restarting browser and retrying...")
                        await self.restart_context()
                        attempt += 1
                        continue
                    else:
                        self.session_logger.error(
                            "Retry limit reached. Skipping this URL."
                        )
                        break

                except Exception as e:
                    self.session_logger.error(f"Unexpected error loading {url}: {e}")
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
            result_structured = await call_llm_structured(
                llm_client=llm_client,
                model=LLM_MODEL,
                messages=messages,
                logger=self.session_logger,
                max_tokens=32,
                temperature=0.0,
                retry=True,
                pydantic_model=IsJobListingPageResponse,
            )

            if not result_structured:
                self.session_logger.warning(
                    f"No valid JSON response from LLM for {url}"
                )
                continue

            # --- Validate response with Pydantic
            try:
                validated = IsJobListingPageResponse.model_validate(result_structured)
            except Exception as e:
                self.session_logger.error(f"Validation failed for {url}: {e}")
                continue

            # --- Final decision
            if validated.is_job_listing_page == "yes":
                job_listing_pages.append(url)
                self.session_logger.info(f"Identified as job listing page: {url}")
            else:
                self.session_logger.info(f"Not a job listing page: {url}")

        return job_listing_pages

    async def find_internal_career_pages(self) -> List[str]:
        # --- Crawl the main site and collect all visited URLs
        main_visited_pages = await self.crawl_site_depth(self.base_url)

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

        self.session_logger.info("Step 2: Identifying Internal Career Pages via LLM...")

        # --- Ask LLM to identify which internal paths are career pages
        internal_pages_filtered = await self.filter_career_pages(
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

        self.session_logger.info(
            f"Internal Career Pages Identified Step 1: {internal_career_pages}"
        )

        # --- Ask LLM to identify which internal career pages are job listing pages (vs job detail pages)
        internal_job_listing_pages = await self.identify_job_listing_pages(
            internal_career_pages
        )

        # --- Filter out blocked or irrelevant domains (LinkedIn, Indeed, etc.)
        internal_job_listing_pages = [
            url
            for url in internal_job_listing_pages
            if not any(urlparse(url).netloc.endswith(root) for root in BLOCKED_DOMAINS)
        ]

        self.session_logger.info(
            f"Job Listing Pages Identified on Internal Site Step 1: {internal_job_listing_pages}"
        )

        # --- Re-crawl internal job listing pages one level deeper
        #     This helps discover job listings that may live under nested subpages
        self.session_logger.info(
            "Re-crawling Internal Job Listing Pages One Level Deeper..."
        )

        expanded_paths_internal = set()
        root_parsed = urlparse(self.base_url)
        base_prefix = root_parsed.path

        for job_page_url in internal_job_listing_pages:
            if job_page_url != self.base_url:
                subpages = await self.crawl_site_path_prefix_only(
                    job_page_url, max_depth=1
                )
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

        self.session_logger.info(
            f"Asking LLM Again for Deeper Job Listing Pages ({len(expanded_paths_internal)} paths)..."
        )

        deeper_internal_pages_filtered = await self.filter_career_pages(
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

        self.session_logger.info(
            f"Deeper Internal Career Pages Identified: {deeper_career_pages_internal}"
        )
        self.session_logger.info(
            f"Identifying Deeper Internal Job Listing Pages ({len(deeper_career_pages_internal)})..."
        )

        deeper_job_pages = await self.identify_job_listing_pages(
            deeper_career_pages_internal
        )

        deeper_job_pages = [
            url
            for url in deeper_job_pages
            if not any(urlparse(url).netloc.endswith(root) for root in BLOCKED_DOMAINS)
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
        internal_job_listing_pages = deduplicate_by_base_url(
            internal_job_listing_pages
        )

        return internal_job_listing_pages

    async def find_external_career_pages(self) -> List[str]:

        self.session_logger.info("Step 3: Identifying External Career Pages via LLM...")

        self.session_logger.info(
            f"2 Filtered External Urls found in website: {self.external_urls}"
        )

        # --- Filter out blocked external URLs (convert to set for uniqueness)
        filtered_external_urls: set[str] = {
            url
            for url in self.external_urls
            if not any(urlparse(url).netloc.endswith(root) for root in BLOCKED_DOMAINS)
        }

        self.session_logger.info(
            f"Filtered External Urls found in website: {filtered_external_urls}"
        )

        # --- Call the LLM to classify external URLs as valid career pages
        external_pages_filtered = await self.filter_career_pages(
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
                    ".".join(domain_parts[i:]) in BLOCKED_DOMAINS
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

        self.session_logger.info(
            f"External Career Pages Roots Identified : {external_career_pages_roots}"
        )

        self.session_logger.info(
            f"External Career Pages Not Modified Identified : {external_career_pages_not_modified}"
        )

        external_career_pages_not_modified = keep_only_roots(
            external_career_pages_not_modified
        )

        self.session_logger.info(
            f"External Career Pages Not Modified Identified Shortest Path : {external_career_pages_not_modified}"
        )

        self.session_logger.info(f"Step 4: Crawling External Career Site")

        external_job_listing_pages = []

        for root_url in external_career_pages_not_modified:

            self.session_logger.info(
                f"Crawling External Career Site Not modified: {root_url}"
            )

            # --- Crawl the external site to collect all subpages
            external_visited_pages = await self.crawl_site_path_prefix_only(root_url)

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

            self.session_logger.info(
                f"Identifying External Job Pages from {len(deduped_paths)} paths via LLM..."
            )

            pages_filtered = await self.filter_career_pages(deduped_paths, "all")

            # --- Convert relative paths returned by the LLM into full absolute URLs
            pages_filtered_full = set(
                urljoin(root_url + "/", path.lstrip("/")) for path in pages_filtered
            )

            pages_filtered_full.add(root_url)

            all_identified = await self.identify_job_listing_pages(pages_filtered_full)

            all_identified = [
                url
                for url in all_identified
                if not any(
                    urlparse(url).netloc.endswith(root) for root in BLOCKED_DOMAINS
                )
            ]

            # --- Filter out blocked domains (aggregators like LinkedIn, Indeed, etc.)
            all_identified = deduplicate_by_base_url(all_identified)

            # --- Store the identified job listing URLs
            external_job_listing_pages.extend(all_identified)

            self.session_logger.info(f"Job Pages Identified External: {all_identified}")

        return external_job_listing_pages

    async def __call__(self) -> JobListingsResult:
        """Starts the scraping process."""

        self.session_logger.info("Step 1: Crawling Main Website...")

        await self.create_context_with_proxy()

        # --- Filter the internal career pages
        self.internal_job_listing_pages = await self.find_internal_career_pages()

        self.session_logger.info(
            f"Final Job Pages Identified on Internal Site: {self.internal_job_listing_pages}"
        )

        self.external_job_listing_pages = await self.find_external_career_pages()

        self.session_logger.info(
            f"Final External Pages Identified: {self.external_job_listing_pages}"
        )

        await self.clean_contexts_playwright()

        await self.db_ops.save_db_job_listing_pages(
            company_name=self.company_name,
            company_id=self.company_id,
            external_job_listing_pages=self.external_job_listing_pages,
            internal_job_listing_pages=self.internal_job_listing_pages,
            emails=self.emails
        )

        return {
            "website": self.base_url,
            "internal_job_listing_pages": self.internal_job_listing_pages,
            "external_job_listing_pages": self.external_job_listing_pages,
            "emails": self.emails,
            "containers_html": {},
            "current_job_offers": set(),
        }
