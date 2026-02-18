import Fastify, {
  FastifyInstance,
  FastifyRequest,
  FastifyReply
} from "fastify";
import cors from "@fastify/cors";
import redis from "@fastify/redis";
import * as dotenv from "dotenv";
import fastifyCookie from "@fastify/cookie";
import { db } from "../db/drizzle/drizzle"; 
import i18nPlugin from "./plugins/i18n";
import embeddingsPlugin from "./plugins/embeddings";
import multipart from "@fastify/multipart";
import { companiesRoutes } from "./routes/companies";
import rabbitmq from "./plugins/rabbitmq";
import { jobsRoutes } from "./routes/jobs";
import fastifyQs from "fastify-qs";

dotenv.config();

const fastify: FastifyInstance = Fastify({
  logger: true,
});

const allowedOrigin =
  process.env.NODE_ENV === "production"
    ? "http://localhost:3000"
    : "http://localhost:5173";

fastify.register(cors, {
  origin: allowedOrigin,
  methods: ["GET", "PUT", "POST", "DELETE", "OPTIONS"],
  credentials: true,
});

fastify.register(fastifyCookie);

fastify.register(multipart, {
  attachFieldsToBody: false, // file is accessible with request.file()
});

fastify.register(fastifyQs, {})

fastify.register(rabbitmq);

fastify.register(i18nPlugin);

fastify.register(embeddingsPlugin);

fastify.decorate("db", db);

const redisOrgin =
  process.env.NODE_ENV === "production" ? "redis" : "localhost";

fastify.register(redis, {
  host: redisOrgin,
  port: 6379,
  ...(process.env.NODE_ENV === "production" && {
    password: process.env.REDIS_PASSWORD,
  }),
});

if (process.env.NODE_ENV === "development") {
  fastify.register(require("@fastify/swagger"), {
    openapi: {
      openapi: "3.0.0",
      info: {
        title: "Swagger Backend Client - Play2Path - DeepSearchJobs",
        description: "Swagger Backend Client API - Play2Path - DeepSearchJobs",
        version: "0.1.0",
      },
      servers: [
        {
          url: "http://localhost:4000",
          description: "Development server",
        },
      ],
      externalDocs: {
        url: "https://swagger.io",
        description: "Find more info here",
      },
    },
  });

  fastify.register(require("@fastify/swagger-ui"), {
    routePrefix: "/documentation",
    uiConfig: {
      docExpansion: "full",
      deepLinking: false,
    },
    uiHooks: {
      onRequest: function (
        request: FastifyRequest,
        reply: FastifyReply,
        next: (err?: Error) => void
      ) {
        next();
      },
      preHandler: function (
        request: FastifyRequest,
        reply: FastifyReply,
        next: (err?: Error) => void
      ) {
        next();
      },
    },
    staticCSP: true,
    transformStaticCSP: (header: string) => header,
    transformSpecification: (swaggerObject: any, request: any, reply: any) => {
      return swaggerObject;
    },
    transformSpecificationClone: true,
  });
}

// Routes
fastify.register(companiesRoutes, { prefix: "/companies" });
fastify.register(jobsRoutes, { prefix: "/jobs" });

const start = async () => {
  try {
    await fastify.listen({ port: 4000, host: "0.0.0.0" });
    console.log("Server listening on http://localhost:4000");
  } catch (err) {
    fastify.log.error(err);
    process.exit(1);
  }
};

start();
