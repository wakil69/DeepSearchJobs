import { estypes } from "@elastic/elasticsearch";

export const buildMust = (
  country?: string,
  regions?: string[],
  contract_type?: string,
  company_id?: number
): estypes.QueryDslQueryContainer[] => {
  const must: estypes.QueryDslQueryContainer[] = [
    { term: { is_existing: true } },
    { exists: { field: "job_title_vectors" } },
  ];

  if (country) {
    must.push({ terms: { "location_country.keyword": [country] } });
  }

  if (regions?.length) {
    must.push({ terms: { "location_region.keyword": regions } });
  }

  if (contract_type) {
    must.push({ terms: { "contract_type.keyword": [contract_type] } });
  }

  if (company_id) {
    must.push({ term: { company_id } });
  }

  return must;
};

export const buildQuery = (
  must: estypes.QueryDslQueryContainer[],
  search?: string,
  embedding?: number[],
  excludedIds: number[] = []
): { query: estypes.QueryDslQueryContainer; minScore?: number } => {
  const should: estypes.QueryDslQueryContainer[] = [];

  if (search && search.trim().length > 0) {
    should.push({
      multi_match: {
        query: search,
        fields: [
          "job_title^3",
          "job_description^2",
          "skills_required",
          "location_country",
          "location_region",
        ],
        fuzziness: "AUTO",
      },
    });
  }

  const hasEmbedding = Array.isArray(embedding) && embedding.length > 0;

  const scriptScoreFunction = hasEmbedding
    ? {
        script_score: {
          script: {
            source: `
              double cosine = cosineSimilarity(params.queryVector, 'job_title_vectors') + 1.0;
              double normalizedBM25 = Math.min(_score, 10.0) / 10.0 * 2.0;
              return (params.alpha * cosine) + (params.beta * normalizedBM25);
            `,
            params: {
              queryVector: embedding,
              alpha: 0.7,
              beta: 0.3,
            },
          },
        },
      }
    : {
        // fallback: pure BM25 score if no embedding
        weight: 1,
      };

  return {
    query: {
      function_score: {
        query: {
          bool: {
            must,
            should,
            minimum_should_match: should.length > 0 ? 1 : 0,
            must_not: excludedIds.length
              ? [{ terms: { id: excludedIds } }]
              : [],
          },
        },
        functions: [scriptScoreFunction],
        boost_mode: "replace",
      },
    },
    // apply a minScore only if we have embeddings or search
    minScore: hasEmbedding || should.length ? 1.1 : undefined,
  };
};
