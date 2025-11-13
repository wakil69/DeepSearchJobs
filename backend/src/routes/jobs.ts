import { FastifyInstance } from "fastify";
import { db } from "../../db/drizzle/drizzle";
import {
  allJobs,
  companies,
  ContractType,
  jobsProposals,
} from "../../db/drizzle/schema";
import { and, eq, ilike, inArray, sql } from "drizzle-orm";
import { buildMust, buildQuery } from "../utilities/elasticSearchJobs";
import clientElasticSearch from "../../db/elasticsearch/elasticsearch";
import type { Tensor } from "@xenova/transformers";

export async function jobsRoutes(fastify: FastifyInstance) {
  fastify.get("/", {
    schema: {
      description:
        "Fetch jobs from Elasticsearch excluding already proposed ones, enriched with company info from PostgreSQL",
      tags: ["Jobs"],
      querystring: {
        type: "object",
        properties: {
          page: { type: "number", minimum: 1, default: 1 },
          pageSize: { type: "number", minimum: 1, maximum: 50, default: 10 },
          country: { type: "string" },
          regions: { type: "array", items: { type: "string" } },
          contract_type: { type: "string" },
          search: { type: "string" },
          company_id: { type: "number" },
        },
      },
      response: {
        200: {
          type: "object",
          properties: {
            jobs: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  id: { type: "number" },
                  company: { type: "string" },
                  companyId: { type: "number" },
                  jobTitle: { type: "string" },
                  jobUrl: { type: "string" },
                  locationCountry: { type: "string" },
                  locationRegion: { type: "string" },
                  contractType: { type: "string" },
                  skillsRequired: { type: "array", items: { type: "string" } },
                  dateFetched: { type: "string" },
                  salary: { type: "string" },
                  emails: { type: "array", items: { type: "string" } },
                  isExisting: { type: "boolean" },
                },
              },
            },
            total: { type: "number" },
            page: { type: "number" },
            pageSize: { type: "number" },
          },
        },
        500: {
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },
    handler: async (request, reply) => {
      const { t } = request;
      const { embedder } = fastify;
      let {
        page = 1,
        pageSize = 10,
        country,
        regions = [],
        contract_type,
        search = "",
        company_id,
      } = request.query as {
        page: number;
        pageSize: number;
        country?: string;
        regions?: string[];
        contract_type?: string;
        search?: string;
        company_id?: number;
      };

      try {
        search = search.trim();

        let whereClause = sql`TRUE`;

        if (country && regions && regions.length > 0) {
          const clauseA = eq(allJobs.locationCountry, country);
          const clauseB = inArray(allJobs.locationRegion, regions);
          whereClause = and(clauseA, clauseB) ?? clauseA;
        } else if (country) {
          whereClause = eq(allJobs.locationCountry, country);
        } else if (regions && regions.length > 0) {
          whereClause = inArray(allJobs.locationRegion, regions);
        }

        const existingProposals = await db
          .select({ jobId: jobsProposals.jobId })
          .from(jobsProposals)
          .innerJoin(allJobs, eq(allJobs.id, jobsProposals.jobId))
          .where(whereClause);

        const excludedIds = existingProposals.map((p) => p.jobId);

        const must = buildMust(country, regions, contract_type, company_id);

        let embedding: number[] = [];
        if (search) {
          const output = (await embedder(search, {
            pooling: "mean",
            normalize: true,
          } as any)) as Tensor;

          embedding = Array.from(output.data);
        }

        const { query, minScore } = buildQuery(
          must,
          search,
          embedding,
          excludedIds
        );

        const from = (page - 1) * pageSize;

        const esResponse = await clientElasticSearch.search({
          index: "all_jobs",
          from,
          size: pageSize,
          min_score: minScore,
          _source: [
            "id",
            "company_id",
            "job_title",
            "job_url",
            "location_country",
            "location_region",
            "contract_type",
            "salary",
            "skills_required",
            "update_date",
            "is_existing",
          ],
          body: { query },
        });

        const total =
          typeof esResponse.hits.total === "number"
            ? esResponse.hits.total
            : esResponse.hits.total?.value ?? 0;

        const esJobs = esResponse.hits.hits.map((hit: any) => ({
          id: hit._source.id,
          companyId: hit._source.company_id,
          jobTitle: hit._source.job_title,
          jobUrl: hit._source.job_url,
          locationCountry: hit._source.location_country,
          locationRegion: hit._source.location_region,
          contractType: hit._source.contract_type,
          salary: hit._source.salary,
          skillsRequired: hit._source.skills_required,
          emails: hit._source.emails,
          dateFetched: hit._source.update_date
            ? new Date(hit._source.update_date).toLocaleString("en-GB", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              })
            : null,
          isExisting: hit._source.is_existing,
        }));

        const companyIds = [...new Set(esJobs.map((j) => j.companyId))];

        let companyMap: Record<number, any> = {};
        if (companyIds.length > 0) {
          const companiesData = await db
            .select({
              id: companies.id,
              name: companies.name,
              emails: companies.emails,
            })
            .from(companies)
            .where(inArray(companies.id, companyIds));

          companyMap = companiesData.reduce(
            (acc, c) => ({ ...acc, [c.id]: c }),
            {}
          );
        }

        const jobs = esJobs.map((job) => ({
          ...job,
          company: companyMap[job.companyId]?.name ?? "Unknown",
          emails: companyMap[job.companyId]?.emails ?? [],
        }));

        return reply.status(200).send({
          jobs,
          total,
          page,
          pageSize,
        });
      } catch (error) {
        console.error("Error fetching jobs:", error);
        return reply.status(500).send({
          message: t("jobs.jobsFetchFailed"),
        });
      }
    },
  });

  fastify.get("/all-companies", {
    schema: {
      description: "Get list of all companies",
      tags: ["Jobs"],
      response: {
        200: {
          type: "array",
          items: {
            type: "object",
            properties: {
              id: { type: "number" },
              name: { type: "string" },
            },
            required: ["id", "name"],
          },
        },
        500: {
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },
    handler: async (request, reply) => {
      const { t } = request;

      try {
        const dbCompanies = await db
          .select({
            id: companies.id,
            name: companies.name,
          })
          .from(companies)
          .orderBy(companies.name);

        return reply.status(200).send(dbCompanies);
      } catch (error) {
        console.error("Error fetching companies:", error);
        return reply.status(500).send({
          message: t("companies.companiesFetchFailed"),
        });
      }
    },
  });

  fastify.get("/applied-or-not-interested", {
    schema: {
      description:
        "Fetch jobs by status (applied or not_interested) from PostgreSQL",
      tags: ["Jobs"],
      querystring: {
        type: "object",
        properties: {
          status: {
            type: "string",
            enum: ["applied", "not_interested"],
            description: "Job proposal status to filter by",
          },
          page: { type: "number", minimum: 1, default: 1 },
          pageSize: { type: "number", minimum: 1, maximum: 50, default: 10 },
          country: { type: "string" },
          regions: { type: "array", items: { type: "string" } },
          contract_type: { type: "string" },
          search: { type: "string" },
        },
        required: ["status"],
      },
      response: {
        200: {
          type: "object",
          properties: {
            jobs: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  id: { type: "number" },
                  company: { type: "string" },
                  companyId: { type: "number" },
                  jobTitle: { type: "string" },
                  jobUrl: { type: "string" },
                  locationCountry: { type: "string" },
                  locationRegion: { type: "string" },
                  contractType: { type: "string" },
                  dateFetched: { type: "string" },
                  skillsRequired: { type: "array", items: { type: "string" } },
                  emails: { type: "array", items: { type: "string" } },
                  salary: { type: "string" },
                  isExisting: { type: "boolean" },
                  status: {
                    type: "string",
                    enum: ["applied", "not_interested"],
                  },
                },
              },
            },
            total: { type: "number" },
            page: { type: "number" },
            pageSize: { type: "number" },
          },
        },
        500: {
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },
    handler: async (request, reply) => {
      const { t } = request;
      const { db } = fastify;

      const {
        status,
        page = 1,
        pageSize = 10,
        country,
        regions = [],
        contract_type,
        search = "",
      } = request.query as {
        status: "applied" | "not_interested";
        page: number;
        pageSize: number;
        country?: string;
        regions?: string[];
        contract_type?: ContractType;
        search?: string;
      };
      
      try {
        const offset = (page - 1) * pageSize;

        let whereClause = eq(jobsProposals.status, status);

        const filters: any[] = [whereClause];

        if (country) filters.push(eq(allJobs.locationCountry, country));
        if (regions.length > 0)
          filters.push(inArray(allJobs.locationRegion, regions));
        if (contract_type)
          filters.push(eq(allJobs.contractType, contract_type));
        if (search && search.trim().length > 0) {
          filters.push(ilike(allJobs.jobTitle, `%${search}%`));
        }

        const finalWhere = and(...filters);

        const jobs = await db
          .select({
            id: allJobs.id,
            companyId: companies.id,
            company: companies.name,
            website: companies.website,
            emails: companies.emails,
            jobTitle: allJobs.jobTitle,
            jobUrl: allJobs.jobUrl,
            skillsRequired: allJobs.skillsRequired,
            locationCountry: allJobs.locationCountry,
            locationRegion: allJobs.locationRegion,
            contractType: allJobs.contractType,
            salary: allJobs.salary,
            status: jobsProposals.status,
          })
          .from(jobsProposals)
          .innerJoin(allJobs, eq(allJobs.id, jobsProposals.jobId))
          .innerJoin(companies, eq(allJobs.companyId, companies.id))
          .where(finalWhere)
          .limit(pageSize)
          .offset(offset);

        const [{ count }] = await db
          .select({ count: sql<number>`COUNT(*)` })
          .from(jobsProposals)
          .innerJoin(allJobs, eq(allJobs.id, jobsProposals.jobId))
          .where(finalWhere);

        return reply.code(200).send({
          jobs,
          total: Number(count),
          page,
          pageSize,
        });
      } catch (error) {
        console.error("Error fetching applied/not_interested jobs:", error);
        return reply.code(500).send({
          message: t("jobs.jobsFetchFailed"),
        });
      }
    },
  });

  fastify.post("/status-job", {
    schema: {
      description: "Save status job as applied or not interested",
      tags: ["Jobs"],
      body: {
        type: "object",
        properties: {
          jobId: { type: "number", description: "Job Id" },
          status: { type: "string", enum: ["applied", "not_interested"] },
        },
        required: ["jobId", "status"],
      },
      response: {
        201: {
          type: "object",
          properties: {
            message: { type: "string" },
          },
        },
        500: {
          description: "Server error",
          type: "object",
          properties: {
            message: { type: "string" },
          },
        },
      },
    },

    handler: async (request, reply) => {
      const { jobId, status } = request.body as {
        jobId: number;
        status: "applied" | "not_interested";
      };
      const { t } = request;

      try {
        await db.transaction(async (tx) => {
          const existing = await tx
            .select()
            .from(jobsProposals)
            .where(eq(jobsProposals.jobId, Number(jobId)));

          if (existing.length > 0) {
            await tx
              .update(jobsProposals)
              .set({
                status
              })
              .where(eq(jobsProposals.jobId, Number(jobId)));
          } else {
            await tx.insert(jobsProposals).values({
              jobId: Number(jobId),
              status,
            });
          }
        });

        return reply
          .status(201)
          .send({ message: t("jobs.jobStatusSuccess", { status }) });
      } catch (error) {
        console.error("Transaction failed:", error);
        return reply.status(500).send({ message: t("jobs.jobStatusError") });
      }
    },
  });
}
