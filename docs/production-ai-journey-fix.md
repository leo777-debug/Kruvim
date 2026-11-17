# Live AI provider failure handling

Live-provider failures now stop graph extraction, environment generation, participant reactions and actions, and report outlining. Deterministic substitutes remain available in explicit dry runs. A failed live call cannot fabricate an agent answer and complete that run.

The OpenAI-compatible adapter shares a credential-digest pacing gate between clients in the same event loop. It honors advertised request-per-second/minute limits and provider Retry-After delays, with a one-minute cooldown for HTTP 429 responses without a retry header. This is process-local pacing, not a global multi-instance rate limiter.

Production inspection showed that the verification key allows only two requests per minute. A live stage can therefore legitimately exceed the hosted execution deadline. Background work now yields before that deadline and enqueues its continuation automatically, carrying the provider cooldown forward. Simulation checkpoints preserve completed reactions/actions; durable call receipts replay earlier report/graph responses without another upstream request. Usage totals are assembled from those receipts once. Interactive requests do not use this background continuation mechanism. The connection test also explains low request limits to the user.

Provider errors retain a safe provider label, error category and HTTP status in the user-facing message. Raw response bodies stay out of these messages. The existing accounting path stores redacted provider detail in the owning provider configuration. Connection-test responses include only whitelisted rate-limit headers, and provider settings no longer include the key in their object representation.

Failed report usage is retained. Worker tasks report failure to the cloud delivery wrapper, so failed stages no longer leave cloud-job rows marked done. Model choices and custom OpenAI-compatible endpoints remain available; this does not set a shared platform provider or change billing.

Live report verification also exposed truncated JSON. The common JSON helper now increases the output allowance on its one retry when an answer is incomplete, up to 8,192 tokens (without shrinking an already larger allowance). OpenAI-compatible and Anthropic output-limit metadata survives encrypted receipt replay, so a length-limited response cannot be accepted merely because a partial object happens to parse. An unfinished analyst section fails explicitly instead of being marked complete with placeholder text.

At the evidence-tool limit, report writing now switches to a separate plain-Markdown request with bounded evidence excerpts. It no longer asks the model to wrap an entire final section in tool-selection JSON. Failed/in-progress reports retain their outline and completed sections across continuations and retries, while an explicit regeneration of a completed report starts a new report. This avoids rewriting completed sections and stabilizes progress in the browser.

Regression coverage includes live-model failure without substituted entities/reactions/environment/report outlines, cloud-job error state, safe provider-error reporting, retry/pacing behavior, and the existing complete mock-provider workflow. Live production verification is recorded separately with its actual outcome.
