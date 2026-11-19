# Authentication safeguards

Recovery and verification now use the app's existing custom authentication database.

- `POST /api/v1/auth/forgot-password` accepts `{email}` and always returns the same eligible-account confirmation.
- `POST /api/v1/auth/reset-password` accepts `{token, new_password}`. Passwords require 10–200 characters. A successful reset invalidates access tokens, refresh tokens, and other outstanding reset links.
- `POST /api/v1/auth/verification-email` accepts `{email}` with the same private confirmation.
- `POST /api/v1/auth/verify-email` accepts `{token}`. Session and `/auth/me` responses expose `email_verified` and `email_verification_required`.

Registration and new invited accounts receive verification mail automatically. Invitation mail and existing allowance/provider notices use the same delivery service. An invitation does not verify an email address: an inviting administrator can access the invitation link.

Tokens contain 48 random bytes, are stored only as SHA-256 hashes, expire after 30 minutes (reset) or 24 hours (verification), and can be consumed once. Issuing a new link invalidates earlier links for the same purpose. Password changes also invalidate outstanding reset links and all existing sessions, including the current session. Recovery never signs the browser in automatically.

The browser routes are `/forgot-password`, `/reset-password`, `/verification-email`, and `/verify-email`, under `KRUVIM_APP_BASE_PATH` when configured. Links carry their token in the URL fragment so HTTP logs and referrers do not receive it. Verification requires a button press; email link scanners cannot consume it with a GET.

## Deployment

Apply migration `0021` with `python -m alembic upgrade head` from `backend` before serving the updated application. Existing users remain unverified and can request a verification email from the sign-in screen. Production requires verified email for workspace endpoints; account recovery, sign-in, refresh, `/auth/me`, and password changes remain accessible. Existing organization API keys retain their own authentication. `KRUVIM_REQUIRE_EMAIL_VERIFICATION=false` is an explicit temporary migration override; otherwise verification is required in production and optional in development.

Set these on the API and workers:

```dotenv
KRUVIM_ENV=production
KRUVIM_PUBLIC_URL=https://your-domain.example
KRUVIM_MAIL_BACKEND=smtp
KRUVIM_MAIL_FROM=Kruvim <accounts@your-domain.example>
KRUVIM_SMTP_HOST=smtp.your-provider.example
KRUVIM_SMTP_PORT=587
KRUVIM_SMTP_USERNAME=your-smtp-user
KRUVIM_SMTP_PASSWORD=your-smtp-password
KRUVIM_SMTP_SECURITY=starttls
KRUVIM_RATE_LIMIT_BACKEND=auto
```

Use `ssl` with port 465 for implicit TLS. Production refuses console delivery, plaintext SMTP, and an HTTP public URL. Configure and verify the sender/domain with your mail provider, including its required DNS records. The development console setting suppresses delivery and never claims the message was delivered; use a local SMTP capture service for development links (`plain` is allowed only outside production).

The mail outbox commits with account tokens, invitations, and notices. Bodies are encrypted with the application's existing secret encryption key; delivered bodies are cleared. SMTP failures retain the message with exponential retry delays, capped at one hour, until its expiry. Delivery runs after account/invite requests, every 30 seconds in the persistent API, every minute in the existing worker maintenance job, and in the existing authenticated cloud refresh endpoint. Keep the cloud refresh scheduler running for serverless retry delivery. SMTP acceptance is tracked; inbox receipt and bounces require provider monitoring. Delivery is at least once: a process crash after SMTP accepts mail but before the database commit can produce a duplicate.

`auto` uses Redis when configured and otherwise uses atomic SQL upserts in production/serverless. `database` explicitly selects SQL in any environment; `redis` requires `KRUVIM_REDIS_URL`. Production/serverless reject `local`. Redis increment/expiry runs atomically. Counter keys hash account/IP identifiers; expired SQL counters are pruned. Backend outages fail the request rather than silently bypassing limits. Development uses per-process counters unless a shared backend is selected.

Only enable `KRUVIM_TRUST_PROXY_HEADERS=true` behind a proxy that overwrites client-supplied `X-Forwarded-For`. Otherwise the socket peer supplies the IP; direct clients cannot evade throttling by forging forwarding headers. All replicas need the same backend configuration. Authentication has IP/account limits; recovery and verification emails share a three-per-hour per-address limit, including nonexistent accounts.

## Validation

`backend/tests/test_account_security.py` covers recovery, verification enforcement, expiry, purpose separation, replay, disabled accounts, session revocation, reissuance, concurrent SQL counters, spoofed forwarding headers, SMTP TLS/authentication, and outbox retries. `frontend/e2e/account-recovery.spec.ts` exercises confirmation, token submission, and expired-link UI on desktop/mobile; reset and verification responses are mocked there, while backend tests exercise their actual state transitions.

Migration upgrade/downgrade/upgrade is checked on a disposable SQLite database. Live PostgreSQL/Redis replicas and external SMTP delivery require deployment credentials and a staging smoke test before production rollout.

On Vercel, validated `X-Vercel-Forwarded-For` supplies the client IP automatically; ordinary forwarding headers remain untrusted by default. See [Vercel request headers](https://vercel.com/docs/headers/request-headers).
