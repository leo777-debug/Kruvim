# Authentication release verification — 18 November 2026

Status: tested and prepared; not deployed. Production email configuration is required before release.

## Release source

- Target: Vercel `kruvim-lp`, project `prj_7opOj3HCYoBRIMqGb81zXrN8ILDw`, team `team_wCW1Fz8EiXYTLsgKxcNFaYmf`.
- Base: exact live source `8e9aab50557ee114447c2c5240bb7fded43a7205`.
- Branch: `fix/account-recovery-20261118`.
- Production database: ANE (`jrdgxbdglmpynbyfmamf`), schema `kruvim`, observed revision `0019`.
- Auth migration `0021` on this release follows `0019`; the working source tree's unrelated unreleased billing migration `0020` is excluded.
- The landing page, upload fixes, routing, and existing production behavior are preserved.

## Changes and fixes

Password reset, email verification, session invalidation, SMTP delivery, encrypted outbox retries, and database-backed shared rate counters are included. A hosting-specific IP bug was corrected: Vercel requests use the validated platform client-IP header instead of sharing the socket proxy's limit. Ordinary forwarded headers remain untrusted by default. The isolated browser server now gives repeated test accounts an appropriate test-only auth limit; separate backend tests assert real throttling behavior.

## Evidence

- 60 backend tests passed: account security, invitation authentication, dry workflows, direct uploads, and media processing.
- 24 desktop/mobile Edge tests passed: recovery UI, invitations, sign-in, registration, autofill, and browser password saving.
- Production frontend build passed.
- Ruff and diff whitespace checks passed.
- SQLite migration sequence passed: upgrade to `0019`, upgrade to `0021`, downgrade to `0019`, upgrade to `0021`.
- Exact PostgreSQL migration SQL was generated offline and reviewed in `account-security-production-migration.sql`. It has not been applied to production.
- Real local SMTP socket delivery passed. Verification and reset messages were received by a local capture server, their links consumed successfully through the API, and replays rejected. External provider delivery has not been tested.

## Remaining deployment prerequisite

Production has no SMTP provider credentials or sender configuration. The new production startup checks deliberately reject console delivery. Publishing now would fail application startup; enabling email verification without delivery would also prevent users from entering their workspaces.

Configure `KRUVIM_MAIL_BACKEND=smtp`, `KRUVIM_MAIL_FROM`, `KRUVIM_SMTP_HOST`, `KRUVIM_SMTP_PORT`, `KRUVIM_SMTP_USERNAME`, `KRUVIM_SMTP_PASSWORD`, and `KRUVIM_SMTP_SECURITY=starttls` (or `ssl`) in the Vercel production environment. Verify the sender with the chosen provider. Do not commit or paste credentials into chat.

After configuration: recheck the production target and database version, apply the additive migration, stage a production-environment deployment without domain assignment, verify health and the full mail flow with a controlled account, then promote that exact tested deployment and check the public alias. Existing users will need email verification; there is an explicit temporary enforcement override documented in `authentication-safeguards.md`.


## Zero-cost email setup follow-up

The user declined domain registration and requires no additional spend. No domain was purchased and no paid email plan was selected. Resend terms were accepted and its integration installation exists on the Free plan, but no sending-domain resource or SMTP credentials were provisioned.

Brevo's Free plan is the selected alternative because it supports 300 daily sends and can rewrite a verified free-email sender to its shared `brevosend.com` domain. This avoids buying a domain. Sender rewriting changes the address recipients see; a custom branded sender remains a future option. Provider account approval, sender verification, and live inbox delivery must still be confirmed before deployment.

The Brevo signup page is open for the user to create/verify their account and accept its terms. Use only the Free plan, no payment card, and no paid add-ons. SMTP configuration will use `smtp-relay.brevo.com`, port 587 with STARTTLS; the provider supplies the SMTP login and key. Keep all credentials out of Git and chat output. Production remains unchanged while this prerequisite is pending.

Primary references: [Brevo free plan](https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans), [shared sender-domain behavior](https://help.brevo.com/hc/en-us/articles/16045394674066-Troubleshooting-Domain-authentication), [SMTP setup](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP).
