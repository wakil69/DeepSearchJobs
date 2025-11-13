CREATE TYPE "public"."contract_type" AS ENUM('full_time', 'part_time', 'internship', 'freelance', 'short_term', 'apprenticeship', 'graduate_program', 'remote');--> statement-breakpoint
CREATE TYPE "public"."job_status_application" AS ENUM('applied', 'on_hold', 'interviewing', 'offer_made', 'offer_accepted', 'offer_refused', 'not_selected');--> statement-breakpoint
CREATE TYPE "public"."job_status" AS ENUM('applied', 'not_interested');--> statement-breakpoint
CREATE TABLE "all_jobs" (
	"id" serial PRIMARY KEY NOT NULL,
	"company_id" integer NOT NULL,
	"job_title" text NOT NULL,
	"job_url" text NOT NULL,
	"job_description" text,
	"skills_required" text[],
	"location_country" varchar(255),
	"location_region" varchar(255),
	"contract_type" "contract_type",
	"salary" varchar(255),
	"is_existing" boolean DEFAULT false NOT NULL,
	"job_title_vectors" double precision[],
	"creation_date" timestamp with time zone DEFAULT now() NOT NULL,
	"update_date" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "companies" (
	"id" serial PRIMARY KEY NOT NULL,
	"name" text NOT NULL,
	"website" text,
	"description" text,
	"internal_job_listing_pages" text[],
	"external_job_listing_pages" text[],
	"emails" text[],
	"containers_html" jsonb,
	"creation_date" timestamp with time zone DEFAULT now() NOT NULL,
	"update_date" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "jobs_proposals" (
	"id" serial PRIMARY KEY NOT NULL,
	"job_id" integer NOT NULL,
	"status" "job_status" DEFAULT 'applied' NOT NULL,
	"status_application" "job_status_application" DEFAULT 'applied' NOT NULL,
	"creation_date" timestamp with time zone DEFAULT now() NOT NULL,
	"update_date" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "all_jobs" ADD CONSTRAINT "all_jobs_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs_proposals" ADD CONSTRAINT "jobs_proposals_job_id_all_jobs_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."all_jobs"("id") ON DELETE cascade ON UPDATE no action;