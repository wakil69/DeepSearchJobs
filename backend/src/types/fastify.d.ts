import "fastify";
import type { pipeline } from "@xenova/transformers";

declare module "fastify" {
  interface FastifyInstance {
    t: (key: string, options?: any) => string;
    db: ReturnType<typeof import("../db/drizzle/drizzle").db>;
    embedder: Awaited<ReturnType<typeof pipeline>>;
    rabbitmq: {
      connection: Connection;
      channel: Channel;
      publish: (queue: string, message: any) => Promise<void>;
    };
  }

  interface FastifyRequest {
    t: (key: string, options?: any) => string;
    db: ReturnType<typeof import("../db/drizzle/drizzle").db>;
    file: () => Promise<MultipartFile>;
    files: () => AsyncIterableIterator<MultipartFile>;
  }
}
