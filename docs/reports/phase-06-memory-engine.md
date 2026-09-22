# Phase 6 — Memory engine · **92 %**

**Delivered** (`backend/app/memory`): structured preferences (name, language…) injected into every reply · episodic + long-term memories with embeddings, importance and access tracking · **recall** = 0.7·similarity + 0.2·importance + 0.1·recency(45-day half-life-style decay) · near-duplicate consolidation (cos ≥ 0.92 bumps importance instead of duplicating) · pruning of stale, unimportant, never-recalled episodic memories · explicit-fact extraction in all three languages (name, language preference, likes, "remember that… / … nyabagam vechuko") · privacy controls (list, forget one, forget all, export) · knowledge retrieval over documents, notes and memories with citations · document ingest (sentence-aware chunking, summary) · meeting summaries (LLM, or a multilingual heuristic offline) that can create tasks.

**Embeddings are language-aware**: Tanglish tokens are reduced to phonetic skeletons and lexicon concepts are added as features, so `nalaiku ≈ naalaiku ≈ tomorrow ≈ நாளை` with no network. Vector stores: in-process (rebuilt lazily from the DB) and Qdrant over REST (per-user filter asserted in tests). `OpenAICompatEmbedder` swaps in real embeddings (falls back to hashing on error).

**Tests:** `test_memory.py` 39 · plus recall/knowledge/isolation cases in `test_api.py`.

**Bugs found:** embedder used the *concept-word* list as stop-words and discarded "meeting/remind/tomorrow" (zero vectors) · "call me later" was learned as the user's name · `amma` fuzzy-matched `aama`.

**Gaps:** the hashing embedder is lexical + concept-based, **not semantically deep** — paraphrases without shared words won't match; use a real embedding model for production quality (`EMBEDDING_PROVIDER=openai_compat`, untested against a real endpoint) · no scheduled pruning job yet (the function exists) · no reflection/summarisation of old memories · Qdrant path untested against a real server.

---

## Addendum — Production Completion Mode: real persistence proof

**Found:** every memory-engine test used `sqlite+aiosqlite:///:memory:`, which lives entirely in RAM. That proves the engine works *while the connection is open* — it cannot prove data written by a user survives a reconnect, which is the actual meaning of "verify memory persistence" for an assistant a user expects to remember things across sessions.

**Tests added:** two tests in `tests/test_memory.py` use a real file on disk. The first writes a user, a preference, a semantic memory, a task, a reminder and a conversation message through one `Database` instance, disposes it entirely (simulating a process restart), opens a **second, independent** `Database` instance against the same file, and confirms every row is there with correct values — including confirming the (explicitly non-persistent) in-process vector index correctly rehydrates itself from the durable `Memory.embedding` column on first recall, rather than just asserting the row exists. The second test opens two independent `Database` instances against one shared file, standing in for two API replica pods sharing one production database, and confirms a write from one is visible from the other. Both passed on the first run (no defect found — the persistence design was already correct; this closes a *verification* gap, not a *code* gap).

Full memory suite after this addendum: **41/41 passing** (was 39).
