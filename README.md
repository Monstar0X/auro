# Quorum

**A fair-decision engine, taste-DNA profiler and spoiler shield for anime Telegram groups, as a bot + Mini App in one deployable service.**

Every anime group chat has the same three problems: *what do we watch tonight?* (and someone always loses),
*who even is this person's taste?*, and *somebody just spoiled episode 9*. Quorum solves all three with real math
on top of AniList data, and it needs no file hosting, so it complements the bots you already run
(filestore, filters, posters, news) instead of duplicating them.

---

## What it does

### 1. Group Night: a fair "what do we watch?" engine  (`/night`)
* Anyone in the group opens the **swipe Mini App** (Tinder-style: like / nope / super-like / **veto**).
* Quorum predicts, for every candidate show, **how much each member would score it** (from their AniList history).
* It combines those predictions with a **weighted geometric mean (Nash bargaining)** instead of an average, so a pick
  one person hates is punished much harder than a pick everyone finds "pretty good".
* **Fairness has memory.** After each night, every member's *regret* (how far the winner was from their personal best)
  is stored per chat. Members who lost last time get a heavier weight next time (up to 3x). Over weeks the group's
  choices even out by themselves, and the verdict names who "took one for the team".
* **Swipes teach the engine live.** Each swipe is folded into the swiper's taste profile for the session, so the deck
  re-ranks itself as the night goes on. Guests without an AniList still participate purely through swipes.
* **Hard rules:** a veto removes a show for everyone; anything any member has already watched is excluded
  (unless `rewatch`); `max=13` caps episodes; 18+ is off unless `adult`.
* **Moods:** `cozy`, `hype`, `mindbender`, `cry`, `spooky` tilt the ranking toward matching genres/tags.
* Result: a shareable **verdict card** (PNG) with per-member predicted enjoyment, runtime, badge
  (*Crowd-pleaser / Bold compromise / Swipe favourite*) and a **fairness %**.
* No Mini App? **Quick vote** inside the chat message works with plain inline buttons.

### 2. Taste DNA  (`/dna`)
Builds a taste profile from a public AniList list (ratings centred on *your own* average, drops count as negative
signal, shrinkage so tiny samples don't dominate) and renders a **card**: archetype
(*The Mastermind, The Heart-Wrecker, The Night Owl...*), genre radar, judge style, "explorer" score and how generous
you are versus the crowd.

### 3. Compatibility + bridge picks  (`/compat`, reply to someone)
Cosine similarity of taste vectors blended with rating agreement on shared titles, plus friction genres, shared
favourites and **bridge picks**: shows both of you are predicted to enjoy.

### 4. Spoiler Shield  (`/spoiler`, `/progress`, `/watching`)
* `/spoiler 6 Himmel is already dead` (or `/spoiler Frieren | 6 | ...`): the bot **deletes your message** and
  posts a locked card. The text lives only in the database, never in the chat.
* Tapping **Reveal** shows the text in a private pop-up **only if that person's progress >= the episode**
  (progress comes from AniList or `/progress`). Behind? They get "You're on episode 3; this spoils episode 6".
  There is a deliberate **Reveal anyway** skull button for the brave.
* `/watching <title>` sets the group's current show and announces **new episodes** when they air.

### 5. Privacy
`/forget` deletes everything stored about you (list cache, swipes, progress, regret, profile).
Only *public* AniList data is read; no AniList login is ever requested.

---

## Commands

| Command | Where | What |
|---|---|---|
| `/link <anilist>` | anywhere | connect your public AniList |
| `/dna` | anywhere | your Taste DNA card |
| `/compat` | group (reply) | compatibility + bridge picks |
| `/night [mood] [max=N] [rewatch] [adult]` | group | start a fair movie night |
| `/spoiler <ep> <text>` or `<Title> \| <ep> \| <text>` | group | post a locked spoiler |
| `/progress [Title \|] <ep>` | anywhere | tell Quorum how far you are |
| `/watching <title>` | group | set current show + airing alerts |
| `/forget` | anywhere | delete your data |

BotFather command list:
```
link - Connect your AniList
dna - Your Taste DNA card
compat - Reply to someone: compatibility
night - Start a fair movie night
spoiler - Post a spoiler behind a lock
progress - Set how far you've watched
watching - Set the group's current show
forget - Delete my data
help - How it works
```

---

## Setup (about 10 minutes)

1. Create a bot with @BotFather; get `API_ID` / `API_HASH` from https://my.telegram.org/apps.
2. Deploy (Docker / Render / Railway / Heroku, a `Dockerfile`, `Procfile` and `render.yaml` are included).
   Copy `.env.example` to `.env` (or set the variables on your host) and fill them in.
   `PUBLIC_URL` must be the **https** URL of the deployed service.
3. In @BotFather: `/newapp` -> pick your bot -> Web App URL = your `PUBLIC_URL` -> short name e.g. `quorum`.
   Put the resulting link (`https://t.me/YourBot/quorum`) into `MINIAPP_LINK`. This is what makes the **Swipe**
   button open the Mini App from inside *groups*.
4. In @BotFather: `/setcommands` with the list above. Add the bot to your group and give it
   **Delete messages** admin rights (needed for Spoiler Shield to remove the original message).
5. Run it: `python main.py`.

> Storage is SQLite (`DB_PATH`). On hosts with ephemeral disks mount a volume at `/app/data`, otherwise
> history and fairness memory reset on every deploy.

### Try it with zero setup (no Telegram, no internet)
```bash
pip install pillow
QUORUM_DEMO=1 DEV_AUTH=1 python main.py
# open http://localhost:8080/?dev=1:Alice&night=1   (add &dev=2:Ben in another tab to be someone else)
```
Demo mode swaps AniList for built-in fixtures and seeds three friends with different tastes plus an open night.
`DEV_AUTH` skips Telegram signature checks, so **never enable it in production**.

### Tests
```bash
python -m unittest discover -s tests -t .      # 40 tests, ~6 s, no network or Telegram needed
```
They cover the taste model, the consensus maths (veto, rewatch, episode caps, Nash penalty, regret feedback,
determinism), the service layer, Telegram initData signature checking, the HTTP API over a real socket,
PNG rendering, and all bot handlers against a stubbed Kurigram.

---

## How it works

```
 Telegram group --- bot.py (Kurigram handlers, thin) ---+
                                                        +--> service.py --> consensus.py (Nash + regret)
 Telegram Mini App --- server.py (stdlib HTTP + API) ---+               +-> taste.py     (profiles, DNA, compat)
        webapp/ (vanilla JS swipe UI)                                    +-> card.py      (Pillow PNG cards)
                                                         anilist.py (GraphQL)  /  demo.py (offline fixtures)
                                                         db.py (SQLite)
```

**Prediction.** For a show with features *F* (genres at full strength, top tags weighted by AniList rank) and a user
with weights *w*: `score = mean_eff + 32 * avg_f(w_f) + 0.5 * (community - 72)`. Each weight is
`sum(signal) / (support + 2)`, where signal is `(your score - your mean) / 20`, so one lucky 10/10 can't define you.

**Group score.** Satisfaction `u = clamp((score - 40) / 60)`; group = `exp( sum(w_m * ln u_m) / sum(w_m) ) * 100`
with `w_m = 1 + 2 * regret_m`. After the verdict, `regret_m = 0.5 * old + 0.5 * (best_possible_m - score_m) / 60`.

**Security.** Mini App requests are authenticated by verifying Telegram's `initData` HMAC (and 24 h freshness);
only the person who started a night (or an owner) can lock it; request bodies are size-limited; static files are
served from an allow-listed directory; every user-supplied string shown in Telegram is HTML-escaped.

---

## Honest notes
* **Verified here:** all logic, the HTTP API, auth, card rendering, JS syntax and every bot handler (against a stub).
* **Not verified here:** the sandbox this was built in has no internet, so it was not run against live Telegram or
  the live AniList API, and the swipe UI was not exercised in a real browser/WebView. Expect to do one smoke test:
  `/link <you>`, `/night`, swipe, lock. If AniList changes a field, the single place to fix is `quorum/anilist.py`.
* Telegram pop-ups hold at most 200 characters, so spoilers are limited to 190 characters.
* Predictions are only as good as the lists behind them. Brand-new accounts fall back to the community score
  plus whatever they swipe.
* Why this exists: existing AniList bots mostly do lookups, airing alerts and manual "suggest a show" watch
  parties (one Discord bot, for example). I did not find one that combines predicted per-member enjoyment, Nash-style
  group choice with cross-session fairness, live-learning swipes and progress-gated spoilers. Treat "nobody has this"
  as "I couldn't find it", not as a guarantee.

Licence: MIT. Data from AniList (https://anilist.co), used under their API terms; cover art belongs to its owners.
