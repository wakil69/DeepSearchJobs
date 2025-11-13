import {
  pgEnum,
  pgTable,
  serial,
  text,
  timestamp,
  jsonb,
  doublePrecision,
  boolean,
  varchar,
  integer,
} from "drizzle-orm/pg-core";

// --- Enums ---
export const jobStatusEnum = pgEnum("job_status", ["applied", "not_interested"]);

export const jobStatusApplicationEnum = pgEnum("job_status_application", [
  "applied",
  "on_hold",
  "interviewing",
  "offer_made",
  "offer_accepted",
  "offer_refused",
  "not_selected",
]);

export const contractTypeEnum = pgEnum("contract_type", [
  "full_time",
  "part_time",
  "internship",
  "freelance",
  "short_term",
  "apprenticeship",
  "graduate_program",
  "remote",
]);

export type ContractType = (typeof contractTypeEnum.enumValues)[number];

// --- companies table ---
export const companies = pgTable("companies", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  website: text("website"),
  description: text("description"),
  internalJobListingPages: text("internal_job_listing_pages").array(),
  externalJobListingPages: text("external_job_listing_pages").array(),
  emails: text("emails").array(),
  containersHtml: jsonb("containers_html"),
  creationDate: timestamp("creation_date", { withTimezone: true })
    .defaultNow()
    .notNull(),
  updateDate: timestamp("update_date", { withTimezone: true }),
});

// --- all_jobs table ---
export const allJobs = pgTable("all_jobs", {
  id: serial("id").primaryKey(),

  companyId: integer("company_id")
    .references(() => companies.id, { onDelete: "cascade" })
    .notNull(),

  jobTitle: text("job_title").notNull(),
  jobUrl: text("job_url").notNull(),
  jobDescription: text("job_description"),
  skillsRequired: text("skills_required").array(),

  locationCountry: varchar("location_country", { length: 255 }),
  locationRegion: varchar("location_region", { length: 255 }),

  contractType: contractTypeEnum("contract_type"),

  salary: varchar("salary", { length: 255 }),

  isExisting: boolean("is_existing").default(false).notNull(),

  jobTitleVectors: doublePrecision("job_title_vectors").array(),

  creationDate: timestamp("creation_date", { withTimezone: true })
    .defaultNow()
    .notNull(),

  updateDate: timestamp("update_date", { withTimezone: true })
    .defaultNow()
    .notNull(),
});

// --- jobs_proposals table ---
export const jobsProposals = pgTable("jobs_proposals", {
  id: serial("id").primaryKey(),

  jobId: integer("job_id")
    .references(() => allJobs.id, { onDelete: "cascade" })
    .notNull(),

  status: jobStatusEnum("status").notNull(),
  statusApplication: jobStatusApplicationEnum("status_application"),

  creationDate: timestamp("creation_date", { withTimezone: true })
    .defaultNow()
    .notNull(),

  updateDate: timestamp("update_date", { withTimezone: true })
    .defaultNow()
    .notNull(),
});