# Security Checklist

Status legend: ✅ implemented and covered by automated tests · 🟡 implemented, not fully verified · ❌ not implemented / production gap.

This is a self-assessment, **not** a security review. The platform must not be described as production-secure until an independent review has been carried out.

## Authentication & sessions

| Control | Status | Evidence |
|---|---|---|
| Passwords hashed with bcrypt (cost 12), no 72-byte truncation | ✅ | `core/security.py`, `test_password_hashing` |
| Password strength (≥ 8 chars, letter + digit) | ✅ | `schemas/auth.py`, `test_rejections` |
| Timing-equalised login for unknown emails | 🟡 | `auth_service.authenticate` (dummy hash); not timing-tested |
| JWT signature, expiry, `alg=none` rejected | ✅ | `test_jwt_roundtrip_tamper_and_expiry` |
| Logout revokes token (jti deny-list) | ✅ | `test_register_login_me_logout` |
| Production refuses default/short `JWT_SECRET_KEY` and wildcard CORS | ✅ | `test_production_rejects_insecure_config` |
| Refresh tokens / key rotation | ❌ | access tokens only (60 min) |
| Account lockout after failed logins | ❌ | mitigated by per-IP auth rate limit only |

## Authorization & isolation

| Control | Status | Evidence |
|---|---|---|
| Every document/chunk/conversation/eval query scoped by owner | ✅ | `test_user_isolation_across_documents_search_chat_and_conversations` |
| Other users' resources return 404 (no existence leak) | ✅ | same test |
| Retrieval cannot return other users' chunks (vector, keyword, hybrid, filters) | ✅ | same test |
| Caches user-scoped; semantic cache never serves another user's answer | ✅ | `test_retrieval_cache_is_user_scoped_and_invalidated`, `test_semantic_cache_threshold_and_isolation`, isolation test |
| Admin-only metrics endpoint | ✅ | `test_analytics_and_metrics` |
| Row-level security in PostgreSQL (defence in depth) | ❌ | isolation is enforced in application queries |

## Input handling

| Control | Status | Evidence |
|---|---|---|
| Upload type validated by extension **and** magic bytes | ✅ | `TestFileValidation`, `test_validation_errors` |
| Upload size limit enforced while streaming | ✅ | `test_validation_errors` (413) |
| Corrupted/encrypted files fail safely | ✅ | `test_corrupted_*`, `test_corrupted_file_marks_document_failed` |
| Client filename never used as a storage path | ✅ | `document_service.save_upload` (stored as `<uuid>.<ext>`) |
| SQL injection: bound parameters, `plainto_tsquery`, escaped LIKE | 🟡 | by construction; no fuzzing performed |
| Request validation with Pydantic, bounded lengths | ✅ | schemas; 422 tests |
| Malware scanning of uploads | ❌ | not implemented |

## LLM-specific

| Control | Status | Evidence |
|---|---|---|
| Sources delimited; documents cannot close the `<source>` tag | ✅ | `test_documents_cannot_break_out_of_source_tags` |
| System prompt treats sources as untrusted; injection text flagged | ✅ / 🟡 | `test_prompt_injection_is_flagged`; flagging is heuristic, effectiveness against adaptive attacks not measured |
| Invented citations removed; answers never cite non-existent sources | ✅ | `test_invented_citations_are_removed_never_remapped` |
| LLM model whitelist (prevents arbitrary/expensive models) | ✅ | `test_disallowed_model_rejected`, settings validation |
| Provider error details not leaked to clients | ✅ | `test_litellm_errors_become_safe_provider_errors` |
| Output filtering for sensitive data (PII) | ❌ | not implemented |

## Operational

| Control | Status | Evidence |
|---|---|---|
| Per-user and per-IP rate limiting | ✅ | `test_rate_limiter` |
| Uniform error envelope, no stack traces to clients | ✅ | `test_request_id_and_safe_errors` |
| Secrets only from environment; `.env` git-ignored | ✅ | `.gitignore`, `.dockerignore`; verified before each commit |
| Log redaction of password/token/secret/api_key fields; no document text logged | 🟡 | `core/logging.py`; redaction by key name only |
| CORS restricted to configured origins, credentials disabled | ✅ | `main.py` |
| Container runs as non-root | ✅ | `backend.Dockerfile` |
| HTTPS/TLS | ❌ | must be terminated by a reverse proxy / load balancer in production |
| Secret manager (Vault / cloud KMS) | ❌ | production requirement |
| Dependency vulnerability scanning (pip-audit, image scan) | ❌ | recommended in CI |
| Audit log of document access | ❌ | usage events cover queries, not a tamper-evident audit trail |
