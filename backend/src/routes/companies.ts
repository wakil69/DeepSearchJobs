import { FastifyInstance } from "fastify";
import { and, eq, ilike, inArray, sql, or } from "drizzle-orm";
import { db } from "../../db/drizzle/drizzle";
import { allJobs, companies } from "../../db/drizzle/schema";
import ExcelJS from "exceljs";
import Papa from "papaparse";

export async function companiesRoutes(fastify: FastifyInstance) {
  fastify.post("/", {
    schema: {
      description: "Import companies from a CSV or XLSX file",
      consumes: ["multipart/form-data"],
      tags: ["Companies"],
      response: {
        200: {
          type: "object",
          properties: {
            message: { type: "string" },
            importedCount: { type: "number" },
          },
        },
        400: {
          type: "object",
          properties: { message: { type: "string" } },
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

      try {
        const uploaded = await request.file();
        if (!uploaded) {
          return reply
            .status(400)
            .send({ message: t("companies.noFileUploaded") });
        }
        const rawBuffer = await uploaded.toBuffer();
        const fileBuffer = rawBuffer as unknown as Buffer;
        const fileName = uploaded.filename.toLowerCase();

        let parsedData: any[] = [];

        if (fileName.endsWith(".csv")) {
          const csvText = fileBuffer.toString("utf-8");
          parsedData = Papa.parse(csvText, { header: true }).data;
        } else if (fileName.endsWith(".xlsx")) {
          const workbook = new ExcelJS.Workbook();
          // @ts-expect-error Fastify multipart typing mismatch (https://github.com/exceljs/exceljs/issues/2877); runtime value is fine
          await workbook.xlsx.load(fileBuffer);
          const sheet = workbook.worksheets[0];
          const headers = sheet.getRow(1).values as string[];

          parsedData = [];
          sheet.eachRow((row, rowNumber) => {
            if (rowNumber === 1) return; // skip headers
            const rowValues = row.values as string[];
            const record: any = {};
            headers.forEach((header, i) => {
              if (typeof header === "string") {
                record[header.trim()] = rowValues[i] ?? "";
              }
            });
            parsedData.push(record);
          });
        } else {
          return reply
            .status(400)
            .send({ message: t("companies.unsupportedFileType") });
        }

        const formattedCompanies = parsedData
          .map((row: any) => {
            const normalizedRow: Record<string, any> = {};
            for (const key in row) {
              if (key) {
                const normalizedKey = key
                  .toLowerCase()
                  .replace(/\s+/g, "")
                  .replace(/_/g, "");
                normalizedRow[normalizedKey] = row[key];
              }
            }

            return {
              name: normalizedRow.name?.trim(),
              website: (() => {
                const w = normalizedRow.website;
                if (!w) return null;

                if (typeof w === "object" && w.hyperlink) {
                  return w.hyperlink.trim();
                }

                if (typeof w === "object" && w.text) {
                  return w.text.trim();
                }

                if (typeof w === "string") {
                  return w.trim();
                }

                return null;
              })(),
              internalJobListingPages: normalizedRow.internaljoblistingpages
                ? String(normalizedRow.internaljoblistingpages)
                    .split(",")
                    .map((p: string) => p.trim())
                    .filter(Boolean)
                : [],
              externalJobListingPages: normalizedRow.externaljoblistingpages
                ? String(normalizedRow.externaljoblistingpages)
                    .split(",")
                    .map((p: string) => p.trim())
                    .filter(Boolean)
                : [],
              emails: normalizedRow.emails
                ? String(normalizedRow.emails)
                    .split(",")
                    .map((e: string) => e.trim())
                    .filter(Boolean)
                : [],
              creationDate: new Date(),
            };
          })
          .filter((c) => c.name);

        const importedCount = await db.transaction(async (tx: typeof db) => {
          let count = 0;
          for (const company of formattedCompanies) {
            const exists = await tx
              .select()
              .from(companies)
              .where(eq(companies.name, company.name));

            if (exists.length === 0) {
              await tx.insert(companies).values(company);
              count++;
            }
          }
          return count;
        });

        return reply.status(200).send({
          message: t("companies.importSuccess", { count: importedCount }),
          importedCount,
        });
      } catch (err) {
        console.error("Error importing companies:", err);
        return reply.status(500).send({
          message: t("companies.importError"),
        });
      }
    },
  });

  fastify.get("/", {
    schema: {
      description: "Get list of companies with Redis job statuses",
      tags: ["Companies"],
      querystring: {
        type: "object",
        properties: {
          page: { type: "number", minimum: 1, default: 1 },
          pageSize: { type: "number", minimum: 1, maximum: 100, default: 10 },
          search: { type: "string", description: "Filter by company name" },
          statusFilter: {
            type: "string",
            description: "Filter by company process status",
          },
        },
      },
      response: {
        200: {
          type: "object",
          properties: {
            companies: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  id: { type: "number" },
                  name: { type: "string" },
                  website: { type: "string" },
                  internalJobListingPages: {
                    type: "array",
                    items: { type: "string" },
                  },
                  externalJobListingPages: {
                    type: "array",
                    items: { type: "string" },
                  },
                  emails: { type: "array", items: { type: "string" } },
                  numberJobs: { type: "number" },
                  lastCheckedDate: { type: ["string", "null"] },
                  status: { type: "string" },
                },
                required: ["id", "name"],
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
      const {
        page = 1,
        pageSize = 10,
        search,
        statusFilter,
      } = request.query as {
        page: number;
        pageSize: number;
        search?: string;
        statusFilter?: string;
      };

      const offset = (page - 1) * pageSize;
      const { redis } = fastify;
      const { t } = request;

      try {
        let companyIdsFromRedis: number[] = [];

        if (statusFilter) {
          const prefixes = ["company_jobs:", "check_jobs:"];

          for (const prefix of prefixes) {
            const keys = await redis.keys(`${prefix}*`);
            for (const key of keys) {
              const value = await redis.hget(key, "status");
              if (value === statusFilter) {
                const id = parseInt(key.replace(prefix, ""), 10);
                if (!Number.isNaN(id)) companyIdsFromRedis.push(id);
              }
            }
          }

          if (companyIdsFromRedis.length === 0) {
            return reply.status(200).send({
              companies: [],
              total: 0,
              page,
              pageSize,
            });
          }
        }

        const filters = [sql`TRUE`];

        if (search?.trim()) {
          filters.push(ilike(companies.name, `%${search.trim()}%`));
        }

        if (companyIdsFromRedis.length > 0) {
          filters.push(inArray(companies.id, companyIdsFromRedis));
        }

        const [{ count }] = await db
          .select({ count: sql<number>`COUNT(DISTINCT ${companies.id})` })
          .from(companies)
          .leftJoin(
            allJobs,
            and(
              eq(allJobs.companyId, companies.id),
              eq(allJobs.isExisting, true)
            )
          )
          .where(sql.join(filters, sql` AND `));

        const dbCompanies = await db
          .select({
            id: companies.id,
            name: companies.name,
            website: companies.website,
            internalJobListingPages: companies.internalJobListingPages,
            externalJobListingPages: companies.externalJobListingPages,
            emails: companies.emails,
            numberJobs: sql<number>`COUNT(${allJobs.id})`,
            lastCheckedDate: companies.updateDate,
          })
          .from(companies)
          .leftJoin(
            allJobs,
            and(
              eq(allJobs.companyId, companies.id),
              eq(allJobs.isExisting, true)
            )
          )
          .where(sql.join(filters, sql` AND `))
          .groupBy(companies.id)
          .orderBy(companies.name)
          .limit(pageSize)
          .offset(offset);

        const companiesWithStatus = await Promise.all(
          dbCompanies.map(async (company) => {
            const analyseStatus = await redis.hget(`company_jobs:${company.id}`, "status");
            const checkStatus = await redis.hget(`check_jobs:${company.id}`, "status");

            const analyseStartedAt = await redis.hget(`company_jobs:${company.id}`, "started_at");
            const checkStartedAt = await redis.hget(`check_jobs:${company.id}`, "started_at");

            const analyseTime = analyseStartedAt ? new Date(analyseStartedAt) : null;
            const checkTime = checkStartedAt ? new Date(checkStartedAt) : null;

            let status;

            if (analyseTime && checkTime) {
              status = analyseTime >= checkTime ? analyseStatus : checkStatus;
            } else if (analyseTime) {
              status = analyseStatus;
            } else if (checkTime) {
              status = checkStatus;
            } else {
              status = "idle";
            }
            
            const formattedDate = company.lastCheckedDate
              ? new Date(company.lastCheckedDate).toLocaleString("en-GB", {
                  year: "numeric",
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : null;

            return { ...company, lastCheckedDate: formattedDate, status };
          })
        );

        return reply.status(200).send({
          companies: companiesWithStatus,
          total: Number(count),
          page,
          pageSize,
        });
      } catch (error) {
        console.error("Error fetching companies:", error);
        return reply.status(500).send({
          message: t("companies.companiesFetchFailed"),
        });
      }
    },
  });

  fastify.put("/company", {
    schema: {
      description: "Update company information",
      tags: ["Companies"],
      body: {
        type: "object",
        properties: {
          id: { type: "number", description: "Company Id" },
          name: { type: "string", description: "Company Name" },
          website: { type: "string", description: "Company Website" },
          emails: {
            type: "array",
            items: { type: "string" },
            description: "Associated Emails",
          },
          internalJobListingPages: {
            type: "array",
            items: { type: "string" },
            description: "Internal Job Listing Pages",
          },
          externalJobListingPages: {
            type: "array",
            items: { type: "string" },
            description: "External Job Listing Pages",
          },
        },
        required: ["id", "name"],
      },
      response: {
        200: {
          type: "object",
          properties: {
            message: { type: "string" },
          },
        },
        404: {
          description: "Company not found",
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
      const {
        id,
        name,
        website,
        emails,
        internalJobListingPages,
        externalJobListingPages,
      } = request.body as {
        id: number;
        name: string;
        website?: string;
        emails?: string[];
        internalJobListingPages?: string[];
        externalJobListingPages?: string[];
      };

      const { t } = request;

      try {
        await db.transaction(async (tx) => {
          const existing = await tx
            .select()
            .from(companies)
            .where(eq(companies.id, id));

          if (existing.length === 0) {
            reply.status(404).send({ message: t("companies.companyNotFound") });
            return;
          }

          await tx
            .update(companies)
            .set({
              name,
              website,
              emails: emails ?? [],
              internalJobListingPages: internalJobListingPages ?? [],
              externalJobListingPages: externalJobListingPages ?? [],
              updateDate: new Date(),
            })
            .where(eq(companies.id, id));
        });

        return reply.status(200).send({
          message: t("companies.companyUpdateSuccess", { name }),
        });
      } catch (error) {
        console.error("Error updating company:", error);
        return reply
          .status(500)
          .send({ message: t("companies.companyUpdateError") });
      }
    },
  });

  fastify.delete("/", {
    schema: {
      description: "Delete companies by IDs",
      tags: ["Companies"],
      body: {
        type: "object",
        properties: {
          ids: {
            type: "array",
            items: { type: "number" },
            description: "IDs of companies to delete",
          },
        },
        required: ["ids"],
      },
      response: {
        200: {
          type: "object",
          properties: { message: { type: "string" } },
        },
        400: {
          description: "Bad Request",
          type: "object",
          properties: { message: { type: "string" } },
        },
        404: {
          description: "Companies not found",
          type: "object",
          properties: { message: { type: "string" } },
        },
        500: {
          description: "Server error",
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },

    handler: async (request, reply) => {
      const { ids } = request.body as { ids: number[] };
      const { t } = request;

      if (!ids.length) {
        return reply.status(400).send({
          message: t("companies.noIdsProvided"),
        });
      }

      try {
        const deletedCount = await db.transaction(async (tx) => {
          const existing = await tx
            .select()
            .from(companies)
            .where(inArray(companies.id, ids));

          if (existing.length === 0) return 0;

          await tx.delete(companies).where(inArray(companies.id, ids));
          return existing.length;
        });

        if (deletedCount === 0) {
          return reply
            .status(404)
            .send({ message: t("companies.companyNotFound") });
        }

        return reply.status(200).send({
          message: t("companies.companiesDeleteSuccess", {
            count: deletedCount,
          }),
        });
      } catch (error) {
        console.error("Error deleting companies:", error);
        return reply
          .status(500)
          .send({ message: t("companies.companiesDeleteError") });
      }
    },
  });

  fastify.post("/queue-companies", {
    schema: {
      description: "Queue company jobs (analyse or check)",
      tags: ["Companies"],
      body: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: ["analyse", "check"],
            description: "Type of job to queue",
          },
          ids: {
            type: "array",
            items: { type: "number" },
            minItems: 1,
            description: "Company IDs to queue",
          },
        },
        required: ["type", "ids"],
      },
      response: {
        200: {
          type: "object",
          properties: {
            message: { type: "string" },
            queued: { type: "array", items: { type: "number" } },
          },
        },
        400: {
          type: "object",
          properties: { message: { type: "string" } },
        },
        500: {
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },
    handler: async (request, reply) => {
      const { redis, rabbitmq } = fastify;
      const { t } = request;
      const { type, ids } = request.body as {
        type: "analyse" | "check";
        ids: number[];
      };

      try {
        if (type === "check") {
          const companiesWithPages = await db
            .select({
              id: companies.id,
              name: companies.name,
            })
            .from(companies)
            .where(
              and(
                inArray(companies.id, ids),
                or(
                  sql`array_length(internal_job_listing_pages, 1) IS NOT NULL AND array_length(internal_job_listing_pages, 1) > 0`,
                  sql`array_length(external_job_listing_pages, 1) IS NOT NULL AND array_length(external_job_listing_pages, 1) > 0`
                )
              )
            );

          const validIds = companiesWithPages.map((c) => c.id);

          const invalidCompanies = await db
            .select({
              id: companies.id,
              name: companies.name,
            })
            .from(companies)
            .where(
              inArray(
                companies.id,
                ids.filter((id) => !validIds.includes(id))
              )
            );

          if (invalidCompanies.length > 0) {
            const invalidNames = invalidCompanies.map((c) => c.name).join(", ");

            return reply.status(400).send({
              message: t("companies.noJobPagesFound", {
                count: invalidCompanies.length,
                names: invalidNames,
              }),
            });
          }
        }

        const queue = type === "analyse" ? "company_jobs" : "check_jobs";

        const companiesToQueue = await db
          .select({
            id: companies.id,
            name: companies.name,
          })
          .from(companies)
          .where(inArray(companies.id, ids));

        for (const company of companiesToQueue) {
          await rabbitmq.publish(queue, {
            company_id: company.id,
            company_name: company.name,
          });
          await redis.hset(`${queue}:${company.id}`, {
            status: "queued",
            retries: 0,
            started_at: new Date().toISOString()
          });
        }

        const messageKey =
          type === "analyse"
            ? "companies.companiesQueued"
            : "companies.jobsQueued";

        return reply.status(200).send({
          message: t(messageKey, { count: ids.length }),
          queued: ids,
        });
      } catch (error: any) {
        console.error("Error queueing jobs:", error);
        return reply.status(500).send({
          message: t("companies.queueError"),
        });
      }
    },
  });

  fastify.get("/status", {
    schema: {
      description:
        "Get status of all company analysis and check jobs from Redis",
      tags: ["Companies"],
      response: {
        200: {
          type: "object",
          properties: {
            analyse: {
              type: "object",
              properties: {
                jobs: {
                  type: "array",
                  items: {
                    type: "object",
                    properties: {
                      id: { type: "number" },
                      status: { type: "string" },
                    },
                  },
                },
                total: { type: "number" },
              },
            },
            check: {
              type: "object",
              properties: {
                jobs: {
                  type: "array",
                  items: {
                    type: "object",
                    properties: {
                      id: { type: "number" },
                      status: { type: "string" },
                    },
                  },
                },
                total: { type: "number" },
              },
            },
            totalAll: { type: "number" },
          },
        },
        500: {
          type: "object",
          properties: { message: { type: "string" } },
        },
      },
    },

    handler: async (request, reply) => {
      const { redis } = fastify;
      const { t } = request;

      try {
        const prefixes = {
          analyse: "company_jobs:",
          check: "check_jobs:",
        };

        const fetchJobsByPrefix = async (prefix: string) => {
          const keys = await redis.keys(`${prefix}*`);
          const jobs = await Promise.all(
            keys.map(async (key) => {
              const status = await redis.hget(key, "status");
              const id = parseInt(key.replace(prefix, ""), 10);
              return { id, status: status ?? "unknown" };
            })
          );
          return { jobs, total: jobs.length };
        };

        const analyse = await fetchJobsByPrefix(prefixes.analyse);
        const check = await fetchJobsByPrefix(prefixes.check);

        const totalAll = analyse.total + check.total;

        return reply.status(200).send({
          analyse,
          check,
          totalAll,
        });
      } catch (error) {
        console.error(error as Error, "Error fetching job statuses");
        return reply
          .status(500)
          .send({ message: t("companies.statusFetchError") });
      }
    },
  });
}
