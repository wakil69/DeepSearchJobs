import { drizzle } from "drizzle-orm/node-postgres";
import pkg from "pg";
import * as schema from "./schema";
import * as dotenv from "dotenv";
import path from "path";

dotenv.config({
  path: path.resolve(__dirname, "../.env"),
});

const { Pool } = pkg;

const isDev = process.env.NODE_ENV === "development";

const pool = new Pool({
  host: isDev ? process.env.PG_HOST_DEV : process.env.PG_HOST,
  port: Number(process.env.PG_PORT),
  user: isDev ? process.env.PG_USER_DEV : process.env.PG_USER,
  password: isDev ? process.env.PG_PASSWORD_DEV : process.env.PG_PASSWORD,
  database: isDev ? process.env.PG_DATABASE_DEV : process.env.PG_DATABASE,
});

console.log("Connected to Postgres:", {
  host: pool.options.host,
  port: pool.options.port,
  database: pool.options.database,
});

export const db = drizzle(pool, { schema });
export type Schema = typeof schema;
