# Loom

GitHub codebase intelligence, in one panel. Loom is a Chrome extension + FastAPI backend that gives you two things while you browse GitHub:

- **Ask questions about a codebase** and get answers grounded in retrieved source, with clickable citations (repo pages).
- **Get an AI-powered PR review** with inline, line-accurate comments — context-aware if the repo is indexed, basic otherwise (PR pages).

The extension detects which kind of GitHub page you're on and switches modes automatically — there's no "chat tool" and "review tool" to think about, just Loom.

---

## How it works

| Page you're on | Mode | What happens |
|---|---|---|
| A repo page (home, code, file view, commits) | **Q&A** | Ask natural-language questions about the codebase; answers cite specific files and line ranges. |
| A pull request page (`/pull/:number`) | **Review** | Run an AI review of the diff; comments are posted inline at the correct lines with severity levels. |
| Anything else (org pages, GitHub home, settings) | — | Panel is hidden. |

Navigating between a repo and a PR in the same tab (GitHub is a SPA) switches modes instantly, no reload required.

---

## Architecture

```
┌─────────────────────────┐        HTTPS / JWT cookie         ┌──────────────────────────┐
│   Chrome Extension      │ ───────────────────────────────▶ │   FastAPI Backend        │
│   (Manifest V3)         │ ◀─────────────────────────────── │                          │
│                         │              JSON                 │  • GitHub OAuth          │
│  • content.js (panel)   │                                   │  • Retrieval (Chroma)    │
│  • background.js (relay │                                   │  • LLM orchestration     │
│  • Q&A + Review UI      │                                   │  • SQLite + Alembic      │
└─────────────────────────┘                                   └──────────────────────────┘
```

The retrieval layer is shared between both modes — code is chunked, embedded, and stored per-user in Chroma, then queried either for direct Q&A or to give the review model relevant context (similar logic, callers of changed functions, etc.).

---

## Tech Stack

**Backend**

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Framework | FastAPI + Uvicorn |
| LLM | Gemini API (`gemini-2.5-flash`) via `google-genai` |
| Embeddings | Local ONNX `all-MiniLM-L6-v2` (Chroma's built-in runner) |
| Vector store | Chroma (local, file-based) |
| Chunking | Hybrid AST (Python) + lexical brace-matching (JS/TS/Swift) + sliding-window fallback |
| Database | SQLite + SQLAlchemy (async) + Alembic + `aiosqlite` |
| Auth | GitHub OAuth App + JWT httpOnly cookies + Fernet-encrypted tokens |
| Testing | `pytest` + `httpx` |

**Extension**

| Layer | Choice |
|---|---|
| Platform | Chrome, Manifest V3, vanilla JS |
| Styling | Plain CSS, no frameworks |
| API calls | `fetch()` via background service worker relay (required by MV3) |
| Build | None — plain JS files loaded directly |

---

## Repository Structure

```
loom/
├── main.py                  # FastAPI entrypoint
├── requirements.txt
├── alembic.ini
├── .env.example
├── alembic/versions/
├── scripts/
│   └── reindex.py           # CLI indexing script
├── backend/
│   ├── config.py
│   ├── db/                  # models, crud, async engine
│   ├── auth/                # GitHub OAuth, JWT
│   ├── security/            # Fernet encryption
│   ├── retrieval/           # chunking, embeddings, vector store, indexing, sync
│   ├── llm/                 # LLM client + response parsing
│   ├── prompts/             # Q&A + review system prompts
│   ├── orchestrators/       # Q&A + review pipelines
│   ├── session/             # in-memory conversation history
│   └── routes/               # auth, repos, qa, review, health
└── extension/
    ├── manifest.json
    ├── background.js         # service worker: API relay, OAuth tab handling
    ├── content.js             # URL detection, panel injection, mode switching
    ├── panel/
    │   ├── panel.html / panel.css
    │   ├── delphi.js          # Q&A mode
    │   └── cassandra.js       # Review mode
    └── assets/
```

This is a two-track project split cleanly by directory: the backend team works in `backend/`, `scripts/`, `alembic/`, `main.py`; the extension team works exclusively in `extension/`. The API contract below is the shared boundary between the two.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Google Chrome
- A [GitHub OAuth App](https://github.com/settings/developers) (Client ID + Secret)
- A [Gemini API key](https://aistudio.google.com)

### Backend setup

```bash
git clone https://github.com/<your-org>/loom.git
cd loom

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # fill in the values below
alembic upgrade head            # creates loom.db

uvicorn main:app --reload --port 8000
```

`GET http://localhost:8000/health` should return `{"status": "ok", "version": "1.0.0"}`.

### Extension setup

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension/` folder.
4. Make sure the backend is running on `http://localhost:8000` (the extension's `host_permissions` are scoped to this + `https://github.com/*`).
5. Open any GitHub repo or PR page — the Loom panel should appear.

### Environment variables (`.env`)

```env
# LLM
GEMINI_API_KEY=                 # aistudio.google.com
LLM_MODEL=gemini-2.5-flash

# Embeddings
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Vector store
VECTOR_STORE_PATH=./chroma_data

# Database
DATABASE_URL=sqlite+aiosqlite:///./loom.db

# GitHub OAuth (github.com/settings/developers → OAuth Apps)
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=

# Security
JWT_SECRET=
ENCRYPTION_KEY=                 # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Server
PORT=8000
LOG_LEVEL=info
```

---

## API Reference

Base URL (dev): `http://localhost:8000`. All extension requests go through the background service worker relay with `credentials: 'include'` so the JWT cookie is sent.

### Auth
```
GET  /auth/github/login          → redirect to GitHub OAuth
GET  /auth/github/callback       → exchange code, set JWT cookie
GET  /auth/logout                → clear cookie
GET  /auth/me                    → { github_username, avatar_url } | 401
```

### Repos
```
GET  /repos/github               → { repos: [{ full_name, private, default_branch }] }
POST /repos/index                → body: { repo_full_name } → { repo_id, status: "indexing" }
GET  /repos/indexed              → { repos: [{ repo_id, repo_full_name, status, chunk_count, last_indexed_at }] }
GET  /repos/status/:repo_id      → { status, chunk_count, last_indexed_at }
```
`status` is one of `pending | indexing | ready | failed`.

### Q&A
```
POST /ask
body: { repo_id, question, conversation_id? }
→ 200: { answer, sources: [{ file, function_name, line_start, line_end }], conversation_id }
→ 400: { error: "repo not indexed" }
```

### Review
```
POST /review
body: { repo_id: uuid|null, pr_title, pr_description, diff: [{ file, patch, status }] }
→ 200: { summary, comments: [{ file, line, severity, text }], context_aware }
→ 400: { error: "diff is required" }
```
`severity` is one of `info | warning | critical`. `repo_id: null` triggers a **basic review** (no retrieval context); `context_aware` reflects whether context was actually used.

### Health
```
GET /health → { status: "ok", version: "1.0.0" }
```

Every non-2xx response returns `{ "error": "...", "detail": "..." }` — no raw exceptions or unparsed JSON ever reach the client.

---

## Data & Privacy

- GitHub access tokens are Fernet-encrypted at rest and decrypted only in memory; they're never logged or returned in API responses.
- Vector data is scoped per user (`{user_id}_{sanitized_repo_name}` Chroma collections) — two users indexing the same repo never share embeddings.
- Every repo-scoped operation verifies ownership (`indexed_repos.user_id == current_user.id`) before proceeding.

---

## Testing

Backend tests use `pytest` + `httpx`, with `LLMClient`, `retrieve_context`, and all GitHub API calls mocked — no real API calls in the suite.

```bash
pytest
```

Covers: OAuth flow and JWT verification, chunking (Python AST / JS lexical / sliding window), LLM response parsing, `/ask` and `/review` happy paths and error paths, and per-user vector store isolation.

---

## Roadmap / Status

- [x] Backend: retrieval pipeline, GitHub OAuth, Q&A endpoint, review endpoint
- [x] Extension: mode detection, Q&A panel, inline PR review comments
- [ ] Polished UI/UX pass
- [ ] Auto-sync daemon refinements
- [ ] Chrome Web Store listing

---

## License

Add a license of your choice (MIT is a common default for projects like this).
