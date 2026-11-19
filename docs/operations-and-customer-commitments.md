# Operations and customer commitments

Checked 19 November 2026. **Release gate remains open.** This document distinguishes
implemented controls from verified production operation. No production restore,
customer deletion, outbound alert, policy publication or billing change was performed.

Work order confirmed by the user: leave Terms & Conditions and the privacy policy
until last. Continue recovery, failure alerts, maintenance, support and deletion
work first. Defer legal-identity questions and policy drafting/publication until
that final stage; operational work does not depend on completing the policy copy.

The earlier main-workspace validation covered 11 focused recovery/maintenance
tests and 7 library tests. Current candidate checks and measured rollback evidence
are in [the release record](release-reconciliation-20261119.md). Local recovery
tests use disposable SQLite/storage and do not certify production backup recovery.

## Evidence and remaining gates

| Requirement | Observed evidence | Required to close |
| --- | --- | --- |
| Public availability | `https://kruvim-lp.vercel.app/`, `/api/v1/healthz` and `/api/v1/readyz` each returned 402, `Payment required / DEPLOYMENT_DISABLED` during this check | Hosting owner resolves disabled deployment; repeat anonymous landing, login, readiness and legal-link checks |
| Database recovery | Connected ANE project healthy; live application revision `0019` | Confirm backup/PITR configuration and retention in provider console; restore a dated backup into a separate project/database and record revision, counts, tenant checks, elapsed time and achieved recovery point |
| Uploaded-file recovery | Private bucket `kruvim-data`; one application asset row | Back up object bytes independently; restore them to a separate private bucket and run the checksum verification below against the restored database |
| Failure alerts | Application logs, metrics and worker health checks exist; no received test alert evidenced | Configure external checks and recipients; record delivery, acknowledgement and recovery notification for each failure class |
| Maintenance | Nine scheduled jobs combine snapshot archiving and separate mail dispatch; live `kruvim-cloud-imports` cron active at `*/10 * * * *`; latest eight cron records succeeded | Check HTTP completion and actual task completion separately; verify all three external workers and freshness of every task after deployment |
| Support | Existing legal draft identifies `shrafimtech@gmail.com` | Assign mailbox owner/backup, verify inbound receipt and response with an approved test; approve hours/escalation and response commitments |
| Deletion | Asset/project endpoints remove object bytes; library row removal exists | Rehearse scoped deletion across derived data and backups; approve retention, exception handling and account/workspace process |
| Published privacy/commercial terms | Landing source `landing-page/frontend/lib/site-info.ts` has null privacy/terms URLs; workspace legal files explicitly remain drafts | Confirm operator and policies, publish final pages, wire links, verify anonymous access and preserve versioned evidence |

The live cron results confirm PostgreSQL cron execution, not successful HTTP responses
or completed background jobs. Do not disable the existing cron until the replacement
dispatchers and workers have been verified. Local maintenance code is ahead of the
live schema: do not infer that current workspace features are deployed.

## Paired backup and restore drill

Database backups do not include Storage object bytes. See the provider's
[backup documentation](https://supabase.com/docs/guides/platform/backups).
The earlier release package contains `backend/tools/backup-production.sh`; it is
not an installed or verified production schedule. Its hard-coded schema, independent
destination, endpoint configuration and retention need review before installation.

1. Assign recovery owner and agree internal recovery-point/time targets, backup
   retention and destination region. Record these as internal targets until measured;
   do not promise an SLA from an untested schedule. Schedule paired daily backups
   and a drill before release, after storage/schema changes, and quarterly thereafter.
2. Pause application writes, imports, workers and schedulers for a consistent pair.
   Capture database backup, all object bytes and the manifest within this window.
   Include all application schemas (including landing submissions where applicable),
   required extensions/grants, configuration and separately escrowed encryption keys.
   Capture provider-managed auth through the provider-supported recovery procedure.
   An application-schema dump alone is not full-service recovery.
3. From `backend`, with source `KRUVIM_*` settings in a restricted environment, run:

   ```sh
   python -m tools.verify_recovery capture /restricted/recovery.json
   ```

   This reads every table count, Alembic revision and every `assets` object, verifies
   its recorded size, and stores SHA-256 checksums. It refuses to replace evidence.
   Keep the manifest private: it contains object keys. On Windows restrict the parent
   directory ACL; POSIX file modes do not establish Windows permissions. The command
   reads whole files one at a time and may incur storage egress.
4. Restore the database and object bytes into **isolated** targets. Verify the target
   host, schema and bucket before restoring. Keep outbound mail, paid models, billing,
   connectors, jobs and schedulers disabled. Reapply grants, extensions and private
   bucket permissions. Retain original keys in the restored bucket.
5. Start a fresh shell with restored-target database/storage settings and run:

   ```sh
   python -m tools.verify_recovery verify /restricted/recovery.json
   ```

   Require exit zero with nonzero files checked. It fails on revision/count differences,
   missing objects, size changes and same-size content corruption. `--allow-empty-assets`
   is for intentionally empty fixtures and does not prove uploaded-file recovery.
   Matching counts do not prove all database values: also compare representative
   projects, reports and settings to the source, and test tenant isolation and private
   file access through the recovered application. This tool covers `assets` references;
   additionally inventory the whole bucket, library inboxes and any external volumes,
   plus object metadata/policies and non-asset files. Record any orphan/missing keys.
6. Record backup ID/time, manifest, source/target identity, revisions/counts, checksum
   results, operator, elapsed recovery time, observed data loss and application checks.
   Store evidence with restricted access. No drill is complete until these records
   exist. Never point production at recovered jobs without reviewing replay/charges.

## Alerts and required maintenance

Use a monitor outside the application and hosting account where possible. Configure
an incident owner and backup recipient. Suggested internal thresholds, subject to
owner approval: public/readiness failure twice at one-minute intervals; worker
heartbeat missing for two minutes; failed jobs immediately; queue age above five
minutes; daily backup absent after 26 hours; any checksum failure immediately.
Check all three worker types, queue age and each maintenance job's **last successful
completion**, rather than accepting dispatch as execution. Monitor SMTP delivery
failures, connector failures, sustained 5xx and provider spend thresholds. Scrub
credentials, tokens and customer content from diagnostic events.

Test each condition in staging, receive/acknowledge the alert, recover service and
receive the recovery notification. Record incident ID, UTC timestamps and recipient;
do not claim alert delivery from configuration alone. The currently disabled public
deployment is a real condition for the uptime monitor to detect.

The required application schedule is in [background processing](background-processing.md):
data refresh/inbox/connectors every ten minutes; recurring/monitoring every ten
minutes offset five; analytics offset three; archive/cultural synthesis hourly at
:15; memory consolidation daily 02:30 UTC; watchdog/mail/token maintenance every
minute, plus regional snapshot archiving every ten minutes offset one. Deployment needs simulation, connector and maintenance workers with their
ARQ health checks. Review task failures daily, backup freshness daily, support queue
each staffed day, and retention/deletion exceptions monthly. These reviews require
assigned owners and calendar/scheduler evidence; this document does not create them.

## Support and deletion procedure

The existing contact is a draft channel, not a verified staffed service. Once the
mailbox owner confirms receipt, use it for access, export, deletion, billing and
incident requests. Track request ID, received date, verified requester, workspace,
scope, owner, applicable deadline, action and completion. Verify identity through
the authenticated account or a challenge to its registered email; never request a
password/API key. Escalate security incidents to the incident owner and billing
questions to the billing owner. Approve response times before publishing them.

For deletion, establish whether the request concerns one file, a project, workspace,
or account. Confirm workspace authority and other members' ownership interests.
Stop relevant jobs/imports and recurring sources first. Inventory uploads, extracted
text, analytics/library rows, frozen evidence copies in simulations, graph/report
content, agent/creator memory, shares, exports, inbox files, provider-held data and
credentials. Removing one library row does **not** erase evidence already frozen in
a run. Asset deletion alone does not remove derived reports. There is no verified
whole-account/workspace erasure workflow; do not substitute a membership removal.

Use scoped application operations where available, reconcile database and storage,
revoke shares/sessions/keys as appropriate and verify former access is denied. If an
operation partially fails, retain the request as incomplete and retry/reconcile;
database/object changes are not one atomic transaction. Avoid unreviewed broad SQL.
Record only minimal completion evidence, not deleted content. Explain any approved
legal retention exception. Record deletion tombstones in a restricted register so
an eventual backup restore reapplies deletions **before** service is reopened.
Define backup expiry and downstream-provider deletion before claiming completion.

## Publication gate — deferred until last

The root workspace `docs/legal/Finalisation-Notes.md` lists missing facts. Confirm
operator legal name/address/jurisdiction, processing providers/countries/transfers,
training permissions, age requirement, operational and backup retention, deletion
handling, and regulator where applicable. Commercial terms need actual plan prices,
tax/currency, renewal, cancellation effective date, refunds, credits/expiry,
provider charges, suspension and contact details aligned with the deployed checkout.
Document service limits and simulated-result limitations without inventing guarantees.

Finalize and version privacy, terms and acceptable-use information; prepare a DPA
if required by the actual business arrangement. Set public URLs in the landing
configuration and link them at signup and checkout. Test without authentication,
check links from the production footer/forms, confirm correct operator/version and
save timestamped evidence. The disabled deployment prevents that verification today.

Do not publish the draft's indefinite-retention or unspecified-training clauses
as established practice. Operator decisions are needed to finish these commitments;
the audit and local checks do not establish legal compliance.
