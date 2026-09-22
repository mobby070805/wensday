# Wensday — Database reference

> Generated from the SQLAlchemy models (compiled for PostgreSQL) by `scripts/gen_docs.py` — do not edit by hand.

**Engines** PostgreSQL in production (`postgresql+asyncpg://…`), SQLite in development and tests (`sqlite+aiosqlite:///…`). Models use only portable types: 32-char hex string ids, `JSON` columns, naive-UTC `DateTime`.

**Conventions**
- Every user-owned row has `user_id` (FK → `users`, `ON DELETE CASCADE`); **every query is filtered by it** — there is no cross-user endpoint.
- Syncable tables carry `updated_at` (indexed) and `deleted_at` (tombstone). `DELETE` sets `deleted_at`; it never removes the row, so other devices can learn about the deletion.
- Timestamps are stored as **naive UTC**; the API converts to/from the user's timezone at the edge.
- Vector search: `memories.embedding` / `document_chunks.embedding` / `notes.embedding` hold JSON float arrays (source of truth, so the index can be rebuilt); Qdrant (collection `memories`, payload `{user_id}`) is the production index when `WENSDAY_QDRANT_URL` is set.

## Tables

| Table | Purpose |
|---|---|
| `users` | Accounts (email, name, timezone, language preference) |
| `conversations` | Conversation threads |
| `devices` | Registered devices / push tokens |
| `documents` | Uploaded documents for analysis / Q&A |
| `email_drafts` | Drafts and their send status (draft/sent/queued/discarded) |
| `events` | Calendar events (local + Google-synced) |
| `goals` | Goals |
| `memories` | Long-term + episodic memory with embeddings and importance |
| `notes` | Notes, meeting notes, summaries |
| `oauth_accounts` | Linked Google accounts; tokens **encrypted at rest** (Fernet) |
| `pending_actions` | Confirmation gate + multi-turn slot state (email send, 'when?' questions) |
| `plugin_settings` | Per-user plugin enablement, granted scopes, config |
| `preferences` | Structured key→value preferences (name, language, wake word…) |
| `refresh_tokens` | Refresh-token registry for rotation, logout and reuse detection |
| `reminders` | One-off and recurring reminders |
| `workflows` | Custom workflows (trigger + steps JSON) |
| `document_chunks` | Embedded chunks for retrieval |
| `messages` | Messages (role, text, detected language, intent) |
| `milestones` | Goal milestones |
| `tasks` | To-dos |
| `workflow_runs` | Workflow execution logs |

## DDL (PostgreSQL)

```sql
CREATE TABLE users (
	email VARCHAR(320) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(255), 
	timezone VARCHAR(64) NOT NULL, 
	language VARCHAR(16) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_users_updated_at ON users (updated_at);

CREATE TABLE conversations (
	title VARCHAR(200) NOT NULL, 
	lang VARCHAR(16) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_conversations_updated_at ON conversations (updated_at);
CREATE INDEX ix_conversations_user_id ON conversations (user_id);

CREATE TABLE devices (
	name VARCHAR(120) NOT NULL, 
	platform VARCHAR(32) NOT NULL, 
	push_token VARCHAR(512), 
	last_seen TIMESTAMP WITHOUT TIME ZONE, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_devices_updated_at ON devices (updated_at);
CREATE INDEX ix_devices_user_id ON devices (user_id);

CREATE TABLE documents (
	title VARCHAR(300) NOT NULL, 
	mime VARCHAR(80) NOT NULL, 
	text TEXT NOT NULL, 
	summary TEXT NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_documents_updated_at ON documents (updated_at);
CREATE INDEX ix_documents_user_id ON documents (user_id);

CREATE TABLE email_drafts (
	recipient VARCHAR(320) NOT NULL, 
	subject VARCHAR(300) NOT NULL, 
	body TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	sent_at TIMESTAMP WITHOUT TIME ZONE, 
	lang VARCHAR(4) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_email_drafts_updated_at ON email_drafts (updated_at);
CREATE INDEX ix_email_drafts_user_id ON email_drafts (user_id);

CREATE TABLE events (
	title VARCHAR(300) NOT NULL, 
	start_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	end_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	location VARCHAR(300) NOT NULL, 
	notes TEXT NOT NULL, 
	attendees JSON NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	external_id VARCHAR(255), 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_events_start_at ON events (start_at);
CREATE INDEX ix_events_updated_at ON events (updated_at);
CREATE INDEX ix_events_user_id ON events (user_id);

CREATE TABLE goals (
	title VARCHAR(300) NOT NULL, 
	description TEXT NOT NULL, 
	target_date TIMESTAMP WITHOUT TIME ZONE, 
	status VARCHAR(16) NOT NULL, 
	manual_progress INTEGER, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_goals_updated_at ON goals (updated_at);
CREATE INDEX ix_goals_user_id ON goals (user_id);

CREATE TABLE memories (
	kind VARCHAR(16) NOT NULL, 
	text TEXT NOT NULL, 
	importance FLOAT NOT NULL, 
	embedding JSON, 
	meta JSON NOT NULL, 
	access_count INTEGER NOT NULL, 
	last_accessed TIMESTAMP WITHOUT TIME ZONE, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_memories_updated_at ON memories (updated_at);
CREATE INDEX ix_memories_user_id ON memories (user_id);

CREATE TABLE notes (
	title VARCHAR(300) NOT NULL, 
	body TEXT NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	tags JSON NOT NULL, 
	pinned BOOLEAN NOT NULL, 
	meta JSON NOT NULL, 
	embedding JSON, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_notes_updated_at ON notes (updated_at);
CREATE INDEX ix_notes_user_id ON notes (user_id);

CREATE TABLE oauth_accounts (
	user_id VARCHAR(32) NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	subject VARCHAR(255) NOT NULL, 
	access_token_enc TEXT, 
	refresh_token_enc TEXT, 
	scopes JSON NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (provider, subject), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_oauth_accounts_updated_at ON oauth_accounts (updated_at);
CREATE INDEX ix_oauth_accounts_user_id ON oauth_accounts (user_id);

CREATE TABLE pending_actions (
	conversation_id VARCHAR(32), 
	kind VARCHAR(48) NOT NULL, 
	payload JSON NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_pending_actions_updated_at ON pending_actions (updated_at);
CREATE INDEX ix_pending_actions_user_id ON pending_actions (user_id);

CREATE TABLE plugin_settings (
	plugin VARCHAR(80) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	granted_scopes JSON NOT NULL, 
	config JSON NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, plugin), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_plugin_settings_updated_at ON plugin_settings (updated_at);
CREATE INDEX ix_plugin_settings_user_id ON plugin_settings (user_id);

CREATE TABLE preferences (
	key VARCHAR(80) NOT NULL, 
	value JSON, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (user_id, key), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_preferences_updated_at ON preferences (updated_at);
CREATE INDEX ix_preferences_user_id ON preferences (user_id);

CREATE TABLE refresh_tokens (
	jti VARCHAR(32) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (jti), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE TABLE reminders (
	title VARCHAR(300) NOT NULL, 
	due_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	recurrence VARCHAR(16) NOT NULL, 
	style VARCHAR(4) NOT NULL, 
	fired_at TIMESTAMP WITHOUT TIME ZONE, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_reminders_due ON reminders (status, due_at);
CREATE INDEX ix_reminders_updated_at ON reminders (updated_at);
CREATE INDEX ix_reminders_user_id ON reminders (user_id);

CREATE TABLE workflows (
	name VARCHAR(120) NOT NULL, 
	trigger JSON NOT NULL, 
	steps JSON NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_workflows_updated_at ON workflows (updated_at);
CREATE INDEX ix_workflows_user_id ON workflows (user_id);

CREATE TABLE document_chunks (
	id VARCHAR(32) NOT NULL, 
	document_id VARCHAR(32) NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	idx INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	embedding JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);
CREATE INDEX ix_document_chunks_document_id ON document_chunks (document_id);
CREATE INDEX ix_document_chunks_user_id ON document_chunks (user_id);

CREATE TABLE messages (
	conversation_id VARCHAR(32) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	text TEXT NOT NULL, 
	lang VARCHAR(16) NOT NULL, 
	intent VARCHAR(48), 
	meta JSON NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);
CREATE INDEX ix_messages_updated_at ON messages (updated_at);
CREATE INDEX ix_messages_user_id ON messages (user_id);

CREATE TABLE milestones (
	goal_id VARCHAR(32) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	done BOOLEAN NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(goal_id) REFERENCES goals (id) ON DELETE CASCADE
);
CREATE INDEX ix_milestones_goal_id ON milestones (goal_id);
CREATE INDEX ix_milestones_updated_at ON milestones (updated_at);

CREATE TABLE tasks (
	title VARCHAR(300) NOT NULL, 
	notes TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	priority INTEGER NOT NULL, 
	due_at TIMESTAMP WITHOUT TIME ZONE, 
	tags JSON NOT NULL, 
	goal_id VARCHAR(32), 
	completed_at TIMESTAMP WITHOUT TIME ZONE, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(goal_id) REFERENCES goals (id) ON DELETE SET NULL, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_tasks_status ON tasks (status);
CREATE INDEX ix_tasks_updated_at ON tasks (updated_at);
CREATE INDEX ix_tasks_user_id ON tasks (user_id);

CREATE TABLE workflow_runs (
	workflow_id VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	log JSON NOT NULL, 
	user_id VARCHAR(32) NOT NULL, 
	id VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workflow_id) REFERENCES workflows (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_workflow_runs_updated_at ON workflow_runs (updated_at);
CREATE INDEX ix_workflow_runs_user_id ON workflow_runs (user_id);
CREATE INDEX ix_workflow_runs_workflow_id ON workflow_runs (workflow_id);

```
