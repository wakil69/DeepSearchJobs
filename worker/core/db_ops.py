import worker.dependencies as deps

from psycopg.types.json import Json
from typing import List, Optional
from worker.types.worker_types import Job


class DBOps:
    def __init__(self, session_logger) -> None:
        self.session_logger = session_logger

    async def save_db_job_listing_pages(
        self,
        company_name: str,
        company_id: int,
        internal_job_listing_pages: List[str],
        external_job_listing_pages: List[str],
        emails: set[str],
    ) -> None:
        """Save scraping results into the database.
        Returns:
            int: 1 if the update succeeded, raises Exception otherwise.
        """

        if deps.pool_postgres is None:
            raise RuntimeError("PostgreSQL pool not initialized")

        try:

            async with deps.pool_postgres.connection() as conn:
                async with conn.transaction():
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE companies
                            SET emails = %s, 
                                external_job_listing_pages = %s, 
                                internal_job_listing_pages = %s
                            WHERE id = %s
                            """,
                            (
                                list(emails) or None,
                                external_job_listing_pages or None,
                                internal_job_listing_pages or None,
                                company_id,
                            ),
                        )

        except Exception:
            self.session_logger.exception(
                f"Database error for company {company_name}, company ID: {company_id}"
            )
            raise

    async def insert_jobs_and_emails_in_db(
        self,
        conn,
        company_id,
        website,
        emails,
        external_job_listing_pages,
        internal_job_listing_pages,
        containers_html,
        company_description,
        new_job_offers,
    ) -> None:
        """Insert jobs and emails into the DB (companies and all_jobs tables)."""

        async with conn.cursor() as cur:
            emails = list(emails) or None
            external_job_listing_pages = external_job_listing_pages or None
            internal_job_listing_pages = internal_job_listing_pages or None
            containers_html = {
                base_url: list(values)
                for base_url, values in containers_html.items()
            }

            await cur.execute(
                """
                UPDATE companies
                SET website = %s, emails = %s, description = %s, external_job_listing_pages = %s, internal_job_listing_pages = %s, containers_html = %s
                WHERE id = %s
                """,
                (
                    website,
                    emails,
                    company_description,
                    external_job_listing_pages,
                    internal_job_listing_pages,
                    Json(containers_html),
                    company_id,
                ),
            )

            if not new_job_offers:
                self.session_logger.info(
                    "No job offers to insert for this company."
                )
                return

            job_urls = [
                job["job_url"] for job in new_job_offers if job.get("job_url")
            ]

            await cur.execute(
                """
                SELECT job_url
                FROM all_jobs
                WHERE job_url = ANY(%s)
                AND is_existing = TRUE;
                """,
                (job_urls,),
            )
            
            existing_urls = {row[0] for row in await cur.fetchall()}

            self.session_logger.info(
                f"Found {len(existing_urls)} existing active jobs for this company."
            )

            for job in new_job_offers:
                
                job_url = job.get("job_url")
                
                if not job_url:
                    continue

                job_record = (
                    company_id,
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

                if job_url in existing_urls:
                    # Update existing job
                    await cur.execute(
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
                    await cur.execute(
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
                    
            self.session_logger.info(
                "Successfully inserted/updated all job offers for company."
            )

    async def update_old_jobs(self, conn, company_id, old_job_offers) -> None:
        """Set is_existing = FALSE for old job URLs no longer active (PostgreSQL)."""
        if not old_job_offers:
            self.session_logger.info("No old jobs to update.")
            return


        async with conn.cursor() as cur:
            
            await cur.execute(
                """
                UPDATE all_jobs
                SET is_existing = FALSE
                WHERE company_id = %s
                AND is_existing = TRUE
                AND job_url = ANY(%s)
                RETURNING id
                """,
                (company_id, old_job_offers),
            )

    async def save_db_results(
        self,
        company_id: int,
        company_name: str,
        company_description: Optional[str],
        website: Optional[str],
        emails: set[str],
        external_job_listing_pages: List[str],
        internal_job_listing_pages: List[str],
        containers_html: dict[str, set[str]],
        old_job_offers: List[str],
        new_job_offers: List[Job],
    ) -> None:
        """Save scraping results into the database."""

        if deps.pool_postgres is None:
            raise RuntimeError("PostgreSQL pool not initialized")

        try:

            async with deps.pool_postgres.connection() as conn:
                async with conn.transaction():
                    async with conn.cursor() as cur:

                        await self.update_old_jobs(conn, company_id, old_job_offers)

                        await self.insert_jobs_and_emails_in_db(
                            conn,
                            company_id=company_id,
                            website=website,
                            emails=emails,
                            external_job_listing_pages=external_job_listing_pages,
                            internal_job_listing_pages=internal_job_listing_pages,
                            containers_html=containers_html,
                            new_job_offers=new_job_offers,
                            company_description=company_description
                        )

        except Exception as e:
            self.session_logger.error(f"Database error for company {company_name}: {e}")
            raise
