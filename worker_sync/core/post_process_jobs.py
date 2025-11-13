import random
import requests
import json
import numpy as np

from numpy.linalg import norm
from sentence_transformers import SentenceTransformer
from Levenshtein import ratio as levenshtein_ratio
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from worker_sync.core.find_company_logo import FindCompanyLogo
from dataclasses import dataclass, field
from typing import Callable, Any, Optional, List, Tuple
from worker_sync.core.prompts import get_extract_company_description_prompt, get_job_infos_prompt
from worker_sync.core.llm_utils import call_llm_structured
from worker_sync.worker_types import CompanyDescriptionResponse, JobInfosExtractionResponse, Job
from pathlib import Path

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cpu")

country_data_file_path = Path(__file__).resolve().parent.parent / "country-region-data.json"

with open(country_data_file_path, "r", encoding="utf-8") as file:
    country_data = json.load(file)


@dataclass
class PostProcessingJobs:
    logger: Any
    page: Any
    emails: set[str]
    get_emails: Callable
    restart_context: Callable
    llm_client: Any
    llm_model: str
    send_heartbeat_if_needed: Callable
    company_name: str
    company_id: int
    user_agents: list[str]
    find_company_logo: FindCompanyLogo = field(init=False)
    job_offers: List[Job]
    company_description: Optional[str]

    def __post_init__(self):
        self.find_company_logo = FindCompanyLogo(
            self.page, self.logger, self.company_name, self.company_id
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

        countries = [c["countryName"] for c in country_data]

        # Calculate similarity scores for all countries
        matches = [
            (country, levenshtein_ratio(input_country.lower(), country.lower()) * 100)
            for country in countries
        ]

        # Find the best match
        best_match, best_score = max(matches, key=lambda x: x[1])

        return best_match if best_score >= score_threshold else None

    @staticmethod
    def find_best_match_region(
        input_region: Optional[str], country_name: Optional[str], score_threshold: int = 85
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
            (c for c in country_data if c["countryName"] == country_name), None
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
    def job_vector_embedding(job_title: str) -> Optional[np.ndarray]:
        """Return the L2-normalized embedding for a job title, or None if invalid."""
        embedding = model.encode(job_title, convert_to_tensor=True)
        embedding_np = embedding.cpu().numpy()
        norm_val = norm(embedding_np)

        if not np.isfinite(norm_val) or norm_val == 0:
            return None

        return embedding_np / norm_val

    def extract_job_description(self, url: str, retries=1) -> Optional[str]:
        """Extract a job description text from a job description page."""
        try:
            self.page.goto(url, timeout=25000, wait_until="domcontentloaded")
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.page.wait_for_timeout(2000)

            soup = BeautifulSoup(self.page.content(), "lxml")
            job_description = soup.body or soup

            job_description = soup.body or soup

            for tag in job_description(["script", "style", "meta", "noscript", "svg"]):
                tag.decompose()

            text_job_description = job_description.get_text(separator="\n", strip=True)

            if new_emails := self.get_emails(text_job_description):
                self.logger.info(f"Emails found: {new_emails}")
                self.emails.update(new_emails)

            return text_job_description

        except PlaywrightTimeoutError as e:
            self.logger.warning(f"Timeout loading {url}: {e}")
        except Exception as e:
            self.logger.warning(f"Playwright failure at {url}: {e}")

        if retries > 0:
            self.logger.info("Restarting browser and retrying...")
            self.restart_context()
            return self.extract_job_description(url, retries=retries - 1)

        self.logger.error(
            f"Failed to extract job description from {url} after retries."
        )
        return None

    def extract_company_description(self, job_description_text: str) -> Optional[str]:
        """Extract a concise company description from a job description using the LLM."""
        system_prompt, user_prompt = get_extract_company_description_prompt(
            job_description_text
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        result_structured = call_llm_structured(
            llm_client=self.llm_client,
            model=self.llm_model,
            messages=messages,
            logger=self.logger,
            max_tokens=256,
            temperature=0.0,
            retry=True,
            pydantic_model=CompanyDescriptionResponse
        )

        if not result_structured:
            self.logger.warning(
                "No valid JSON response from LLM for company description."
            )
            return None

        try:
            validated = CompanyDescriptionResponse.model_validate(result_structured)
            return validated.company_description
        except Exception as e:
            self.logger.error(f"Failed to validate company description: {e}")
            return None

    def extract_infos_job_description(
        self, job_description_text: str, location_country=None, location_region=None
    ):
        """Extract required skills, location info, and salary data from a job description using the LLM."""

        system_prompt, user_prompt = get_job_infos_prompt(location_country, job_description_text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        result_structured = call_llm_structured(
            llm_client=self.llm_client,
            model=self.llm_model,
            messages=messages,
            logger=self.logger,
            max_tokens=1024,
            temperature=0.0,
            retry=True,
            pydantic_model=JobInfosExtractionResponse
        )
        
        if not result_structured:
            self.logger.warning("No valid JSON response from LLM for job infos extraction.")
            return [], location_country, location_region, None
 
        # --- Validate and normalize using Pydantic ---
        try:
            validated = JobInfosExtractionResponse.model_validate(result_structured)
        except Exception as e:
            self.logger.error(f"Validation failed for skill extraction: {e}")
            return [], location_country, location_region, None

        return (
            validated.skills_required,
            validated.location_country or location_country,
            validated.location_region or location_region,
            validated.salary,
        )

    def check_single_link(self, job_url: str) -> bool:
        """Check if a single job link is still active based on HTTP status code."""
        try:

            self.send_heartbeat_if_needed()

            extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")

            if job_url.lower().endswith(extensions):
                self.logger.info(f"Job {job_url} is a file link: {job_url}")
                return True

            # Always allow mailto links
            if job_url.lower().startswith("mailto:"):
                self.logger.info(f"Job {job_url} is a mailto link (valid)")
                return True

            headers = {"User-Agent": random.choice(self.user_agents)}

            response = requests.head(
                job_url, allow_redirects=True, timeout=15, headers=headers
            )

            # Some servers may not support HEAD, fall back to GET
            if response.status_code in (405, 501):
                response = requests.get(
                    job_url, allow_redirects=True, timeout=15, headers=headers
                )

            if response.status_code < 400:
                self.logger.info(f"{job_url} returned {response.status_code}")
                return True
            else:
                self.logger.info(f"{job_url} returned {response.status_code}")
                return False

        except Exception as e:
            self.logger.info(f"Request failed for {job_url}: {e}")
            return False

    def post_process(self) -> None:
        """Post-process and enrich scraped job offers with embeddings, descriptions, and metadata."""

        # --- Filter and deduplicate job offers ---
        def not_seen_and_add(url: str, seen: set[str]) -> bool:
            if url in seen:
                return False
            seen.add(url)
            return True

        seen_urls: set[str] = set()
        
        self.job_offers = [
            job
            for job in self.job_offers
            if job.get("job_title")
            and job.get("job_url")
            and not_seen_and_add(job["job_url"], seen_urls)
            and self.check_single_link(job["job_url"])
        ]
        
        self.logger.info("Intermediary Results:")
        self.logger.info(f"Emails: {self.emails}")
        self.logger.info(f"Job Offers: {self.job_offers}")

        blocked_extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar")
        filtered_offers = []
        nb_job_offers_to_process = len(self.job_offers)
        
        # --- Process each job offer ---
        for index, job in enumerate(self.job_offers):
            self.send_heartbeat_if_needed()
            self.logger.info(f"Processing job offer #{index + 1}/{nb_job_offers_to_process}: {job}")

            job_url = job.get("job_url", "")
            job_title = job.get("job_title", "")

            # Generate title embedding
            embedding = self.job_vector_embedding(job_title)
            job["job_title_vector"] = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding

            # Skip invalid URLs (attachments, mailto, etc.)
            if job_url.lower().endswith(blocked_extensions) or job_url.startswith("mailto:"):
                
                self.logger.info("Skipped attachment or mailto link.")
                
                job["skills_required"] = []
                job["salary"] = None
                
                filtered_offers.append(job)
                
                continue

            # --- Extract job description ---
            job_description = self.extract_job_description(job_url)
            job["job_description"] = job_description

            # --- Extract structured info ---
            if job_description:
                skills_required, country, region, salary = self.extract_infos_job_description(
                    job_description,
                    job.get("location_country"),
                    job.get("location_region"),
                )
                
                country = self.find_best_match_country(country)
                region = self.find_best_match_region(region, country)
                salary = salary if salary and len(salary) < 100 else None
                
                job.update(
                    {
                        "skills_required": skills_required,
                        "salary": salary,
                        "location_country": country,
                        "location_region": region,
                    }
                )

            # --- Extract company info once ---
            if index == 0:
                if job_description:
                    self.company_description = self.extract_company_description(job_description)
                self.find_company_logo.get_company_logo_url()

            filtered_offers.append(job)

        return
    
