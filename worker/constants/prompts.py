import json

from typing import Optional

def get_filter_internal_career_pages_prompt(
    company_name: str, internal_pages: set[str]
) -> str:
    """
    Build a prompt for identifying internal career/job listing pages
    from a company's official website.
    """

    prompt = f"""
    You are a smart AI assistant helping with web scraping.

    You are given a list of **internal pages** from the company **{company_name}**'s official website.
    Your job is to return only the pages that are likely to contain **job listings or open positions**.

    Exclude pages that are individual job descriptions or unrelated
    (e.g., blog, news, about us, contact, etc.).

    Do NOT modify or rewrite any URLs.

    Respond in the following JSON format:
    {{
        "career_pages": ["url1", "url2", ...]
    }}

    Pages to analyze:
    {json.dumps(list(internal_pages), indent=2)}
    """

    return prompt

def get_filter_external_career_pages_prompt(
    company_name: str, external_pages: set[str]
) -> str:
    """
    Build a prompt for identifying external career/job listing pages
    such as ATS links or job boards.
    """
    prompt = f"""
    You are a smart AI assistant helping with job search scraping.

    The company **{company_name}** lists external websites that may host their job offers
    (e.g., job boards, ATS systems).

    Your job is to identify only the URLs that could represent **career or job listing pages**,
    excluding individual job detail pages.

    Also keep URLs where **any part or variation** of the company name
    appears in the URL path or domain.

    Do NOT modify or rewrite any URLs.

    Return a JSON like this:
    {{
        "career_pages": ["url1", "url2", ...]
    }}

    External pages to analyze:
    {json.dumps(list(external_pages), indent=2)}
    """

    return prompt

def get_filter_career_pages_prompt(all_pages: set[str]) -> str:
    """
    Build a prompt for identifying career/job listing pages
    such as ATS links or job boards.
    """
    prompt = f"""
        You are a smart AI assistant helping with web scraping.
        Below is a list of pages from a website.

        Your task:
        - Identify pages that are **job listing or career overview pages**.
        - Do NOT include job description/detail pages (these usually have long slugs with job titles, locations, or IDs).
        - Exclude pages that point to a single specific role.
        - Include only the higher-level pages where multiple jobs are listed or browsed.

        Return a JSON object in exactly this format:
        {{
            "career_pages": ["url1", "url2", ...]
        }}

        Pages to analyze:
        {json.dumps(list(all_pages), indent=2)}
        """

    return prompt

def get_identify_career_page_prompt(text_content: str) -> tuple[str, str]:
    """
    Build a prompt for identifying career/job listing pages.
    """

    system_prompt = """
        You are an expert AI assistant specialized in job listing detection.
        Your task is to analyze an text content page and determine if it contains **job listings**.

        ### **Instructions**:
        1. If the page contains job offers, return `"is_job_listing_page": "yes"`.
        2. If it does **not** contain job offers, return `"is_job_listing_page": "no"`.
        3. **Exclude pages** that are:
        - Career blogs, company descriptions, press releases.

        ### **Expected JSON Output**:
        ```json
        {
            "is_job_listing_page": "yes" or "no"
        }
        ```
        """

    user_prompt = f"""
        ### 
        {text_content}
        """

    return system_prompt, user_prompt

def get_extract_company_description_prompt(job_description_text: str) -> tuple[str, str]:
    """
    Build a prompt for identifying career/job listing pages.
    """

    system_prompt = """
    You are an AI assistant specialized in extracting the company description from job descriptions. 

    ### **Instructions:**
    - Identify the section of the job description that describes the company.
    - Ignore information related to job responsibilities, qualifications, benefits, or application instructions.
    - If no explicit company description is provided, return an empty string.
    - Ensure the response is a valid JSON object.

    ### **Expected JSON Output Format:**
    ```json
    {
        "company_description": "<Extracted company description text>"
    }
    ```
    Only return the JSON output without any additional text.
    """

    user_prompt = f"""
    ### **Job Description:**
    {job_description_text}

    Extract and return only the company description.
    """

    return system_prompt, user_prompt

def get_job_infos_prompt(location_country: Optional[str], job_description_text:str) -> tuple[str, str]:
    
    if location_country:
            system_prompt = """
            You are an AI assistant specialized in extracting skills required from job descriptions. 
            Your task is to analyze the provided job description and extract a list of the required skills.
            
            ### **Expected JSON Output:**
            ```json
            {
                "skills_required": [
                    "Skill 1",
                    "Skill 2",
                    "Skill 3",
                    ...
                ],
                "salary": "Only numeric value(s) with currency. Return null if not clearly specified."
            }
            ```
            Only return a valid JSON object with the fields skills_required and salary. If salary is not specified in the description, return null for the "salary" field.
            """

    else:
        system_prompt = """
        You are an AI assistant specialized in extracting skills required from job descriptions. 
        Your task is to analyze the provided job description and extract a list of the required skills and the job location information.
        **Normalize location information**:
            - If the country or region is given in **abbreviated form** (e.g., "US", "UK", "NY", "TX"), **convert it into the full official name** 
                (e.g., "United States", "United Kingdom", "New York", "Texas").
            - Use globally recognized full names for countries and regions. **Country names must be in English**.

        
        ### **Expected JSON Output:**
        ```json
        {
            "skills_required": [
                "Skill 1",
                "Skill 2",
                "Skill 3",
                ...
            ],
            "location_country": "Job Location Country",
            "location_region": "The **official region** (not a city) where the job is located.",
            "salary": "Only numeric value(s) with currency. Return null if not clearly specified."
        }
        ```
        """

    user_prompt = f"""
    ### **Extracted Job Description:**
    {job_description_text}
    """
    
    return system_prompt, user_prompt
    
PROMPT_CLEAN_JSON = """
You are an assistant specialized in returning JSON without formatting issues so that I can then insert it into json.loads() without any problem.
Do not remove anything at all.
"""

PROMPT_IDENTIFY_PAGINATION_CONTAINER = """
You are an AI specialized in web scraping. Your task is to analyze the HTML structure of a webpage and identify the **container element** that holds pagination buttons.

### **Instructions:**
1. **Identify the pagination container**:
    - Look for elements (e.g., `<div>`, `<nav>`, `<ul>`) that contain pagination buttons such as:
    - Page numbers (e.g., "1", "2", "3", "4", etc.).
    - Navigation buttons (e.g., "Next", "Previous").
    - Symbols (e.g., `<<`, `>>`, `<`, `>`).
    - The pagination container should **only** include elements responsible for navigating pages.

2. **How to return the result**:
    - If you find a **clear and unique pagination container**, return its **XPath**.
    - If **no valid pagination container is found**, return `None` (not an empty string).

### **Expected JSON Response Format:**
```json
{
    "container_identifier": "xpath or None" 
}
```
"""

PROMPT_IDENTIFY_SHOW_MORE_BUTTON_TEXT = """
You are an AI that extracts the VISIBLE TEXT of a 'show more' pagination button from a webpage.

Return ONLY a JSON object in this format:
{
    "button_text": "<text or empty string>"
}

Rules:
    - VALID matches must clearly indicate **loading or revealing more content**,
    such as:
        "Show more", "Load more", "View more", "See more", "More results", "More items", etc.
    - INVALID matches include any **pagination or navigation controls**, such as:
        "Next", "Previous", "Back", "Forward", "First", "Last", "Page 1", "1", "2", "3", etc.
    - Do NOT return texts that only imply page navigation, even if at the bottom.
    - If multiple valid matches exist, choose the one closest to the bottom of the page text.
    - If nothing valid matches, return {"button_text": ""}.
"""

PROMPT_EXTRACT_JOBS = """
You are a smart AI assistant specialized in job web scraping. 
Your task is to analyze the text content and links from a webpage and determine if it contains **job listings**.

### Instructions:
**Extract only real job listings**:
- A valid job listing must have:
- A **clear job title**.
- A **valid job application link** that is explicitly present in the provided content.  
    Do NOT invent or guess URLs.  
    If no link is present for a job, set `"job_url": null`.
- Normalize **location information**:
- Convert country or region abbreviations (e.g., "US", "UK", "NY", "TX") into the full official name 
    (e.g., "United States", "United Kingdom", "New York", "Texas").
- Country names must always be in **English**.
- `"location_region"` must be the **official region/state/province**, not a city.
- Exclude items that are not actual job offers:
- Advertisements
- Employee testimonials
- Company descriptions
- Career category pages, search filters, or generic “jobs” pages
- Press releases, blog posts, or advice articles

### Rules:
- Only include links that are **explicitly visible in the given content**.  
- If a job looks real but has no apply link, return it with `"job_url": null`.  
- Never generate or invent new links.


### **Expected JSON Output:**
```json
{{
    "jobs": [
        {{
            "job_title": "Job Title",
            "location_country": "Job Location Country",
            "location_region": "The **official region** (not a city) where the job is located.",
            "job_url": "Job application URL (if available, else null)",
            "contract_type": "full_time | part_time | internship | freelance | short_term | apprenticeship | graduate_program | remote"
        }},
        ...
    ]
}}
```
"""
