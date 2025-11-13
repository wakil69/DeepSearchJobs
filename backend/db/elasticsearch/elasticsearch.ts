import { Client } from "@elastic/elasticsearch";
import * as dotenv from "dotenv";
import * as path from "path";

dotenv.config({ path: path.resolve(__dirname, ".env") });

const clientElasticSearch = new Client({
  node:
    process.env.NODE_ENV === "production"
      ? "http://elasticsearch:9200"
      : "http://localhost:9200",
  auth: {
    username: "elastic",
    password: process.env.ELASTIC_PASSWORD ?? "admin",
  },
});

export default clientElasticSearch;
