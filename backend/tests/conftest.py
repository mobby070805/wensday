"""Shared fixtures. Every test app runs against an in-memory SQLite DB with no network:
LLM chain = offline only, reminder worker off, collaborators injected where a test needs them."""
from __future__ import annotations

import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

API = "/api/v1"


def make_settings(**overrides) -> Settings:
    base = dict(database_url="sqlite+aiosqlite:///:memory:", reminder_worker=False, llm_chain=["offline"],
                jwt_secret="test-secret-test-secret-test-secret-32b", env="test", rate_limit_per_minute=100000)
    base.update(overrides)
    return Settings(**base)


@contextmanager
def running(**kw):
    """Context manager yielding a live TestClient. kw: settings overrides + injected collaborators."""
    inject = {k: kw.pop(k) for k in ("llm", "http", "stt", "tts", "mailer") if k in kw}
    with TestClient(create_app(make_settings(**kw), **inject)) as c:
        yield c


@pytest.fixture
def client():
    with running() as c:
        yield c


class Person:
    def __init__(self, client: TestClient, email: str, name: str):
        self.c, self.email, self.name = client, email, name
        r = client.post(f"{API}/auth/register", json={"email": email, "password": "password123", "name": name})
        assert r.status_code == 201, r.text
        self.tokens = r.json()
        self.h = {"Authorization": f"Bearer {self.tokens['access_token']}"}
        self.id = client.get(f"{API}/auth/me", headers=self.h).json()["id"]
        self.cid: str | None = None

    def get(self, path, **kw):
        return self.c.get(API + path, headers=self.h, **kw)

    def post(self, path, json=None, **kw):
        return self.c.post(API + path, json=json, headers=self.h, **kw)

    def patch(self, path, json=None):
        return self.c.patch(API + path, json=json, headers=self.h)

    def put(self, path, json=None):
        return self.c.put(API + path, json=json, headers=self.h)

    def delete(self, path):
        return self.c.delete(API + path, headers=self.h)

    def say(self, text: str, **kw) -> dict:
        """One chat turn, continuing this person's conversation."""
        r = self.post("/chat", {"text": text, "conversation_id": self.cid, **kw})
        assert r.status_code == 200, r.text
        out = r.json()
        self.cid = out["conversation_id"]
        return out


@pytest.fixture
def madesh(client) -> Person:
    return Person(client, "madesh@example.com", "Madesh")


def tamil_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(1 for c in letters if "஀" <= c <= "௿") / len(letters) if letters else 0.0


def has_tamil(s: str) -> bool:
    return bool(re.search(r"[஀-௿]", s))
