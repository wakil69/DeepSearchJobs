import random
import time

from playwright_stealth import Stealth  # type: ignore
from playwright.async_api import Browser, BrowserContext, Page, Route, Request
from typing import Optional, List, Tuple, Dict, Any
from worker.constants import PROXIES, MEDIA_EXTENSIONS, BLOCKED_ADS, USER_AGENTS

class BaseScraper:
    """Common functionality shared by all scrapers."""

    def __init__(
        self, company_id: int, company_name: str, session_logger, browser: Browser
    ):
        self.company_id = company_id
        self.company_name = company_name
        self.session_logger = session_logger
        self.browser = browser
        self.last_heartbeat = time.time()
        
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def get_page(self) -> Page:
        
        assert self.page is not None 
        
        return self.page 
    
    def get_random_proxy(self, proxies: List[str]) -> Optional[dict]:
        """Return a random proxy config dict compatible with Playwright."""
        if not proxies:
            return None

        proxy_str = random.choice(proxies)
        self.session_logger.info(f"Using proxy: {proxy_str}")

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
    ):
        """Intercept and block unwanted requests (media + ads)."""
        url = request.url
        hostname = ""

        try:
            hostname = url.split("/")[2]
        except Exception:
            pass

        # Block media files
        if any(url.lower().endswith(ext.replace("*", "")) for ext in MEDIA_EXTENSIONS):
            self.session_logger.debug(f"🖼️ Blocked media: {url}")
            return route.abort()

        # Block ad/tracker domains
        if any(domain in hostname for domain in BLOCKED_ADS):
            self.session_logger.debug(f"🛑 Blocked ad/tracker: {hostname}")
            return route.abort()

        return route.continue_()

    async def create_context_with_proxy(self) -> Tuple[BrowserContext, Page]:
        """Create a new browser context using a random user agent and proxy (if provided)."""
        context_options: Dict[str, Any] = {
            "user_agent": random.choice(USER_AGENTS),
            "viewport": {"width": 1920, "height": 1080},
            "locale": random.choice(["en-US", "en-GB", "fr-FR", "de-DE"]),
            "java_script_enabled": True,
        }

        proxy = self.get_random_proxy(PROXIES)
        if proxy:
            context_options["proxy"] = proxy

        context = await self.browser.new_context(**context_options)
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
    
        page = await context.new_page()

        await context.route(
            "**/*",
            lambda route, request: self.intercept_requests(
                route, request
            ),
        )

        self.context, self.page = context, page

        return context, page

    async def clean_contexts_playwright(self):
        try:
            if getattr(self, "page", None) and self.page:
                await self.page.close(run_before_unload=False)

            if getattr(self, "context", None) and self.context:
                await self.context.close()

            self.page = None
            self.context = None
            self.session_logger.info("Playwright contexts closed cleanly.")
        except Exception as e:
            self.session_logger.warning(f"Error while cleaning Playwright: {e}")

    async def restart_context(self) -> None:
        """Fully restarts the Playwright browser and context."""
        await self.clean_contexts_playwright()
        await self.create_context_with_proxy()
        self.session_logger.info("Playwright context restarted successfully.")

  