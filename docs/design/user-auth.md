# User Authentication Design

## Context

The platform stores data scoped to `user_id` throughout (jobs, memory, workflows, RAG scope filters,
chat sessions, feedback). Currently there is no authentication layer — the API reads `user_id` from
`X-User-Id` / `X-Authenticated-User-Id` request headers without any verification, and the UI
hard-codes a single user id in localStorage.

This document describes the design for a minimal authentication layer that maps a real logged-in
user to the `user_id` used everywhere in the system.

---

## Goals

- Authenticated users: every API call is scoped to a verified identity.
- Minimal implementation: no email verification, no OAuth, no MFA — username + password only.
- No new Python library dependencies: use stdlib `hashlib`/`secrets` + existing Redis.
- All existing `user_id` scoping (memory, RAG, workflows) works automatically once auth is wired.

---

## Data Model

### `users` table

| Column          | Type     | Notes                            |
|-----------------|----------|----------------------------------|
| `id`            | `string` | UUID primary key                 |
| `username`      | `string` | unique, lowercase                |
| `display_name`  | `string` | shown in UI                      |
| `password_hash` | `string` | `hex(salt):hex(pbkdf2_sha256)`   |
| `created_at`    | `datetime` |                                |

No email or role columns in v1.

### Session tokens (Redis)

Opaque tokens — no JWT, no signature verification needed.

- Key: `auth_session:{token}` (token = `secrets.token_urlsafe(32)`)
- Value: JSON `{"user_id": "...", "username": "...", "display_name": "..."}`
- TTL: 7 days (refreshed on each use if desired)
- Stored only in Redis; no DB table needed

---

## API Routes

| Method | Path              | Auth required | Description                              |
|--------|-------------------|---------------|------------------------------------------|
| POST   | `/auth/register`  | No            | Create a new account                     |
| POST   | `/auth/login`     | No            | Exchange credentials for a session token |
| GET    | `/auth/me`        | Yes           | Return the authenticated user            |
| POST   | `/auth/logout`    | Yes           | Revoke the current session token         |

### POST `/auth/login`

Request:
```json
{ "username": "alice", "password": "secret" }
```

Response `200`:
```json
{
  "token": "<opaque token>",
  "user": { "id": "...", "username": "alice", "display_name": "Alice" }
}
```

Response `401`: `{ "detail": "invalid_credentials" }`

### POST `/auth/register`

Request:
```json
{ "username": "alice", "display_name": "Alice", "password": "secret" }
```

Response `200`: same shape as login.  
Response `409`: `{ "detail": "username_taken" }`  
Response `422`: `{ "detail": "username and password required" }`

---

## Middleware

A FastAPI HTTP middleware runs on every request:

1. Read `Authorization: Bearer <token>` header.
2. Look up `auth_session:{token}` in Redis.
3. If found: set `request.state.authenticated_user_id = session["user_id"]` and
   `request.state.auth_user = session`.
4. If not found: leave request state unset (public routes still work; protected routes return 401).

The existing `_chat_authenticated_user_id(request)` already reads `request.state.authenticated_user_id`,
so all existing job/chat/memory user-scoping flows work with no additional changes.

---

## Password Hashing

```python
# hash: hex(salt) + ":" + hex(pbkdf2_hmac("sha256", password, salt, 100_000))
# verify: recompute and compare with secrets.compare_digest
```

stdlib only, no passlib dependency.

---

## Frontend

### Token storage

`localStorage` key: `ape.auth.token.v1`

All `fetch` calls in `WorkspaceSurfaceContent` are wrapped in a module-level `apiFetch` helper
that reads the token and adds `Authorization: Bearer <token>`. The Next.js proxy passes the header
through to the API unchanged.

### Auth context (`lib/auth.tsx`)

- `AuthProvider` — wraps the whole app; checks `/api/auth/me` on mount.
- Unauthenticated users are redirected to `/login`.
- The `/login` route itself is exempt from the redirect.
- Exposes `useAuth()` hook: `{ user, login, logout, loading }`.

### `user_id` wiring

`WorkspaceSurfaceContent` currently initialises `workspaceUserId` from localStorage with a hard-coded
default. After this change it initialises from `auth.user.id` (the authenticated user's UUID), so
all context, memory, and RAG calls are automatically scoped to the logged-in user.

### AppShell

A user avatar chip (initials circle) and "Sign out" button are added to the top-right of every
page header. The chip shows `display_name`.

---

## Security notes (v1 limitations)

- No CSRF protection — the token is in `Authorization`, not in a cookie, so CSRF is not applicable.
- Token is stored in localStorage: vulnerable to XSS. Acceptable for an internal tool with no PII.
- Upgrade path: switch to httpOnly `Set-Cookie` with SameSite=Strict for a hardened deployment.
- Password policy: minimum 6 characters only in v1.
- No rate-limiting on `/auth/login` in v1.

---

## Migration

Alembic migration `20260527_add_users` adds the `users` table. No data migration is needed —
existing rows with `user_id = null` remain accessible.

For local development, register a user via `POST /auth/register` or with the login page's
"Create account" link.
