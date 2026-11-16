# Invitation authentication fix

An inviting workspace administrator receives the raw invite link. That link authorizes joining the inviting workspace, but cannot establish the identity of an existing account. Previously, omitting the optional password skipped verification and issued both access and refresh tokens for the invited account.

Acceptance now requires a password in the request. An existing recipient must supply their own password and have an active account before any membership, acceptance timestamp, audit entry or session is created. A new recipient uses the password to create an account. An unrelated signed-in session cannot replace the recipient's password. Missing, null and empty passwords receive HTTP 422; incorrect passwords and disabled accounts receive HTTP 401.

The endpoint shares login's IP and email rate-limit keys. These use the existing rate-limit backend; this change does not provide shared limits across production instances when Redis is absent. A database row lock serializes acceptance of the same invitation on PostgreSQL. SQLite regression tests verify sequential replay rejection, not PostgreSQL concurrent locking.

The invite form requires a password, reads browser-filled form values, and avoids automatically refreshing and retrying a failed password attempt. Existing account names and passwords are preserved. Acceptance audit records now include the client IP.

## Verification

From `backend`, run `.venv\Scripts\python.exe -m pytest tests/test_invite_auth.py -q`. The 18 regressions cover an ordinary inviter attacking another ordinary account, omitted/null/empty/wrong credentials, unrelated signed-in credentials, cross-workspace denial, unchanged database state after rejection, disabled accounts, expiry/revocation/invalid tokens, single-use acceptance, valid existing/new recipients, refresh, and shared login limits. Tests use disposable local SQLite data and no production accounts.

From `frontend`, run `npm run build`. Browser regressions in `e2e/invitation-auth.spec.ts` cover existing-recipient rejection and password authentication (including autofill), plus new-account creation, on desktop and mobile layouts. No database migration is required for this fix.

## Production follow-through

Deploy the patched backend and frontend together and verify production rejects missing, null and empty passwords before treating the reported bypass as closed. Deployment does not revoke previously issued sessions.

Review historical `member.invite` and `invite.accepted` audit records alongside invitation creation/acceptance times, inviter and recipient identities, and available request logs. Pre-fix acceptance records do not establish whether a password was supplied, so those records alone cannot distinguish legitimate acceptance from exploitation.

For accounts confirmed or suspected to be affected, revoke all their unrevoked `refresh_tokens` and review memberships and API keys created during the exposure window. Existing access JWTs remain usable until expiry; the current implementation has no per-account immediate access-token revocation. Rotating the JWT signing secret invalidates access tokens globally and requires coordinating the secret across application instances; refresh tokens must also be revoked to prevent renewed sessions. Perform production investigation and account changes as a separate, explicitly scoped operation.
