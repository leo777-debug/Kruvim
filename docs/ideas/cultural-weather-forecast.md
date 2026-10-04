# Idea: Kruvim as the weather forecast for culture

Saved 2026-10-04. The long-term moat idea. Start with the small version (Forecast Lite, below); grow into the
living world over time.

## The insight
Weather forecasters don't predict tomorrow from scratch. They keep one model of the atmosphere running all the
time, correct it every hour with new readings, and publish forecasts every day, in public, with probabilities,
so everyone can see when they are right. Nobody does this for society:
- MiroFish builds a new world from uploaded documents, runs it once and throws it away.
- Aaru makes private predictions for clients and proves accuracy only now and then.

Kruvim would run one living, simulated UAE that never stops. Agents live through each real day (news, trends,
Ramadan, payday, weather). Reality corrects it every hour. Every day it publishes a public forecast of
tomorrow's culture, scored the next day against what actually happened.

## What people see (free page and app, "Kruvim Forecast")
> **Tomorrow in the UAE**
> - Rising: a 72% chance the Gulf Cup match takes over the conversation by evening
> - Mood: humour is up, and outrage is low
> - Storm warning: a rumour about school fees is likely to spread fast among parents in Sharjah
> - Best time to post for 18-24s: 9:40pm, after iftar
> - Yesterday's forecast: 7 of 10 calls were right (public scoreboard)

## Money (individuals first)
- Free: the daily forecast, the public scoreboard, shareable forecast cards.
- Paid:
  - "Drop it into tomorrow": put your reel, headline or post into the living world and see how it plays out
    against tomorrow's real trends
  - personal forecast for your niche
  - story weather and rumour alerts for journalists
  - best time to post
- Companies later: "fork the world", a private copy of today's simulated UAE to test a launch or a crisis
  against the version where they did nothing.

## Why it eats MiroFish and Aaru
- MiroFish starts from a blank page; Kruvim's world already exists, is current and has a public record of being
  right.
- Aaru asks clients to trust private predictions; Kruvim's accuracy is public every day.
- Uploading your own documents becomes a fork of the living world.

## Why it is a moat
1. Time can't be copied: a public, dated forecast record takes months and years to build.
2. It gets smarter every hour it runs; a competitor's new world starts young and wrong.
3. It's a daily habit (like checking the weather), not an occasional tool.
4. It creates and owns a new category: cultural weather.

## Attention
- Daily forecast posts, scoreboard wins ("we called it 2 days early").
- A media partner running a daily "Kruvim Culture Forecast".
- "Beat Kruvim": people predict against the AI for points (no money).

## The noble part
Storm warnings for society: early warning when a rumour, panic or hateful wave is about to spread, so
journalists, schools and communities can respond. The public forecast stays free.

## Honest catches
- Weak forecasts at first: be honest with probabilities and a daily score, and always compare with a simple
  baseline.
- Running cost: a few dollars a day per city with a cheap model; expand city by city.
- Ground rules: topics and moods only, never individuals; no market-moving financial calls; label everything as
  simulated.

## Phases
1. **Forecast Lite (solo, about 1-2 weekends):** one LLM call a day turns the data pool's last 7 days into 10
   checkable forecasts for the UAE; scored automatically the next day; public page and scoreboard. The prompt
   is in [forecast-lite-codex-prompt.md](forecast-lite-codex-prompt.md).
2. **Drop it into tomorrow:** paid creators run their content against tomorrow's forecast context (reuses the
   existing simulation).
3. **The living world:** the always-running, hourly-corrected simulated UAE, then fork-the-world for companies.
