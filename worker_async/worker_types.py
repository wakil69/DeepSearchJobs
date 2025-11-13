from typing import TypedDict, Literal, Optional, List, Dict, NotRequired, Required
from pydantic import BaseModel, Field

class JobData(TypedDict):
    """Represents a job message sent between the producer and worker."""
    company_id: int
    company_name: str
    
class CompanyRecord(TypedDict):
    """Represents a company record fetched from the database."""
    website: Optional[str]
    internal_job_listing_pages: List[str]
    external_job_listing_pages: List[str]
    emails: set[str]
    containers_html: dict[str, set[str]]
    current_job_offers: set[str]

class JobStatus(TypedDict, total=False):
    """Represents the job state stored in Redis."""
    status: Literal["new", "in_progress", "done", "failed"]
    retries: int
    job_listings_step_done: Optional[str]
    
class Region(TypedDict):
    """Represents a region/state within a country."""
    name: str
    shortCode: str

class Country(TypedDict):
    """Represents a country with its regions."""
    countryName: str
    countryShortCode: str
    regions: List[Region]
    
class CareerPagesResponse(BaseModel):
    """Pydantic model for validating career pages LLM responses."""
    career_pages: List[str]
    
class IsJobListingPageResponse(BaseModel):
    """Pydantic model for validating job listing page LLM responses."""
    is_job_listing_page: Literal["yes", "no"] = Field(
        ...,
        description="Indicates whether the page contains job listings ('yes') or not ('no')."
    )
    
class JobListingsResult(TypedDict):
    """
    Represents the structured results of a crawl operation for job listings.

    Attributes:
        website: Website to crawl.
        internal_job_listing_pages: List of URLs pointing to internal job listing pages.
        external_job_listing_pages: List of URLs pointing to external job boards or aggregators.
        emails: Set of email addresses found during the crawl.
        containers_html: Mapping where each key is a job listing page URL, and each
                         value is the HTML snippet or element representing the pagination
                         container. 
    """
    website: Optional[str]
    internal_job_listing_pages: List[str]
    external_job_listing_pages: List[str]
    emails: set[str]
    containers_html: dict[str, set[str]]
    current_job_offers: set[str]
    

class Job(TypedDict):
    """Represents a structured job entry with metadata and embeddings."""
    job_title: str
    job_url: str
    location_country: NotRequired[Optional[str]]
    location_region: NotRequired[Optional[str]]
    job_description: NotRequired[Optional[str]]
    skills_required: NotRequired[List[str]] 
    contract_type: NotRequired[Optional[str]]
    salary: NotRequired[Optional[str]]
    job_title_vector: NotRequired[Optional[List[float]]]  # 1D embedding vector
        
class ContainerIdentifier(BaseModel):
    """XPath expression identifying the pagination container, or None if not applicable."""
    container_identifier: Optional[str] = None  # XPath or None
    
class ButtonLoadMoreIdentifier(BaseModel):
    """Expression identifying the pagination container, or "" if not applicable."""
    button_text: Optional[str] = None 

class JobLLMExtracted(BaseModel):
    """Represents a structured job posting."""
    job_title: str = Field(..., description="Job Title")
    location_country: Optional[str] = Field(None, description="Job Location Country")
    location_region: Optional[str] = Field(
        None,
        description="The official region (not a city) where the job is located."
    )
    job_url: Optional[str] = Field(
        None,
        description="Job application URL (if available, else null)"
    )
    contract_type: Optional[
        Literal[
            "full_time",
            "part_time",
            "internship",
            "freelance",
            "short_term",
            "apprenticeship",
            "graduate_program",
            "remote",
        ]
    ] = Field(
        None,
        description="Type of employment: full_time | part_time | internship | freelance | short_term | apprenticeship | graduate_program | remote"
    )


class JobsResponse(BaseModel):
    """Validates that the input contains a list of JobLLMExtracted under the 'jobs' key."""
    jobs: List[JobLLMExtracted]

PaginationButtons = Dict[str, List[str]] # Example: {"pagination_buttons": ["//button[@id='page_1']", "//a[text()='Next']"]}

class CompanyDescriptionResponse(BaseModel):
    """Represents the extracted company description, or None if unavailable."""
    company_description: Optional[str] = None
    
class JobInfosExtractionResponse(BaseModel):
    """Represents the structured response extracted from a job description."""
    
    skills_required: List[str] = Field(default_factory=list, description="List of required skills.")
    location_country: Optional[str] = Field(default=None, description="Full country name, if detected.")
    location_region: Optional[str] = Field(default=None, description="Full region name, if detected.")
    salary: Optional[str] = Field(default=None, description="Numeric value(s) with currency, or None if unspecified.")