# Phase 6 — Memory engine · **90 %**

**Delivered** (`backend/app/memory`): structured preferences (name, language…) injected into every reply · episodic + long-term memories with embeddings, importance and access tracking · **recall** = 0.7·similarity + 0.2·importance + 0.1·recency(45-day half-life-style decay) · near-duplicate consolidation (cos ≥ 0.92 bumps importance instead of duplicating) · pruning of stale, unimportant, never-recalled episodic memories · explicit-fact extraction in all three languages (name, language preference, likes, "remember that… / … nyabagam vechuko") · privacy controls (list, forget one, forget all, export) · knowledge retrieval over documents, notes and memories with citations · document ingest (sentence-aware chunking, summary) · meeting summaries (LLM, or a multilingual heuristic offline) that can create tasks.

**Embeddings are language-aware**: Tanglish tokens are reduced to phonetic skeletons and lexicon concepts are added as features, so `nalaiku ≈ naalaiku ≈ tomorrow ≈ நாளை` with no network. Vector stores: in-process (rebuilt lazily from the DB) and Qdrant over REST (per-user filter asserted in tests). `OpenAICompatEmbedder` swaps in real embeddings (falls back to hashing on error).

**Tests:** `test_memory.py` 39 · plus recall/knowledge/isolation cases in `test_api.py`.

**Bugs found:** embedder used the *concept-word* list as stop-words and discarded "meeting/remind/tomorrow" (zero vectors) · "call me later" was learned as the user's name · `amma` fuzzy-matched `aama`.

**Gaps:** the hashing embedder is lexical + concept-based, **not semantically deep** — paraphrases without shared words won't match; use a real embedding model for production quality (`EMBEDDING_PROVIDER=openai_compat`, untested against a real endpoint) · no scheduled pruning job yet (the function exists) · no reflection/summarisation of old memories · Qdrant path untested against a real server.
