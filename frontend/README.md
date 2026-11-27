# RAG Intelligence: Web Frontend

React 18, TypeScript, Vite 6, Tailwind CSS 4, Axios, Lucide and React Router. It talks to the FastAPI backend in `../backend`. All data comes from the backend's real endpoints, and nothing is mocked.

## Run

The backend must be running on port 8001. See the root README.

```powershell
cd "C:\Production-Grade RAG System\enterprise-rag-platform\frontend"
Copy-Item .env.example .env      # first time only (VITE_API_BASE_URL=http://localhost:8001)
npm install                      # first time only
npm run dev                      # http://localhost:5173
```

Production build: `npm run build` writes `dist/`; `npm run preview` serves it on port 5173.

Open the app at **http://localhost:5173**, not `127.0.0.1`. The backend's `CORS_ORIGINS` allows `http://localhost:5173`, so other origins are blocked by CORS unless you add them there.

## Pages

| Route | Page | Backend endpoints |
|---|---|---|
| `/login` | Sign in / register | `POST /auth/login`, `POST /auth/register`, `GET /auth/me` |
| `/` | Overview | `GET /analytics/overview`, `GET /documents` |
| `/chat` | AI Chat (streaming) | `POST /chat/stream` (SSE), `GET/DELETE /conversations[/{id}]`, `GET /models`, `GET /settings` |
| `/knowledge` | Knowledge Base | `GET /documents`, `GET /documents/{id}/chunks` |
| `/documents` | Upload & manage | `POST /documents/upload`, `GET /documents/{id}/status`, `POST /documents/{id}/ingest`, `DELETE /documents/{id}` |
| `/search` | Retrieval workspace | `POST /search`, `GET /search/history` |
| `/analytics` | Analytics | `GET /analytics/overview`, `GET /analytics/usage`, `GET /evaluation/results`, `GET /models` |
| `/settings` | RAG settings | `GET/PUT /settings`, `GET /models` |
| header | Connection indicator | `GET /health/ready` (polled every 30 s) |
| sidebar | Sign out | `POST /auth/logout` (revokes the token server-side) |

## Design decisions

- **Token storage.** The backend returns a bearer JWT in the response body and has no cookie flow, so the token is kept in `sessionStorage`. It is cleared when the tab closes, and logout revokes it server-side. Any 401 response signs the user out.
- **Streaming.** `/chat/stream` is a POST that needs an Authorization header, which `EventSource` cannot send. The stream is therefore read with `fetch` and parsed as SSE (`conversation`, `sources`, `token`, `done`, `error`). The verified answer and citations from the `done` event replace the streamed text.
- **Grounding badge.** It shows exactly what the backend verifier returned:
  - **Grounded** when `verification.grounded` is true.
  - **Partially supported** when the verifier flagged weak or uncited sentences.
  - **Insufficient evidence** when the system abstained.
  - **Not verified** when no verification data came back.
- **Model selector.** It lists the server's allow-list. Models whose provider is not configured are shown but disabled.

## Layout

```
src/
  components/{ui,layout,chat,documents}/
  context/AuthContext.tsx
  hooks/       useApi, useBackendHealth, useUploads
  layouts/AppLayout.tsx
  pages/       Login, Dashboard, Chat, KnowledgeBase, Documents, Search, Analytics, Settings
  services/    api (axios + token + errors), auth, document, chat (SSE), platform
  types/api.ts mirrors the backend OpenAPI schemas
  utils/format.ts
```
