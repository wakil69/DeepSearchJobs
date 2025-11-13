import { defineConfig } from "drizzle-kit";
import * as dotenv from "dotenv";

console.log("Current NODE_ENV:", process.env.NODE_ENV);

dotenv.config({ path: "../.env" });

const isDev = process.env.NODE_ENV === "development";

const dbCredentials = {
  host: (isDev ? process.env.PG_HOST_DEV : process.env.PG_HOST) || "localhost",
  port: Number(process.env.PG_PORT || 5432),
  user: (isDev ? process.env.PG_USER_DEV : process.env.PG_USER) || "admin",
  password: (isDev ? process.env.PG_PASSWORD_DEV : process.env.PG_PASSWORD) || "admin",
  database: (isDev ? process.env.PG_DATABASE_DEV : process.env.PG_DATABASE) || "play2path",
  ssl: false,
};

export default defineConfig({
  schema: isDev ? "schema.ts" : "schema.js",
  out: "migrations",
  dialect: "postgresql",
  dbCredentials,
});
