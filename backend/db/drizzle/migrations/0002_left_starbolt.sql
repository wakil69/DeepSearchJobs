ALTER TABLE "companies" ALTER COLUMN "update_date" DROP DEFAULT;--> statement-breakpoint
ALTER TABLE "companies" ALTER COLUMN "update_date" DROP NOT NULL;