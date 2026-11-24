# 0004: Hybrid retrieval in pgvector

## Decision
Requirement documents are split at each `## ` heading, embedded, and stored in a PostgreSQL table with a pgvector column. For a story, retrieval returns:
1. every section whose requirement id the story names (exact match),
2. every section of the API reference, since no test can be written without the endpoints,
3. the k nearest other sections by cosine distance, to bring in related requirements the story does not name (a late-fee story also needs the loan period).

## Options considered
- **Vector search only.** Can miss a requirement the story explicitly names, which would leave it untested.
- **A separate vector database** (Chroma, Pinecone). Another service to run, back up and keep in sync, for about thirty chunks.
- **pgvector in the existing PostgreSQL (chosen).** One database, joins with the rest of the data, and transactions.

## Trade-off
- One section per chunk works because requirement sections are short. Long documents would need a size-based split.
- Each row records which embedding model made it. Vectors from different models cannot be compared, so queries filter on it.
- Tests use a hashing embedder (shared words only) so they need no model; it retrieves worse than a real embedding model.
