import random
import asyncio
import pymupdf  # type: ignore
import pymupdf4llm  # type: ignore
import aiohttp
import aiofiles
import aiofiles.os
import numpy as np
import os
import uuid

from numpy.linalg import norm
from Levenshtein import ratio as levenshtein_ratio
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page
from worker.core.find_company_logo import FindCompanyLogo
from typing import Any, Optional, List, Dict, Tuple
from worker.constants.prompts import (
    get_extract_company_description_prompt,
    get_job_infos_prompt,
)
from worker.utils.llm_utils import call_llm_structured
from worker.types.worker_types import (
    CompanyDescriptionResponse,
    JobInfosExtractionResponse,
    Job,
)
from worker.dependencies import llm_client, LLM_MODEL, encoder_model
from worker.utils.text_utils import get_emails
from worker.core.post_process_jobs.constants import COUNTRY_REGION_DATA, BLOCKED_EXTENSIONS
from docx import Document
from pathlib import Path
from simhash import Simhash  # type: ignore

class PostProcessingJobs:
    def __init__(
        self,
        session_logger: Any,
        emails: set[str],
        company_name: str,
        company_id: int,
        job_offers: List[Job],
        old_job_offers: List[str],
        new_job_offers: List[Job],
        current_job_offers: set[str],
        company_description: Optional[str],
        timeout: int = 30000,
    ):
        self.session_logger = session_logger
        self.timeout = timeout
        self.emails = emails
        self.company_name = company_name
        self.company_id = company_id
        self.job_offers = job_offers
        self.old_job_offers = old_job_offers
        self.new_job_offers = new_job_offers
        self.current_job_offers = current_job_offers
        self.company_description = company_description

        self.find_company_logo = FindCompanyLogo(
            self.session_logger, self.company_name, self.company_id
        )

    @staticmethod
    def find_best_match_country(
        input_country: Optional[str], score_threshold: int = 85
    ) -> str | None:
        """
        Finds the closest matching country name using Levenshtein distance.

        :param input_country: The country name to match.
        :param score_threshold: The minimum score threshold for a valid match (0-100).
        :return: Best-matching country name or None.
        """
        if not input_country or not isinstance(input_country, str):
            return None

        countries = [c["countryName"] for c in COUNTRY_REGION_DATA]

        # Calculate similarity scores for all countries
        matches = [
            (country, levenshtein_ratio(input_country.lower(), country.lower()) * 100)
            for country in countries
        ]

        # Find the best match
        best_match, best_score = max(matches, key=lambda x: x[1])

        return best_match if best_score >= score_threshold else None

    @staticmethod
    async def is_pdf_url_valid(url: str, timeout: int = 10) -> bool:
        """Check if a PDF or file URL returns HTTP 200 (fast check)."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            timeout_obj = aiohttp.ClientTimeout(total=timeout)

            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.head(url, allow_redirects=True, headers=headers) as response:
                    if response.status == 405:
                        async with session.get(url, allow_redirects=True, headers=headers) as get_response:
                            return get_response.status == 200
                    return response.status == 200

        except Exception:
            return False

    @staticmethod
    def find_best_match_region(
        input_region: Optional[str],
        country_name: Optional[str],
        score_threshold: int = 85,
    ) -> str | None:
        """
        Finds the closest matching region name within a given country using Levenshtein distance.

        :param input_region: The region name to match.
        :param country_name: The country the region belongs to.
        :param score_threshold: The minimum score threshold for a valid match (0-100).
        :return: Best-matching region name or None.
        """
        if not input_region or not country_name:
            return None

        if not isinstance(input_region, str) or not isinstance(country_name, str):
            return None

        country = next(
            (c for c in COUNTRY_REGION_DATA if c["countryName"] == country_name), None
        )

        if not country or not country.get("regions"):
            return None

        region_names = [region["name"] for region in country["regions"]]

        # Calculate similarity scores for all regions
        matches = [
            (region, levenshtein_ratio(input_region.lower(), region.lower()) * 100)
            for region in region_names
        ]

        # Find the best match
        best_match, best_score = max(matches, key=lambda x: x[1])

        return best_match if best_score >= score_threshold else None

    @staticmethod
    async def job_vector_embedding(job_title: str) -> Optional[np.ndarray]:
        """Return the L2-normalized embedding for a job title, or None if invalid."""
        embedding = await asyncio.to_thread(
            encoder_model.encode, job_title, convert_to_tensor=True
        )
        embedding_np = embedding.cpu().numpy()
        norm_val = norm(embedding_np)

        if not np.isfinite(norm_val) or norm_val == 0:
            return None

        return embedding_np / norm_val

    @staticmethod
    def replace_israel(country):
        """Normalize country name: replace 'Israel' with 'Occupied Palestine'."""
        return "Occupied Palestine" if country == "Israel" else country

    async def extract_job_description_file(
        self,
        url: str,
        MAX_PARAGRAPHS_DOCX=500,
        MAX_FILE_SIZE_MB: int = 50,
    ) -> tuple[Optional[str], Optional[int]]:
        """Download and extract text content from a PDF or DOCX job description file, returning the text and its SimHash."""

        markdown: str | list[str]
        content: str | None = None

        url_lower = url.lower()
        max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

        # ---------- PDF ----------
        if url_lower.endswith(".pdf"):
            tmp_filename = f"{uuid.uuid4()}.pdf"
            tmp_path = os.path.join("/tmp", tmp_filename)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url_lower) as response:
                        response.raise_for_status()

                        content_length = response.headers.get("Content-Length")
                        if content_length and int(content_length) > max_bytes:
                            return None, None

                        size = 0
                        async with aiofiles.open(tmp_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                size += len(chunk)
                                if size > max_bytes:
                                    return None, None
                                await f.write(chunk)

                result = await asyncio.to_thread(
                    pymupdf4llm.to_markdown, tmp_path, page_chunks=True
                )

                if not isinstance(result, list):
                    raise TypeError("Expected list of page chunks")

                pages: List[Dict[str, Any]] = result

                pages_text: List[str] = [page.get("text", "") for page in pages]

                content = "\n\n".join(pages_text)

            finally:
                if await aiofiles.os.path.exists(tmp_path):
                    await aiofiles.os.remove(tmp_path)

        # ---------- DOCX ----------
        elif url_lower.endswith(".docx"):
            tmp_filename = f"{uuid.uuid4()}.docx"
            tmp_path = os.path.join("/tmp", tmp_filename)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url_lower) as response:
                        response.raise_for_status()

                        content_length = response.headers.get("Content-Length")
                        if content_length and int(content_length) > max_bytes:
                            return None, None

                        size = 0
                        async with aiofiles.open(tmp_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                size += len(chunk)
                                if size > max_bytes:
                                    return None, None
                                await f.write(chunk)

                docx_doc = await asyncio.to_thread(Document, tmp_path)

                paragraphs = [
                    p.text.strip()
                    for p in docx_doc.paragraphs[:MAX_PARAGRAPHS_DOCX]
                    if p.text and p.text.strip()
                ]

                content = "\n\n".join(paragraphs).strip()

            finally:
                if await aiofiles.os.path.exists(tmp_path):
                    await aiofiles.os.remove(tmp_path)

        # ---------- Unsupported ----------
        else:
            return None, None

        # ---------- SimHash + Emails ----------
        simhash_value: Optional[int] = None

        if content and len(content) > 50:
            tokens = content.split()
            simhash_obj = await asyncio.to_thread(Simhash, tokens)
            simhash = simhash_obj.value

            if simhash is None:
                self.session_logger.warning("Simhash returned None, skipping hash computation")
            else:
                simhash_value = int(simhash & ((1 << 63) - 1))
        else:
            self.session_logger.info("Job description too short (<50 chars), skipping SimHash")

        if content and (new_emails := get_emails(content)):
            self.session_logger.info(f"Emails found: {new_emails}")
            self.emails.update(new_emails)

        return content, simhash_value

    async def extract_job_description(
        self, page: Page, url: str, retries=1
    ) -> Optional[Tuple[str, Optional[int]]]:
        """Extract a job description text from a job description page."""
        try:

            await page.goto(url, timeout=self.timeout, wait_until="load")

            await page.wait_for_timeout(random.uniform(1000, 3000))

            html_content = await page.content()
            soup = await asyncio.to_thread(BeautifulSoup, html_content, "lxml")

            job_description = soup.body or soup

            for tag in job_description(["script", "style", "meta", "noscript", "svg"]):
                tag.decompose()

            text_job_description = job_description.get_text(separator="\n", strip=True)

            simhash_value: Optional[int] = None

            if len(text_job_description) > 50:
                tokens = text_job_description.split()
                simhash_obj = await asyncio.to_thread(Simhash, tokens)
                simhash = simhash_obj.value

                if simhash is None:
                    self.session_logger.warning(
                        "Simhash returned None, skipping hash computation"
                    )
                else:
                    # Force signed 63-bit integer (PostgreSQL-safe)
                    simhash_value = int(simhash & ((1 << 63) - 1))
            else:
                self.session_logger.info(
                    "Job description too short (<50 chars), skipping SimHash"
                )

            if new_emails := get_emails(text_job_description):
                self.session_logger.info(f"Emails found: {new_emails}")
                self.emails.update(new_emails)

            return text_job_description, simhash_value

        except PlaywrightTimeoutError as e:
            self.session_logger.warning(f"Timeout loading {url}: {e}")
        except Exception as e:
            self.session_logger.warning(f"Playwright failure at {url}: {e}")

        if retries > 0:
            self.session_logger.info("Retrying...")
            return await self.extract_job_description(page, url, retries=retries - 1)

        self.session_logger.error(
            f"Failed to extract job description from {url} after retries."
        )
        return None

    async def extract_company_description(self, job_description_text: str) -> Optional[str]:
        """Extract a concise company description from a job description using the LLM."""
        system_prompt, user_prompt = get_extract_company_description_prompt(
            job_description_text
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        result_structured = await call_llm_structured(
            llm_client=llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.session_logger,
            max_tokens=256,
            temperature=0.0,
            retry=True,
            pydantic_model=CompanyDescriptionResponse,
        )

        if not result_structured:
            self.session_logger.warning(
                "No valid JSON response from LLM for company description."
            )
            return None

        try:
            validated = CompanyDescriptionResponse.model_validate(result_structured)
            return validated.company_description
        except Exception as e:
            self.session_logger.error(f"Failed to validate company description: {e}")
            return None

    async def extract_infos_job_description(
        self, job_description_text: str, location_country=None, location_region=None
    ):
        """Extract required skills, location info, and salary data from a job description using the LLM."""

        system_prompt, user_prompt = get_job_infos_prompt(
            location_country, job_description_text
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        result_structured = await call_llm_structured(
            llm_client=llm_client,
            model=LLM_MODEL,
            messages=messages,
            logger=self.session_logger,
            max_tokens=1024,
            temperature=0.0,
            retry=True,
            pydantic_model=JobInfosExtractionResponse,
        )

        if not result_structured:
            self.session_logger.warning(
                "No valid JSON response from LLM for job infos extraction."
            )
            return [], location_country, location_region, None

        # --- Validate and normalize using Pydantic ---
        try:
            validated = JobInfosExtractionResponse.model_validate(result_structured)
        except Exception as e:
            self.session_logger.error(f"Validation failed for skill extraction: {e}")
            return [], location_country, location_region, None

        return (
            validated.skills_required,
            validated.location_country or location_country,
            validated.location_region or location_region,
            validated.salary,
        )

    async def check_single_link(self, page: Page, job_url: str) -> bool:
        """Check a single job link using Playwright."""
        if not job_url or job_url.lower().startswith("mailto:"):
            self.session_logger.info(f"📧 Skipping mailto or invalid URL: {job_url}")
            return True

        blocked_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")

        if job_url.lower().endswith(blocked_extensions):
            self.session_logger.info(f"📎 File link detected: {job_url}")

            # Check if it's reachable
            if await self.is_pdf_url_valid(job_url):
                self.session_logger.info(f"{job_url} reachable (200 OK)")
                return True
            else:
                self.session_logger.info(f"{job_url} not reachable")
                return False

        try:

            response = await page.goto(
                job_url, timeout=self.timeout, wait_until="domcontentloaded"
            )

            await page.wait_for_timeout(random.uniform(1000, 3000))

            if not response:
                self.session_logger.info(f"No response for {job_url}")
                return False

            status = response.status
            self.session_logger.info(f"{job_url} → HTTP {status}")

            # If response status is not good
            if status >= 400:
                return False

            return True

        except PlaywrightTimeoutError:
            self.session_logger.warning(f"Timeout loading {job_url}")
            return False
        except Exception as e:
            self.session_logger.warning(f"Error checking {job_url}: {e}")
            return False

    async def post_process(self, page: Page) -> None:
        """Post-process and enrich scraped job offers with embeddings, descriptions, and metadata."""

        # --- Filter and deduplicate job offers ---
        def not_seen_and_add(url: str, seen: set[str]) -> bool:
            if url in seen:
                return False
            seen.add(url)
            return True

        seen_urls: set[str] = set()

        job_offers_urls = set([job["job_url"] for job in self.job_offers])

        self.old_job_offers.extend(list(self.current_job_offers - job_offers_urls))

        new_job_offers_to_complete = [
            job
            for job in self.job_offers
            if job.get("job_title")
            and job.get("job_url")
            and job["job_url"] not in self.current_job_offers
            and not_seen_and_add(job["job_url"], seen_urls)
            # and await self.check_single_link(job["job_url"])
        ]

        self.session_logger.info("Intermediary Results:")
        self.session_logger.info(f"Emails: {self.emails}")
        self.session_logger.info(f"Job Offers {len(self.job_offers)}: {self.job_offers}")
        self.session_logger.info(
            f"New Job Offers {len(new_job_offers_to_complete)}: {new_job_offers_to_complete}"
        )
        self.session_logger.info(
            f"Old Job Offers {len(self.old_job_offers)}: {self.old_job_offers}"
        )

        blocked_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")
        filtered_offers = []
        nb_job_offers_to_process = len(new_job_offers_to_complete)

        # --- Process each job offer ---
        for index, job in enumerate(new_job_offers_to_complete):
            self.session_logger.info(
                f"Processing job offer #{index + 1}/{nb_job_offers_to_process}: {job}"
            )

            job_url = job.get("job_url", "")
            job_title = job.get("job_title", "")

            # Generate title embedding
            embedding = await self.job_vector_embedding(job_title)
            job["job_title_vector"] = (
                embedding.tolist() if isinstance(embedding, np.ndarray) else embedding
            )

            # Skip invalid URLs (attachments, mailto, etc.)
            if job_url.lower().endswith(blocked_extensions) or job_url.startswith(
                "mailto:"
            ):

                self.session_logger.info("Skipped attachment or mailto link.")

                job["skills_required"] = []
                job["salary"] = None

                filtered_offers.append(job)

                continue

            # --- Extract job description ---

            result_job_description = None

            if job_url.lower().endswith((".pdf", ".docx")):

                result_job_description = await self.extract_job_description_file(
                    job_url
                )

            else:

                result_job_description = await self.extract_job_description(
                    page, job_url
                )

            if result_job_description is None:
                job_description, hash_job_description_page = None, None
            else:
                job_description, hash_job_description_page = result_job_description

            job["job_description"] = job_description
            job["hash_job_description_page"] = hash_job_description_page

            # --- Extract structured info ---
            if job_description:
                skills_required, country, region, salary = (
                    await self.extract_infos_job_description(
                        job_description,
                        job.get("location_country"),
                        job.get("location_region"),
                    )
                )

                country = self.find_best_match_country(country)
                region = self.find_best_match_region(region, country)
                salary = salary if salary and len(salary) < 100 else None

                job.update(
                    {
                        "skills_required": skills_required,
                        "salary": salary,
                        "location_country": self.replace_israel(country),
                        "location_region": region,
                    }
                )

            # --- Extract company info once ---
            if index == 0:
                if job_description:
                    self.company_description = await self.extract_company_description(
                        job_description
                    )
                    self.session_logger.info(
                        f"Company description inside postprocess: {self.company_description}"
                    )
                await self.find_company_logo.get_company_logo_url(page)

            filtered_offers.append(job)

        self.new_job_offers.extend(filtered_offers)

        return