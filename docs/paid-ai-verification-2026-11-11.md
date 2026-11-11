# Paid AI usage verification

Verified on 11 November 2026 against the Vercel `billing-preview` branch and the
isolated Supabase `kruvim_billing_preview` schema.

## Implementation and local checks

- AED 50 per seat each month includes AED 10 of AI usage.
- The AED 20 one-time top-up adds AED 10 to the purchasing seat.
- Paid simulations select Kruvim's server-side OpenAI connection. The default model is
  `gpt-4.1-mini-2025-04-14`. Configured USD token prices and the USD-to-AED conversion
  determine the debit, including discounted cached input.
- Database reservations precede each OpenAI request. Successful calls settle against
  reported usage. Uncertain requests retain reservations for reconciliation.
- Eleven focused backend billing tests pass. They cover the AED 0.30 debit leaving
  AED 9.70, seat isolation, concurrent reservations, webhook signatures, payment
  deduplication, renewals, insufficient balances, rate limits and the shared spending cap.
- Frontend type checking and production build pass. Both desktop and mobile billing
  browser tests pass.
- SQLite migration upgrade, downgrade to 0019, and upgrade pass. The hosted preview
  schema is on revision 0020.

## Dodo Test Mode

Both test products use tax-inclusive pricing to charge the exact advertised totals.
The first checkout initially added VAT. Enabling tax-inclusive pricing corrected
the total to AED 50.

| Check | Observed result |
| --- | --- |
| First subscription payment | AED 50 succeeded as `pay_0NrgIQ5XW6VaD6efIrSt2`. Verified webhook fulfillment granted AED 10 to the QA seat. |
| Duplicate subscription webhook | Two successful deliveries left the allowance at AED 10 and persisted one payment grant. |
| Top-up | AED 20 succeeded as `pay_0Nrj0DFZRzFyDRz1ZmcSO`. The QA seat rose from AED 2 to AED 12. |
| Duplicate top-up webhook | Replaying the signed payment kept the balance at AED 12 with one top-up grant. |
| Insufficient balance | At an intentionally seeded AED 0 balance, the normal Home → Test it action displayed the insufficient-balance error and the top-up link. No simulation row was created. |
| Successful renewal | A further AED 50 payment succeeded at 15:42 UTC. The verified webhook moved the billing period to 11 November–11 December, refreshed monthly usage from AED 2 to AED 10, and retained AED 10 purchased usage. The UI showed AED 20 remaining and the database recorded three unique payment grants. |
| Real OpenAI request | Pending configuration of Kruvim's private key in the preview. The API cost settlement has been verified with a simulated OpenAI response. |

The AED 2 starting balance and AED 0 exhaustion state were seeded in the isolated QA
seat to test these boundaries. They were not produced by real OpenAI spending.
After the exhaustion check, the QA balance was restored to AED 2 monthly usage and
AED 10 purchased usage before the renewal check.

The first hosted fulfillment attempt exposed missing privileges for the preview's
dedicated database role on the new `billing_seats` table. Matching the existing
billing-table grants and role-specific RLS policy resolved the failure. The signed
payment replay then returned success and granted the allowance.

A temporary Vercel bypass header was authorized for the Dodo Test Mode webhook.
After verification, the header was removed, the endpoint was restored to its original
disabled state, and the named Vercel automation bypass was revoked.

## Broader test suite

Both failures below also reproduce at the previous preview commit `3f4af6d`.
`test_bulk_interviews.py::test_every_voice_preview_progress_and_idempotent_worker`
expects a 61-credit upfront survey debit. The current worker uses per-call receipts.
`test_source_registry.py::test_registry_crud_licence_and_private_upload` expects an
empty dataset list for a second account. The platform-only Data pool endpoint
returns HTTP 403.
