"""Memory engine: fact extraction, semantic recall, consolidation, decay, isolation, Qdrant adapter."""
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.timeutil import utcnow
from app.db import Database
from app.memory.embeddings import HashingEmbedder, cosine
from app.memory.engine import MemoryEngine
from app.memory.facts import extract_facts
from app.memory.knowledge import Knowledge, chunk_text, extractive_summary
from app.memory.vectorstore import InMemoryVectorStore, QdrantStore
from app.models import Conversation, Memory, Message, Preference, Reminder, Task, User


@pytest.fixture
async def env():
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.create_all()
    async with db.session() as s:
        u1, u2 = User(email="a@x.com", name="Madesh"), User(email="b@x.com", name="Other")
        s.add_all([u1, u2])
        await s.commit()
    yield db, u1, u2, MemoryEngine(HashingEmbedder(256), InMemoryVectorStore())
    await db.dispose()


# ------------------------------------------------------------------ fact extraction
@pytest.mark.parametrize("text,type_,value", [
    ("my name is madesh", "name", "Madesh"),
    ("call me Mads", "name", "Mads"),
    ("en peyar Madesh", "name", "Madesh"),
    ("ennai Mads nu koopidu", "name", "Mads"),
    ("என் பெயர் மதேஷ்", "name", "மதேஷ்"),
    ("speak in Tamil", "language", "ta"),
    ("english la pesu", "language", "en"),
    ("tanglish la pesunga", "language", "tanglish"),
    ("தமிழில் பேசு", "language", "ta"),
    ("I love filter coffee", "like", "filter coffee"),
    ("enaku filter coffee romba pidikkum", "like", "filter coffee"),
    ("எனக்கு பிரியாணி ரொம்ப பிடிக்கும்", "like", "பிரியாணி"),
    ("remember that my anniversary is 5 Dec", "remember", "my anniversary is 5 Dec"),
    ("amma birthday March 3 nyabagam vechuko", "remember", "amma birthday March 3"),
])
def test_fact_extraction_in_all_three_languages(text, type_, value):
    facts = extract_facts(text)
    assert facts and facts[0].type == type_ and facts[0].value == value


@pytest.mark.parametrize("text", ["nalaiku 9 mani meeting remind pannu", "what time is it", "hello", "call me later", "call me back", "call me tomorrow",
                                  "I like", "please call me", "Naa office poitu varen"])
def test_no_false_facts_from_ordinary_commands(text):
    assert extract_facts(text) == []


# ------------------------------------------------------------------ embeddings
async def test_embeddings_are_language_aware():
    e = HashingEmbedder(256)
    a, b, c, d = await e.embed(["nalaiku meeting", "naalaiku meeting", "tomorrow meeting", "filter coffee recipe"])
    assert cosine(a, b) > 0.8                       # Tanglish spelling variants are near-identical
    assert cosine(a, c) > cosine(a, d) + 0.3        # Tanglish "nalaiku" ≈ English "tomorrow" via shared concept
    ta, en = await e.embed(["நாளை மீட்டிங்", "tomorrow meeting"])
    assert cosine(ta, en) > 0.3                     # Tamil script joins the same concept space


async def test_embeddings_are_deterministic_and_normalised():
    e = HashingEmbedder(64)
    v1, v2 = (await e.embed(["Wensday remind"]))[0], (await e.embed(["Wensday remind"]))[0]
    assert v1 == v2 and abs(sum(x * x for x in v1) - 1) < 1e-9


# ------------------------------------------------------------------ engine
async def test_recall_ranks_relevant_first_across_languages(env):
    db, u1, _, eng = env
    async with db.session() as s:
        await eng.remember(s, u1.id, "The user likes filter coffee.", kind="fact", importance=0.7)
        await eng.remember(s, u1.id, "Reminder set for tomorrow's meeting with the client.", kind="fact", importance=0.7)
        await eng.remember(s, u1.id, "The user's sister lives in Coimbatore.", kind="fact", importance=0.7)
        top = await eng.recall(s, u1.id, "nalaiku meeting ninaivootu", k=3)
        assert top[0].memory.text.startswith("Reminder set for tomorrow")
        assert (await eng.recall(s, u1.id, "filter coffee", k=1))[0].memory.text == "The user likes filter coffee."


async def test_near_duplicates_are_consolidated_not_duplicated(env):
    db, u1, _, eng = env
    async with db.session() as s:
        m1 = await eng.remember(s, u1.id, "The user likes filter coffee.", kind="fact", importance=0.6)
        m2 = await eng.remember(s, u1.id, "The user likes filter coffee.", kind="fact", importance=0.6)
        assert m1.id == m2.id and m2.importance > 0.6
        assert len((await eng.recall(s, u1.id, "filter coffee", k=5))) == 1


async def test_unimportant_episodic_memory_is_not_stored_but_facts_always_are(env):
    db, u1, _, eng = env
    async with db.session() as s:
        assert await eng.remember(s, u1.id, "said hi", kind="episodic", importance=0.2) is None
        assert await eng.remember(s, u1.id, "said hi", kind="fact", importance=0.2) is not None


async def test_importance_breaks_similarity_ties(env):
    db, u1, _, eng = env
    async with db.session() as s:
        await eng.remember(s, u1.id, "Ravi is the client contact for quotations.", kind="fact", importance=0.45)
        await eng.remember(s, u1.id, "Priya is the client contact for invoices.", kind="fact", importance=0.95)
        top = await eng.recall(s, u1.id, "client contact", k=2)
        assert top[0].memory.text.startswith("Priya")


async def test_memories_never_leak_between_users(env):
    db, u1, u2, eng = env
    async with db.session() as s:
        await eng.remember(s, u1.id, "Madesh's locker code is 4821.", kind="fact", importance=0.9)
        assert await eng.recall(s, u2.id, "locker code") == []
        other = await eng.remember(s, u2.id, "Other's locker code is 1111.", kind="fact", importance=0.9)
        assert not await eng.forget(s, u1.id, other.id)            # cannot forget someone else's memory
        assert [r.memory.user_id for r in await eng.recall(s, u1.id, "locker code")] == [u1.id]


async def test_forget_removes_from_recall_and_index(env):
    db, u1, _, eng = env
    async with db.session() as s:
        m = await eng.remember(s, u1.id, "The user's password hint is blue.", kind="fact", importance=0.9)
        assert await eng.forget(s, u1.id, m.id)
        assert await eng.recall(s, u1.id, "password hint") == []
        assert not await eng.forget(s, u1.id, m.id)                # second forget is a no-op


async def test_prune_drops_only_stale_unimportant_unused_episodic_memories(env):
    db, u1, _, eng = env
    async with db.session() as s:
        old = utcnow() - timedelta(days=90)
        stale = await eng.remember(s, u1.id, "User walked to the market on a Tuesday.", importance=0.45)
        keep_important = await eng.remember(s, u1.id, "User signed the lease agreement for the flat.", importance=0.9)
        keep_fact = await eng.remember(s, u1.id, "User is allergic to peanuts.", kind="fact", importance=0.5)
        keep_used = await eng.remember(s, u1.id, "User attended the school reunion dinner.", importance=0.45)
        for m in (stale, keep_important, keep_fact, keep_used):
            m.created_at = old
        keep_used.access_count = 3
        await s.flush()
        assert await eng.prune(s, u1.id) == 1
        assert (await s.get(Memory, stale.id)).deleted_at is not None
        for m in (keep_important, keep_fact, keep_used):
            assert (await s.get(Memory, m.id)).deleted_at is None


async def test_learn_updates_preferences_and_user_name(env):
    db, _, _, eng = env
    async with db.session() as s:
        blank = User(email="c@x.com", name="")
        s.add(blank)
        await s.flush()
        facts = await eng.learn(s, blank, "my name is ravi")
        assert facts[0].type == "name" and blank.name == "Ravi"
        assert (await eng.preferences(s, blank.id))["name"] == "Ravi"
        await eng.learn(s, blank, "speak in tamil")
        assert (await eng.preferences(s, blank.id))["language"] == "ta"


async def test_index_can_be_rebuilt_from_the_database(env):
    db, u1, _, eng = env
    async with db.session() as s:
        await eng.remember(s, u1.id, "The user likes filter coffee.", kind="fact", importance=0.7)
        await s.commit()
    fresh = MemoryEngine(HashingEmbedder(256), InMemoryVectorStore())      # e.g. after a restart: empty index
    async with db.session() as s:
        assert (await fresh.recall(s, u1.id, "filter coffee"))[0].memory.text.endswith("filter coffee.")   # lazy hydration
        assert await fresh.reindex(s, u1.id) == 1


async def test_context_block_contains_prefs_and_relevant_memories(env):
    db, u1, _, eng = env
    async with db.session() as s:
        await eng.set_preference(s, u1.id, "language", "tanglish")
        await eng.remember(s, u1.id, "The user likes filter coffee.", kind="fact", importance=0.7)
        block = await eng.context_block(s, u1, "coffee")
        assert "language=tanglish" in block and "filter coffee" in block


# ------------------------------------------------------------------ Qdrant adapter (REST, mocked)
async def test_qdrant_store_scopes_every_search_to_the_user():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        calls.append((req.method, req.url.path, body))
        if req.method == "GET":
            return httpx.Response(404)
        if req.url.path.endswith("/points/search"):
            return httpx.Response(200, json={"result": [{"score": 0.9, "payload": {"_id": "m1", "user_id": "u1"}}]})
        return httpx.Response(200, json={"result": True})

    store = QdrantStore(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "http://qdrant:6333", "key", dim=4)
    await store.upsert("memories", "a" * 32, [0.1, 0.2, 0.3, 0.4], {"user_id": "u1"})
    hits = await store.search("memories", [0.1, 0.2, 0.3, 0.4], 3, {"user_id": "u1"})
    await store.delete("memories", "a" * 32)

    assert hits == [("m1", 0.9, {"_id": "m1", "user_id": "u1"})]
    created = [c for c in calls if c[0] == "PUT" and c[1] == "/collections/memories"]
    assert created and created[0][2]["vectors"] == {"size": 4, "distance": "Cosine"}
    search = next(c for c in calls if c[1].endswith("/points/search"))
    assert search[2]["filter"] == {"must": [{"key": "user_id", "match": {"value": "u1"}}]}
    assert any(c[1].endswith("/points/delete") for c in calls) and store.persistent


# ------------------------------------------------------------------ chunking / knowledge
def test_chunking_respects_size_and_overlaps_by_one_sentence():
    text = " ".join(f"Sentence number {i} has some words in it." for i in range(30))
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 3 and all(len(c) <= 260 for c in chunks)
    assert chunks[0].split(". ")[-1] in chunks[1]             # overlap: last sentence repeats


def test_extractive_summary_is_short_and_keeps_the_opening():
    text = "Quarterly revenue grew strongly this year. Cats are nice. The board approved the new hiring plan for engineering. Lunch is at noon."
    s = extractive_summary(text, 2)
    assert s.startswith("Quarterly revenue") and "hiring plan" in s and "Lunch" not in s


async def test_knowledge_search_spans_documents_notes_and_memories(env):
    db, u1, u2, eng = env
    k = Knowledge(eng.embedder)
    async with db.session() as s:
        await k.ingest(s, u1.id, "Lease", "The monthly rent is 25000 rupees. The lease ends in March.")
        s.add(__import__("app.models", fromlist=["Note"]).Note(user_id=u1.id, title="Trip", body="Book train tickets to Madurai for Pongal"))
        await eng.remember(s, u1.id, "The user's landlord is Mr Rao.", kind="fact", importance=0.8)
        await s.flush()
        assert (await k.search(s, u1.id, "monthly rent", k=1))[0].source == "document"
        assert (await k.search(s, u1.id, "madurai train tickets", k=1))[0].source == "note"
        assert (await k.search(s, u1.id, "who is my landlord", k=1))[0].source == "memory"
        assert await k.search(s, u2.id, "rent lease landlord") == []           # other users see nothing
        ans = await k.answer(s, u1.id, "monthly rent")
        assert "25000" in ans["answer"] and ans["citations"][0]["source"] == "document"


# ------------------------------------------------------------------ real on-disk persistence
# Every other test in this file uses sqlite+aiosqlite:///:memory:, which lives entirely in RAM
# and only proves "works while the connection is open" — it cannot prove data survives a
# reconnect. These tests use a real file on disk and a brand-new Database instance (a distinct
# engine/connection pool) to stand in for a process restart, which is what "verify memory
# persistence" actually has to mean for a personal assistant a user expects to remember things.
async def test_everything_wensday_remembers_survives_closing_and_reopening_the_database(tmp_path):
    db_file = tmp_path / "wensday.db"
    db1 = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    await db1.create_all()

    eng1 = MemoryEngine(HashingEmbedder(256), InMemoryVectorStore())
    async with db1.session() as s:
        user = User(email="madesh@example.com", name="Madesh", timezone="Asia/Kolkata")
        s.add(user)
        await s.flush()
        await eng1.set_preference(s, user.id, "language", "tanglish")
        await eng1.remember(s, user.id, "The user's landlord is Mr Rao.", kind="fact", importance=0.9)
        task = Task(user_id=user.id, title="Buy milk", priority=3)
        reminder = Reminder(user_id=user.id, title="Call client", due_at=utcnow() + timedelta(days=1))
        conv = Conversation(user_id=user.id, title="hello")
        s.add_all([task, reminder, conv])
        await s.flush()
        s.add(Message(user_id=user.id, conversation_id=conv.id, role="user", text="Wensday, nalaiku 9 mani meeting remind pannu."))
        await s.commit()
        user_id, task_id, reminder_id, conv_id = user.id, task.id, reminder.id, conv.id

    # simulate a process restart: dispose the first engine entirely, connect fresh from disk
    await db1.dispose()
    db2 = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")

    async with db2.session() as s:
        reloaded_user = await s.get(User, user_id)
        assert reloaded_user is not None and reloaded_user.email == "madesh@example.com" and reloaded_user.name == "Madesh"

        pref = (await s.execute(select(Preference).where(Preference.user_id == user_id, Preference.key == "language"))).scalars().one()
        assert pref.value == "tanglish"

        reloaded_task = await s.get(Task, task_id)
        assert reloaded_task.title == "Buy milk" and reloaded_task.priority == 3 and reloaded_task.status == "open"

        reloaded_reminder = await s.get(Reminder, reminder_id)
        assert reloaded_reminder.title == "Call client" and reloaded_reminder.status == "pending"

        messages = (await s.execute(select(Message).where(Message.conversation_id == conv_id))).scalars().all()
        assert len(messages) == 1 and "nalaiku 9 mani" in messages[0].text

        # the semantic index (InMemoryVectorStore) is explicitly NOT persistent on its own — this
        # proves the documented recovery path actually works: a fresh engine lazily rehydrates it
        # from the Memory rows' stored embeddings, which ARE durable, on first recall.
        eng2 = MemoryEngine(HashingEmbedder(256), InMemoryVectorStore())
        recalled = await eng2.recall(s, user_id, "landlord")
        assert recalled and recalled[0].memory.text == "The user's landlord is Mr Rao."

    await db2.dispose()


async def test_a_fact_learned_in_one_connection_is_visible_from_a_completely_separate_one(tmp_path):
    """Two independent Database instances against the same file stand in for two API replica
    pods talking to one shared production database."""
    db_file = tmp_path / "shared.db"
    writer = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    await writer.create_all()
    async with writer.session() as s:
        u = User(email="a@x.com")
        s.add(u)
        await s.commit()
        user_id = u.id

    reader = Database(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with reader.session() as s:
        assert (await s.get(User, user_id)) is not None

    await writer.dispose()
    await reader.dispose()
