ALTER TABLE "jobs_proposals" ALTER COLUMN "status" DROP DEFAULT;--> statement-breakpoint
ALTER TABLE "jobs_proposals" ALTER COLUMN "status_application" DROP DEFAULT;--> statement-breakpoint
ALTER TABLE "jobs_proposals" ALTER COLUMN "status_application" DROP NOT NULL;