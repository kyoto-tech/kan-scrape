---
name: kansai-events
description: Scrape upcoming meetups and events in Kyoto, Osaka, Kobe, Nara (Kansai) from Meetup, Doorkeeper and Connpass. Use when asked what's on in Kansai, to find a meetup/event matching some interest or date, or to list upcoming events of a Meetup group.
---

# Kansai events

`scripts/kansai_events.py` (in this skill's directory) is the scraping half of the Kan Scrape
app as a standalone `uv` script. The app's voice + LLM matching layer is replaced by you:
scrape broadly, then pick and pitch the matches yourself.

```bash
S=<skill-dir>/scripts/kansai_events.py
$S --days 7 --format md                      # next week, everything, readable
$S --city Kyoto Online --days 14             # JSON, filtered by city
$S --grep python "language exchange" --limit 20
$S --groups oktech kansaihikes               # specific Meetup group slugs only
```

Run `$S --help` for all flags. Output is JSON (default) or Markdown on stdout; per-source counts
and skipped/failed feeds go to stderr. Times are JST.

## Matching a request

1. Translate the request into loose filters: `--days` for the time window, `--city` only when
   the user named a place. Keep `--grep` off or broad: it is a case-insensitive **substring**
   match (`ai` hits "Kans**ai**"), so it drops good events and keeps noise.
2. Read the JSON titles and descriptions and choose the best 1–5 yourself. Include date, time,
   city and URL for each; answer in the user's language.
3. Nothing fits → say so and offer the nearest alternatives from the same scrape.

## Sources and their quirks

- **Meetup** — public iCal feeds, no key. Default group list is built in (`DEFAULT_MEETUP_GROUPS`
  in the script); a slug is the path segment in `meetup.com/<slug>/`. Feeds only carry each
  group's next ~10 events.
- **Doorkeeper** — needs `DOORKEEPER_TOKEN`; queries Kyoto/Osaka/Hyogo prefectures.
- **Connpass** — needs `CONNPASS_API_KEY` (v2 API); tech events in Kyoto/Osaka/Hyogo.
- Missing credentials skip the source with a stderr note; a dead feed yields 0 events, never an
  error exit.
- `city` is a keyword heuristic over location/title/description, then the group name. Meetup
  events often lack a location, so a hike tagged `Kyoto` may be in Osaka prefecture; check the
  description before promising a place. Some default groups (e.g. the VC/careers one) also list
  events outside Japan, which land in `Other`.
- Duplicates (same normalised title + day across sources) are collapsed; past events dropped.
