# Dodo Payments setup

The paywall is implemented in the FastAPI/Vite app in `Kruvim/`. It is enabled by default,
but hosted checkout remains disabled until the merchant configuration is complete.
No merchant account was created, no real payment was submitted, and no live credentials
are included in this implementation. Dodo onboarding and payout approval are separate
from implementing checkout.

## Commercial settings

- AED 50 per person per month; checkout quantity is the number of paid workspace seats.
- Each paid seat includes AED 10 of AI usage per paid billing cycle.
- An AED 20 one-time top-up adds AED 10 of AI usage to the purchasing seat.
- The billing page shows each seat's available AI usage in AED. Simulations have variable costs.
- Subscription allowance resets only on a confirmed new paid service period. Unused
  monthly allowance does not roll over. Purchased allowance is separate and does not expire;
  an active paid subscription is required to use it.
- This implementation does not promise a fixed number of simulations per month.

## Configure Dodo in test mode first

1. Create your Dodo account and complete merchant verification. Confirm individual seller
   eligibility, the accepted ID, payout bank account, exact AED pricing, and applicable fees.
2. In Dodo test mode, create a fixed recurring product in AED: **5000 minor units per seat**,
   billing every **1 month**, with no trial, discount, purchasing-power-parity reduction,
   or usage-based charges. Turn on tax-inclusive pricing. Use a sufficiently long total subscription duration (Dodo
   recommends 20 years for subscriptions that renew until cancelled).
3. Create a fixed one-time AED product for **2000 minor units**, with tax-inclusive pricing
   on and pay-what-you-want off.
   Top-ups grant local Kruvim credits; do not attach a second Dodo credit ledger to the
   products unless replacing the local ledger explicitly.
4. Add an HTTPS webhook pointing to:

   `https://YOUR_API_HOST/api/v1/billing/webhook`

   Subscribe to `payment.succeeded`, `subscription.active`, `subscription.updated`,
   `subscription.renewed`, `subscription.on_hold`, `subscription.past_due`,
   `subscription.paused`, `subscription.unpaused`, `subscription.cancelled`,
   `subscription.failed`, `subscription.expired`, `subscription.plan_changed`,
   `refund.succeeded`, `dispute.opened`, `dispute.accepted`, and `dispute.lost`.
5. Set these server/worker environment variables using your deployment's secret settings:

   ```dotenv
   KRUVIM_BILLING_ENABLED=true
   KRUVIM_PUBLIC_URL=https://YOUR_APP_HOST
   KRUVIM_DODO_ENVIRONMENT=test_mode
   KRUVIM_DODO_API_KEY=<test API key>
   KRUVIM_DODO_WEBHOOK_KEY=<webhook signing secret>
   KRUVIM_DODO_BUSINESS_ID=<Dodo business id>
   KRUVIM_DODO_SUBSCRIPTION_PRODUCT_ID=<test recurring product id>
   KRUVIM_DODO_TOPUP_PRODUCT_ID=<test one-time product id>
   KRUVIM_BILLING_OPENAI_API_KEY=<Kruvim's existing private OpenAI API key>
   ```

   Paid simulations use OpenAI directly from the server. The default model is
   `gpt-4.1-mini-2025-04-14`. To change it, set `KRUVIM_BILLING_OPENAI_MODEL` and
   configure the model's `input`, `cached`, and `output` rates in USD per million
   tokens through `KRUVIM_BILLING_MODEL_PRICES`. Confirm the model's rates in the
   [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

6. Apply migrations to the intended database: `python -m alembic upgrade head` from `backend/`.
   Back up the database before a production migration. Restart both API and workers with
   the same billing configuration.
7. Sign in as the workspace owner and open **Billing and credits** at `/usage`. Complete
   test checkout and confirm each paid seat receives AED 10 after the verified webhook.
   Check an OpenAI debit and an insufficient-balance pause. Buy the AED 20 top-up from
   the affected seat and verify its balance rises by AED 10. Use Dodo's next billing date
   control to test a successful renewal. Replay a payment webhook and confirm the
   balance is credited only once.
8. Repeat product/webhook creation in live mode; test ids and signing keys do not carry
   over. Switch `KRUVIM_DODO_ENVIRONMENT=live_mode` only after merchant approval and
   testing of the real configuration.

Checkout validates the catalog's AED amount and billing interval before redirecting.
It deliberately refuses a product priced in another currency rather than silently
charging a USD equivalent. If your Dodo account only offers adaptive AED conversion,
confirm exact local pricing with Dodo before activation. Changing public advertised
prices must be accompanied by matching Dodo product configuration.

## Payment trust and spending controls

- Subscription checkout and the billing portal require a signed-in workspace owner.
  A signed-in member can buy a top-up for their own seat. Product IDs, prices and grants
  come from server configuration.
- A return URL only displays a pending confirmation notice. It never grants access.
- Webhooks verify the raw-body Standard Webhooks HMAC, timestamp and Dodo business id.
- Each delivery id and payment id is persisted. Replays do not duplicate grants. Payment
  and subscription details are fetched from Dodo to confirm fulfilment and current status.
- Payment service periods control renewal. Authorisation alone, usage-only payments,
  plan changes and duplicate events do not reset spent monthly credits.
- Simulation writes require active paid access. History remains readable. Workspace
  membership cannot exceed paid seats. Simulations and their queued jobs charge the
  initiating seat. An API key is attributed to the member who created it.
- Refund/dispute events suspend spending for operator review. Do not automatically
  clear this flag without reconciling the payment in Dodo and the grants locally.
- Every paid platform text-model request reserves a conservative maximum cost before
  network I/O. Atomic database updates prevent concurrent overspending. Successful
  responses settle against reported uncached input, cached input, and output tokens at
  the configured rates and USD-to-AED conversion.
- Calls billed to Kruvim are limited to 120 per UTC minute per workspace and AED 100
  in total per UTC calendar month by default. Configure these with
  `KRUVIM_BILLING_AI_CALLS_PER_MINUTE` and `KRUVIM_BILLING_PLATFORM_MONTHLY_BUDGET_AED`.
  The first month counts calls made after the migration and code rollout.
- Platform requests do not automatically retry uncertain network attempts. Timeouts,
  crashes, and missing usage keep their maximum reservation, since the provider may
  still charge. An operator can reconcile these against provider logs; never automatically
  release them on a timer. Customer-owned provider retries retain their existing behavior.
- A stopped simulation saves its existing checkpoint and can resume after buying credits
  using the existing resume endpoint. The watchdog also checks eligible paused work.
- Paid simulations use text inference and the local embedding fallback. Provide
  transcripts for video and audio inputs.
- Existing workspace-wide monthly funds are divided among the paid seats during the
  transition. Legacy purchased balances go to the workspace owner, who could place those
  orders. Existing top-ups retain the allowance quoted at checkout.
- A hard cap depends on accurate provider rates and the provider honoring token limits.
  An unexpected charge above its reserved bound suspends further use for review.

## Verification

Backend tests use signed fixture webhooks, mocked Dodo HTTP responses and isolated temporary
databases; they do not make real payments. Browser tests exercise the unconfigured billing
page at desktop/mobile sizes against a disposable server. A live Dodo sandbox transaction
remains an activation check once credentials are available.

Official references:

- https://docs.dodopayments.com/developer-resources/checkout-session
- https://docs.dodopayments.com/developer-resources/subscription-integration-guide
- https://docs.dodopayments.com/developer-resources/webhooks
- https://docs.dodopayments.com/miscellaneous/verification-process
