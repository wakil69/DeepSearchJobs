import fp from "fastify-plugin";
import { pipeline } from "@xenova/transformers";

export default fp(async (fastify) => {
  const embedder = await pipeline(
    "feature-extraction",
    "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
  );

  fastify.decorate("embedder", embedder);
});