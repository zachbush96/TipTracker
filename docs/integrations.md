# Scoped tip-entry API

This implements the API portion of issue #16. Both feature flags default to disabled. Deploying code does not issue credentials or enable client access.

The browser API keeps its existing routes and response format. Both APIs use shared Decimal calculations with PostgreSQL-compatible half-up rounding. Integration validation is stricter than browser validation.

## Interface

All routes use `/api/integrations/v1`. Browser sessions and demo mode do not authenticate these routes.

| Method and path | Scope | Result |
| --- | --- | --- |
| `GET /tips` | `tips:read` | Own entries, ordered by work date descending, then ID descending |
| `GET /tips/{id}` | `tips:read` | One own entry, or 404 |
| `GET /sections` | `tips:read` | Up to 100 own section suggestions, alphabetically sorted |
| `POST /tip-previews` | `tips:create` | Normalized entry, totals, same-day candidates, and a ten-minute preview |
| `POST /tips` | `tips:create` | One persisted entry from an exact preview |

`GET /tips` accepts `limit` (1–100, default 25) and `offset` (0–100000, default 0). Dates use `start_date` and `end_date` inclusively. The default range covers the last 30 days through today.

A response includes `next_offset` when another page exists. Offset pagination is deterministic for a fixed dataset. Concurrent inserts can shift page boundaries.

## Authentication design

The draft uses high-entropy opaque bearer grants. The server stores only the SHA-256 token digest, owner, client identifier, audience, scopes, expiry, and revocation status.

Each request requires `Authorization: Bearer <token>` and `X-Integration-Client: <client-id>`. The expected audience is `tiptracker-integrations-v1`. The client header identifies the grant consumer. It is not a second authentication factor.

A grant always selects its own user, including manager accounts. No route accepts an owner identifier. The API provides no credential-management, edit, delete, administration, or manager-report operations.

Grant issuance remains an operator design decision before rollout. A trusted issuer must generate at least 256 random bits and store the digest. No route returns tokens. Browser cookies and Supabase credentials are not integration grants.

## Preview and consent contract

The assistant client owns the human consent step. A preview identifier or a Boolean cannot prove human approval. The API enforces payload integrity after that step.

1. Extract the proposed fields without guesses.
2. Submit all eight fields to `POST /tip-previews`.
3. Resolve each unknown field and any tip-out issue.
4. Present the normalized entry, totals, and possible duplicates to the user.
5. Request explicit approval of the exact normalized entry.
6. If the user changes a value, request a new preview and approval.
7. Submit the approved entry with its preview identifier and an idempotency key.
8. Read the returned entry ID through `GET /tips/{id}`.

A client needs both scopes for the complete flow. Same-day entries produce warnings rather than a uniqueness restriction. Legitimate separate shifts remain valid after explicit client consent.

### Preview body

```json
{
  "work_date": "2026-10-24",
  "section": "patio",
  "cash_tips": "20.25",
  "card_tips": "80.75",
  "tip_out": "15.00",
  "sales_amount": "600.00",
  "hours_worked": "5.00",
  "comments": "Synthetic example"
}
```

All eight keys are required for a ready preview. Missing fields or unknown financial values produce 422 with `ready=false`, `unresolved_fields`, and no preview identifier. Explicit zero differs from unknown.

`tip_out` requires an explicit nonnegative decimal, including explicit zero when none was paid. Null means unknown and prevents a ready preview. Cash and card tips are gross amounts before tip-out; `total_tips` is their sum, `net_tips` subtracts tip-out, and `tips_per_hour` uses net tips. Tip percentage uses gross tips divided by sales, matching the deployed PostgreSQL trigger. Negative net tips are permitted when tip-out exceeds gross, matching the app. The API never maps cash owed, deposits, or cash sales into cash tips.

Amounts accept finite decimal strings or JSON numbers with at most two decimal places. Monetary fields range from zero through 99999999.99. Hours exceed zero and do not exceed 24.

Calculated totals must fit their database columns. The limits are 99999999.99 for total tips, 999999.99 for tips per hour, and 999.99 for tip percentage.

Sections contain at most 50 characters. Comments contain at most 500 characters. Section normalization trims whitespace and converts text to lowercase.

Work dates use exact `YYYY-MM-DD` calendar dates. Future dates are invalid against the America/New_York calendar. Imports never default an unknown work date to today.

The parser rejects arrays, duplicate keys, unexpected fields, booleans as amounts, malformed JSON, and non-finite values. Bodies cannot exceed 16 KiB.

### Create body

```json
{
  "preview_id": "<identifier from preview>",
  "entry": {
    "work_date": "2026-10-24",
    "section": "patio",
    "cash_tips": "20.25",
    "card_tips": "80.75",
    "tip_out": "15.00",
    "sales_amount": "600.00",
    "hours_worked": "5.00",
    "comments": "Synthetic example"
  }
}
```

Creation requires `Idempotency-Key`. Keys contain 1–128 ASCII letters, digits, periods, underscores, colons, or hyphens. The entry must match the normalized preview exactly, including decimal strings.

A conditional preview update, entry insert, and unique receipt insert share one database transaction. Receipt uniqueness covers owner, client, and key. A preview permits one successful consumption.

A retry with the same key and payload returns the original entry with 200 and `replayed=true`. This works after preview expiry. A changed payload returns 409. A new key cannot reuse a consumed preview.

## Errors and audit

| Status | Meaning |
| --- | --- |
| 400 | Invalid fields, JSON, date, or pagination |
| 401 | Missing, invalid, expired, revoked, wrong-client, or wrong-audience credential |
| 403 | Insufficient scope or disabled creation |
| 404 | Disabled API or unavailable own entry |
| 409 | Preview mismatch, expiry, consumption, or idempotency conflict |
| 413 | Body exceeds 16 KiB |
| 422 | Unresolved fields or unsupported tip-out |
| 503 | Database operation failed |

Responses disable caching and include `X-Request-ID`. Audit events contain request ID, actor, client, entry ID when available, and status. They exclude tokens, payloads, images, and comments.

Expired previews contain personal entry data. The deployment retention policy must purge expired previews after 24 hours. Receipt records must remain for the documented retry lifetime. This draft retains receipts indefinitely to preserve retry protection.

Audit retention follows the host log policy. Operators must set and document that policy before rollout. Application logs do not contain request bodies or credentials from these routes.

## Rollout gates

The following items remain unverified. This draft does not enable production access.

- Full restore-capable production backup and an exercised restore route before schema changes.
- Target assistant client and its explicit consent behavior.
- Trusted grant issuer, delivery, expiry, revocation, and operational retention policy.
- Effective production backend role and its access to the additive integration tables.
- CI validates a disposable PostgreSQL 17 database with UUID/FK schema, trigger calculations, concurrent retries, API owner isolation and restricted Data API roles. It does not establish production credential or role configuration.
- Separate deployment and security review.

`integration_schema.sql` is an additive, review-only PostgreSQL setup script. It enables RLS and revokes public/Data API access on the three integration tables. It creates no permissive policies.

Application ownership filters provide API isolation even when the backend role bypasses RLS. SQLite tests do not establish PostgreSQL or Supabase isolation. Existing browser authorization and policies remain outside this draft.

The application creates only the existing browser tables at startup. The integration schema requires an explicit deployment step. An unavailable schema returns a generic database error.

`INTEGRATIONS_ENABLED=1` exposes authenticated integration routes. `INTEGRATIONS_CREATE_ENABLED=1` additionally permits entry creation. Both remain unset until their respective rollout reviews finish. Automatic SQLite fallback rejects integration access. Explicit SQLite configuration supports isolated development.

The startup code no longer contains a default database password. The previously exposed password requires external rotation. Git history remains unchanged.

## Local validation

Tests block socket connections before application import. They force a synthetic SQLite database and blank Supabase configuration. Production credentials are not necessary.

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
```

The suite covers authentication, scopes, manager isolation, strict validation, unknown values, preview binding, expiry, retry protection, concurrent requests, and browser compatibility.

An MCP adapter remains deferred until the target client and supported authentication flow are known. The adapter can wrap this API without direct database access.


## Deployment and rollback

On 2026-10-26, read-only production catalog inspection confirmed UUID user IDs, bigint tip IDs, numeric tip-out/net columns, and the trigger semantics above. Integration tables were absent. No production financial entries were inserted or changed for validation.

Code may be deployed with both integration flags disabled, without applying the additive schema. Preserve the prior Replit deployment/checkpoint and source revision before updating. Roll back code by restoring that checkpoint or reverting the code commit and republishing; leave existing business data unchanged. Do not enable access, create grants, change existing RLS or rotate credentials as part of a code-only rollout. Those require separate operator approval.

Before enabling access, verify a full PostgreSQL backup (schema, data, roles/grants, functions, triggers and applicable auth/storage coverage) and restore procedure. A public anon export is insufficient. Apply the reviewed integration schema only after this gate. Verify backend privileges without broadening public or Data API access. Record the approved client, owner, scopes, expiry, consent behavior, token delivery/revocation and preview/audit retention policy.

The existing fallback session secret and any previously exposed database credentials still require operator remediation. No credential is generated, rotated or displayed by this code change.
