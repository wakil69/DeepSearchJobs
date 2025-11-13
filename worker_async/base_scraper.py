import random
import time
import os
import re
import hashlib
import json

from playwright_stealth import Stealth  # type: ignore
from playwright.async_api import Browser, BrowserContext, Page, Route, Request
from openai import OpenAI
from dotenv import load_dotenv
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Optional, List, Tuple, Dict, Any
from worker_async.worker_types import Job
from bs4 import BeautifulSoup, Tag

load_dotenv()

LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")


user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
]


class BaseScraper:
    """Common functionality shared by all scrapers."""

    def __init__(
        self, company_id: int, company_name: str, logger, browser: Browser, ch
    ):
        self.company_id = company_id
        self.company_name = company_name
        self.logger = logger
        self.browser = browser
        self.ch = ch
        self.last_heartbeat = time.time()
        self.user_agents = user_agents

        self.llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    @staticmethod
    def load_json_list(file_name: str) -> list[str]:
        """Load a JSON list safely."""
        if os.path.exists(file_name):
            try:
                with open(file_name, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                print(f"❌ Error parsing {file_name}: {e}")
        return []

    @classmethod
    def load_proxies(cls) -> list[str]:
        return cls.load_json_list("proxies.json")

    @classmethod
    def load_media_extensions(cls) -> list[str]:
        return cls.load_json_list("media_extensions.json")

    @classmethod
    def load_blocked_ads(cls) -> list[str]:
        return cls.load_json_list("blocked_ads.json")

    @staticmethod
    def get_emails(text: str) -> set[str]:
        """Extracts and filters valid emails from the given text."""
        email_regex = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        possible_emails = set(re.findall(email_regex, text))
        valid_tlds = {
            "com",
            "org",
            "net",
            "edu",
            "gov",
            "eu",
            "br",
            "fr",
            "de",
            "es",
            "pl",
            "it",
            "uk",
            "ru",
            "in",
            "ch",
        }
        invalid_extensions = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff"}

        valid_emails = set()

        for email in possible_emails:
            domain_parts = email.split(".")
            tld = domain_parts[-1].lower()

            if tld not in invalid_extensions:
                valid_emails.add(email)

        return valid_emails

    @staticmethod
    def normalize_url(base: str, href: str, keep_query=False) -> Optional[str]:
        """Safely join href with base, correctly handling ../, mailto:, tel:, etc."""

        if not href:
            return None

        href = href.strip()
        if not href:
            return None

        if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            return href

        parsed = urlparse(base)
        path = parsed.path or "/"

        if not path.endswith("/") and "." not in path.split("/")[-1]:
            path += "/"

        clean_base = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

        if href.startswith("//"):
            href = parsed.scheme + ":" + href

        href = re.sub(r"^(\./|//)+", "", href)

        # for single page app like google jobs careers
        # Example: base='/jobs/results/' + href='jobs/results/123' → remove the repeated 'jobs/results'
        base_parts = [p for p in path.strip("/").split("/") if p]
        href_parts = [p for p in href.strip("/").split("/") if p]

        for i in range(len(base_parts)):
            subpath = "/".join(base_parts[i:])
            if href.startswith(subpath + "/") or href == subpath:
                href = href[len(subpath) :].lstrip("/")
                break

        result = urljoin(clean_base, href)

        if keep_query and parsed.query and result:
            if "?" in result:
                result += "&" + parsed.query
            else:
                result += "?" + parsed.query

        if result and result != "/":
            result = result.rstrip("/")

        return result

    @staticmethod
    def hash_page_content(text_content: str) -> str:
        """Creates a hash of the page content to detect duplicates."""
        return hashlib.md5(text_content.encode()).hexdigest()

    def get_random_proxy(self, proxies: List[str]) -> Optional[dict]:
        """Return a random proxy config dict compatible with Playwright."""
        if not proxies:
            return None

        proxy_str = random.choice(proxies)
        self.logger.info(f"Using proxy: {proxy_str}")

        # Handle both "username:password@host:port" and "host:port" formats
        if "@" in proxy_str:
            creds, server = proxy_str.split("@", 1)
            username, password = creds.split(":", 1)
            return {
                "server": f"http://{server}",
                "username": username,
                "password": password,
            }
        else:
            return {"server": f"http://{proxy_str}"}

    def intercept_requests(
        self,
        route: Route,
        request: Request,
        media_extensions: list[str],
        blocked_ads: list[str],
    ):
        """Intercept and block unwanted requests (media + ads)."""
        url = request.url
        hostname = ""

        try:
            hostname = url.split("/")[2]
        except Exception:
            pass

        # Block media files
        if any(url.lower().endswith(ext.replace("*", "")) for ext in media_extensions):
            self.logger.debug(f"🖼️ Blocked media: {url}")
            return route.abort()

        # Block ad/tracker domains
        if any(domain in hostname for domain in blocked_ads):
            self.logger.debug(f"🛑 Blocked ad/tracker: {hostname}")
            return route.abort()

        return route.continue_()

    async def create_context_with_proxy(self) -> Tuple[BrowserContext, Page]:
        """Create a new browser context using a random user agent and proxy (if provided)."""
        context_options: Dict[str, Any] = {
            "user_agent": random.choice(self.user_agents),
            "viewport": {"width": 1920, "height": 1080},
            "locale": random.choice(["en-US", "en-GB", "fr-FR", "de-DE"]),
            "java_script_enabled": True,
        }

        proxies = self.load_proxies()

        proxy = self.get_random_proxy(proxies)
        if proxy:
            context_options["proxy"] = proxy

        context = await self.browser.new_context(**context_options)
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
    
        page = await context.new_page()
        
        media_extensions = self.load_media_extensions()
        blocked_ads = self.load_blocked_ads()

        await context.route(
            "**/*",
            lambda route, request: self.intercept_requests(
                route, request, media_extensions, blocked_ads
            ),
        )

        self.context, self.page = context, page

        return context, page

    def send_heartbeat_if_needed(self, interval: int = 300) -> None:
        """Periodically send a RabbitMQ heartbeat to keep the connection alive."""
        if not self.ch:
            return
        try:
            if time.time() - self.last_heartbeat > interval:
                self.ch.connection.process_data_events()
                self.logger.info("Sent RabbitMQ heartbeat")
                self.last_heartbeat = time.time()
        except Exception as e:
            self.logger.warning(f"Heartbeat failed ({type(e).__name__}): {e}")

    async def clean_contexts_playwright(self):
        try:
            if getattr(self, "page", None) and self.page:
                await self.page.close(run_before_unload=False)

            if getattr(self, "context", None) and self.context:
                await self.context.close()

            self.page = None
            self.context = None
            self.logger.info("Playwright contexts closed cleanly.")
        except Exception as e:
            self.logger.warning(f"Error while cleaning Playwright: {e}")

    async def restart_context(self) -> None:
        """Fully restarts the Playwright browser and context."""
        await self.clean_contexts_playwright()
        await self.create_context_with_proxy()
        self.logger.info("Playwright context restarted successfully.")

    def extract_structured_text(
        self,
        soup: BeautifulSoup,
        url: str,
        job_offers: List[Job] = [],
        skip_existing_jobs: bool = True,
    ) -> str:
        """
        Extracts structured text content (headings, paragraphs, lists, tables, links)
        with associated hyperlinks.

        Args:
            soup (BeautifulSoup): Parsed HTML soup of the page.
            url (str): Current page URL for resolving relative links.
            skip_existing_jobs (bool): If True, skip links already in self.job_offers.

        Returns:
            str: A structured text representation (markdown-like), capped at 128k chars.
        """

        structured_content = []
        seen_links = set()

        verified_existing_jobs = [job["job_url"] for job in job_offers]

        def handle_link(link: Optional[str], text: str):
            """Decide whether to include a link based on known jobs."""
            if not link:
                return None
            if skip_existing_jobs and link in verified_existing_jobs:
                return None
            return text

        def get_associated_link(element):
            """Finds the nearest anchor link within or related to the element."""
            link = element.find("a", href=True)
            if link:
                link = self.normalize_url(url, link["href"])
                seen_links.add(link)
                return link
            return ""

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            link = get_associated_link(heading)
            if link:
                text = f"\n### {heading.get_text(strip=True)} ({link}) ###"
                result = handle_link(link, text)
                if result:
                    structured_content.append(result)

        for paragraph in soup.find_all("p"):
            link = get_associated_link(paragraph)
            if link:
                text = f"- {paragraph.get_text(strip=True)} ({link})"
                result = handle_link(link, text)
                if result:
                    structured_content.append(result)

        for ul in soup.find_all("ul"):
            if not isinstance(ul, Tag):
                continue
            items = []
            for li in ul.find_all("li"):
                if not isinstance(li, Tag):
                    continue
                link = li.find("a", href=True)
                if isinstance(link, Tag) and link.has_attr("href"):
                    link = self.normalize_url(url, str(link["href"]))
                    seen_links.add(link)
                    text = f"  • {li.get_text(strip=True)} ({link})"
                    result = handle_link(link, text)
                    if result:
                        items.append(result)
            if items:
                structured_content.append("\n".join(items))

        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            table_data = []
            for row in table.find_all("tr"):
                if not isinstance(row, Tag):
                    continue
                cells = []
                for td in row.find_all(["td", "th"]):
                    if not isinstance(td, Tag):
                        continue
                    link = td.find("a", href=True)
                    if isinstance(link, Tag) and link.has_attr("href"):
                        link = self.normalize_url(url, str(link["href"]))
                        seen_links.add(link)
                        text = f"{td.get_text(strip=True)} ({link})"
                        result = handle_link(link, text)
                        if result:
                            cells.append(result)
                if cells:
                    table_data.append(" | ".join(cells))
            if table_data:
                structured_content.append("\n".join(table_data))

        links = []
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = a.get("href")
            if not isinstance(href, str):
                continue
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
        if links:
            structured_content.append("\n### Links ###\n" + "\n".join(links))

        return "\n".join(structured_content)[:128000]
