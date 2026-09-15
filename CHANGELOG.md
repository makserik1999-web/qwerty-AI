# Changelog

All notable changes to Anyq are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Housekeeping: three silent bugs, and the disk leak behind every render

**Fixed**

- **Telemetry recorded two fields and then threw them away.** `record()` writes
  `video_length` and `narration_chars`; `write()` builds its line from a fixed
  list of keys, and neither was on it. So the one question the length control
  exists to answer - did the video come out the length that was asked for -
  could not be answered from the run log at all.
- **Every JS and CSS response lost `X-Content-Type-Options`.** The same nginx
  inheritance trap as `index.html`: `add_header Cache-Control` in the static
  asset block replaced every inherited header, and nosniff is the one that
  matters for a script. Measured on the running stack - assets came back with
  none. It is repeated in that block now, with a test to keep it repeated.
  The block also set `expires` *and* `add_header Cache-Control`, so every asset
  carried two different Cache-Control headers; now one.
- **`scripts/run_check.sh` called a script that does not exist** (`agent/check.sh`
  moved to `scripts/check.sh`) and pointed `PYTHONPATH` at a stub directory that
  was deleted. `scripts/check.sh` builds its own stub, so the wrapper did
  nothing but fail. Removed, along with `dbg.sh`/`dbg2.sh`/`dbg3.sh` - dead
  debugging leftovers carrying a hardcoded personal absolute path.

**Fixed - the render left its working tree behind, every time**

`media/videos/<script>/` holds the partial movie files and `Demo.wav`, the
uncompressed narration, about 10 MB per video. Nothing ever removed it:
**66 MB from eight renders**, growing about 8 MB with every question anybody
asks. `retention.py` governs `outputs/`; this directory was governed by nothing.

It is named after the temporary script, so it belongs to one render and nothing
else can reference it, and the finished mp4 has already been moved to
`outputs/` by then - so it goes in the same `finally` that removes the script.
A cleanup failure is logged and never propagates: a disk that fills up slowly
beats a video lost to tidying.

Verified live: the directory exists during a render and is gone after it, with
the video in `outputs/` and no `.wav` left. The media volume went 189 MB -> 124 MB
including a one-off sweep of what had already piled up.

### The animations were slow, and things dissolved on top of each other

**Fixed - one rule in the prompt was causing both**

Reported from watching the videos: everything faded in and out too slowly, and
worse, a new caption appeared while the old one was still leaving, so for the
length of the transition the frame was an unreadable mixture of the two.

Rule 15 required `run_time=tracker.duration` on every animation, which
stretched each one across its whole spoken sentence - a five-second sentence
bought a five-second fade. It was never needed: manim-voiceover's `voiceover`
block calls `wait_for_voiceover()` when it exits, so the block already lasts
exactly as long as its audio whatever happened inside it. Rule L1 swapped
captions with `Transform(caption, Text(...))`, which morphs the letter shapes
of one string into another's - and spent those five seconds doing it. L2's
fallback, `self.play(FadeOut(old), FadeIn(new))`, plays both at once.

- Rules 15, 16, L1, L2 and L8 now say the opposite: a departure is its own
  `self.play` and comes first; `Transform` is for shapes that really do become
  one another, never for swapping one sentence for another; `run_time` is
  0.3-1.0s and a longer sentence means a longer still, not a slower animation.
- **A pacing guard enforces it mechanically**, because the prompt is a request
  and this is a property. A `self.play` that both removes and adds is split in
  two, and any `run_time` written as a share of the sentence is capped
  (`ANIM_RUN_TIME_CAP`, default 1.0s; departures `ANIM_EXIT_RUN_TIME`, 0.35s).
  It rewrites only the statements it touches, so comments, spacing and the
  exact bytes of every spoken line survive - the narration manifest is keyed
  on those, and a changed byte is a silent video.
- The silent variant now pads each block to the length the sentence would have
  taken, the way `wait_for_voiceover` does on the narrated path. It never did,
  which was invisible while every animation filled its block and would have
  made a narration-off video a third of the length the moment they stopped.
- `PIPELINE_VERSION` v3 -> v4, so stored answers made by the old pipeline are
  retired rather than served.

**Verified on real renders, not only in tests**

The same question rendered before and after. The script the model now writes
has 13 `self.play` calls, none of them mixing a removal with an arrival, none
with a stretched `run_time`, and no text-into-text Transform - the guard found
nothing left to do. Contact sheets of both videos, one frame per second: the
old one has captions visibly smeared over each other at four of the
transitions, the new one has one clean caption in every frame. Length is
unchanged (50.9s -> 53.4s), which is correct - the narration sets that, not the
animations. A silent render of three 60-character sentences came out at exactly
15.000s against the 2.1s its animations add up to.

### Deleting a question from the history, and a deploy that reached nobody

**Added**

- `DELETE /api/chats/{chat_id}`, and a delete button on each history row. The
  operation is not new - the `delete_chat` socket frame has always had it - but
  the history is read over REST, so the entry a person wants gone is now
  addressed the same way rather than through a connection that may not be open.
  Ownership is checked inside the delete: the id is matched together with the
  user, so somebody else's chat is not found rather than removed.
- The button is hidden until the row is hovered or something in it has focus. A
  bin beside every question is a list that looks like it is mostly about
  deleting. Coarse pointers have no hover, so there it is always shown.

**Fixed - index.html was cached, so deployed fixes did not reach open tabs**

It carried no `Cache-Control` at all, which is not "do not cache": with no
directive the browser is free to guess, and it guesses from `Last-Modified`.
index.html holds the hashed names of the bundles - the assets are immutable for
a year precisely because their names change, and this is the only file that
says which names to ask for. A stale copy therefore pins the browser to the old
build, and the symptom is a fix that is live on the server and absent on the
screen. That is what happened to the history fix below.

Done with `expires -1` rather than `add_header`, and there is a test for that
specifically: nginx inherits `add_header` from the enclosing level ONLY when the
level defines none of its own, so an `add_header Cache-Control` here would have
silently stripped the CSP, the frame-ancestors and the nosniff from the one
response that is an actual document.

### Clicking a history entry with no answer did nothing at all

**Fixed**

The entry is real; the answer behind it is not. A chat is created before the
question is sent, so one that was refused, lost or never finished stays in the
list with the question as its title and nothing inside it - three such rows were
left by the dead-socket bug below. `explanationFromChat` returns null for a chat
with no assistant message, and `openConversation` returned on null without a
word: no answer, no message, not even a change of selection. It reads as a
broken interface, when in fact the question is the thing that went missing.

- A question with no answer now goes back into the input box with a line saying
  so; the error card's Retry - which already exists - asks it again, which is
  what the click was reaching for.
- A chat that cannot be read says that instead of swallowing it.
- The empty rows are left in place. "This question never got an answer" is a
  truer history than a row that quietly disappears.

### A request written into a dead socket was charged, queued, and lost

**Fixed (live, and it locked a user out for half an hour)**

The agent container restarted; it spent about twenty-five seconds reconnecting
and a question arrived in that window. The backend still held the old socket -
nothing had declared it dead, because the websocket ping timeout is ninety
seconds - and `send_json` on it did not fail. It cannot: a TCP connection whose
far end has gone still accepts bytes into the kernel buffer and the write
returns.

So the quota was charged, the request was entered in `pending_requests` as a
generation in progress, and the person was told to wait. Nothing was working on
it. `GENERATION_MAX_CONCURRENT=1` then refused every later question with "your
previous video is still being made" until the half-hour TTL sweep - the only
thing that ever clears an entry nobody answers. Any drop of the agent
connection reproduced it.

- **The agent now confirms every generation frame the moment it comes off the
  wire**, and a send is not finished until that confirmation arrives
  (`AGENT_ACK_TIMEOUT_SEC`, default 20s). A request that was never confirmed is
  refunded, cleared, and reported as something to try again - in seconds rather
  than in thirty minutes.
- Declared as the `ack` feature at handshake, so a backend talking to an older
  agent does not wait for a confirmation that is never sent.
- A drop or a reconnect releases every waiting sender at once. The socket is
  already known to be dead; making people sit out the timeout to be told so
  would be the same bug in smaller print.

**Changed - the agent reads and works in separate tasks**

Reading and rendering used to be one loop, so the agent read nothing for the
ninety seconds a render takes. Everything sent in that window sat unread in the
socket buffer, which is precisely why it could not answer "have you got it?".
Frames are now read continuously and generations run from a queue.

Still strictly one generation at a time - the queue is what changed, not the
pace. The worker outlives any single connection on purpose: a socket that drops
mid-render must not throw away work that is minutes old, so the answer goes out
on whichever connection exists when it is finished. Held answers are a list
rather than the single slot they were, because a second one can now finish
before the first has been handed over.

### Phase C1 L2 - the semantic cache layer, and two language bugs

**Fixed (both live, both silent)**

- Kazakh was detected only by its own letters (ә ғ қ ң ө ұ ү һ і), so
  "фотосинтез деген не" - the ordinary way to ask "what is photosynthesis" -
  had none and was answered **in Russian**. Kazakh function words are now
  recognised too, anchored on word boundaries so "осы" inside the Russian
  "волосы" does not turn a hair question Kazakh.
- Latin text was not detected at all and the fallback is Kazakh, so an
  **English question came back in Kazakh**. A formula like "E = mc^2" still
  counts as no language and falls back, rather than being called English.

**Added**

- A semantic cache layer: the same question asked in different words now
  finds the stored answer. Measured live at 0.8s against 89s for a fresh
  generation.
- Embeddings come from the agent over a new `embed` frame, because that is
  where the Gemini key lives - OpenRouter, which now serves chat, has no
  embedding models at all. 768 dimensions rather than the native 3072:
  measured identical to the third decimal at a quarter of the storage.
- The agent declares its features at handshake, and the backend will not send
  an embed frame to a build that does not list `embed`. Without this, a
  rolling deploy would have an older agent read the frame as a question and
  render a video of it.
- A semantic hit shows which stored question it matched, so a reader can see
  it is not what they meant and use the existing "Generate a new one".

**Calibration, not guesswork**

The plan proposed a 0.92 threshold with no language rule. Measured on labelled
pairs of this product's own questions, that is exactly wrong:

| | cosine |
|---|---|
| same question, kk vs ru | **0.920** |
| same question, one language, different words | 0.701 - 0.937 |
| genuinely different questions | 0.633 - 0.797 |

At 0.92 the first thing matched is a Kazakh question against a Russian video.
So matching never crosses languages - not a tuning knob - and the threshold is
**0.85**, above every observed different-question pair. That gives up about
half the paraphrases on purpose: the bands overlap, and a false hit answers a
question nobody asked. The measured scores are kept as a test, so moving the
threshold moves the test.

**Fixed during the work**

- `remember()` awaited the agent's embedding reply from inside the agent's own
  receive loop - the only place that reply could ever be read. It deadlocked
  until the timeout, silently, and no answer ever got a vector. The write is
  now a background task, with a regression test that fails if it is awaited
  again.

**Note**

- Entries stored before this have no vector and no language; they stay
  exact-match only rather than being matched unsafely.


### Phase F6 - generation quotas

**Added**

- Per-user generation limits, because closing the service behind a login
  stopped anonymous abuse and nothing else: signup is open, and one account
  could previously queue unbounded renders and hold the only agent.
- **One generation at a time per user** - the limit that actually protects the
  agent. A render occupies it for about 90 seconds, so a single slot means
  nobody can enqueue faster than the queue drains.
- 15 per hour and 50 per day, as comfort ceilings on top of that. A global
  queue cap of 20 answers honestly instead of promising a place in a line
  nobody can reach.
- **Answers from the library do not count**, so the cache doubles as load
  protection rather than being taxed. **Failed generations are refunded** - on
  agent error, on agent disconnect, and on the pending-request sweep.
- Counters live in Mongo, not in memory: an in-memory budget would make
  "crash the backend" a quota bypass.
- `GET /api/quota`, and a line above the composer that appears only when the
  budget is running low.
- Signup rate limit, 100 per IP per hour. Deliberately loose: a school
  computer room shares one address, and this is not the limit that bounds
  cost. It is in-memory, so restarting the backend clears it.

**Fixed**

- The budget line never appeared: the quota was fetched once at mount, before
  login, and nothing re-triggered it after the session existed.

**Note**

- A full test run creates around 50 accounts from one address. Raise
  `SIGNUP_MAX_PER_HOUR` on a stack you test against, or restart the backend.


### Phase E - export

**Added**

- A new `exporter` service. Encoding lives outside the other two on purpose:
  the agent runs on a read-only rootfs so LLM-written Manim cannot do damage,
  and an encode inside the backend's event loop would stall every request for
  its duration - including the status polls asking how it is going.
- `POST /api/export`, `GET /api/export/{id}`, `GET /api/export/{id}/download`.
  Jobs are addressed by message, so the server checks the chat is yours; a
  finished file is downloadable only by the user whose job produced it.
- Cut a fragment as a **GIF or an mp4 clip**. Both formats are equally visible
  buttons with a live size estimate under each; mp4 is preselected because it
  measures ~6x smaller on this product's own output, but GIF is not hidden.
- Size budget with shrink-and-retry: a result over `EXPORT_MAX_OUTPUT_BYTES`
  is rebuilt at a lower width, then a lower frame rate, twice at most.
  Selections are capped at 15 seconds, refused while the dialog is open
  rather than after a minute of encoding.
- "Download" on the player: `/media/{file}?download=1` names the file after
  the question it answers, transliterating Kazakh and Russian for the ASCII
  half of the RFC 6266 header.
- "Deck": a PowerPoint built from the explanation, one slide per step. Frames
  are chosen by ffmpeg scene detection rather than at fixed intervals, so the
  slides land on the animation's own steps instead of mid-transition. The
  full paragraph goes into the speaker notes.
- 5 exports per hour per user; results are swept after 24 hours, file first
  so a crash between the two retries rather than leaks.

**Fixed**

- `?download=1` named the file after whichever message shared the video URL,
  which - because the answer cache serves one rendered file to everyone who
  asks the same question - was very often **another user's wording**. The
  lookup is now scoped to the caller's own chats, with a neutral fallback.
- `transliterate("Жер")` produced "ZHer": a multi-letter replacement was
  upper-cased whole instead of capitalised.

**Known gaps**

- The quiz slide the plan sketches is not built: it needs a model to write
  the questions, and the exporter deliberately holds no API key.
- Exports are swept on a fixed TTL and are not part of the media disk budget.


### Phase C (in progress) - the answer cache

**Added**

- Answers are cached and repeats are served in milliseconds. Storage policy:
  every question increments a small counter, an answer starts in a 48-hour
  tier, and it only earns 30-day storage once the question actually comes
  back. Curated entries never expire.
- Not cached, deliberately: anything with a screenshot, prompts over 200
  characters, personal requests ("реши мою задачу"), and text-only replies -
  which is what refusals and degraded-mode notices look like.
- Media retention with a disk budget (`MEDIA_MAX_BYTES`, default 20GB).
  Collection runs hourly, only above the high-water mark, and scores files by
  hits, recency and size. Curated videos and anything under 24 hours old are
  never deleted; when it cannot free enough it says so instead of deleting
  protected content. Deleting a file also clears the references to it, so old
  chats lose the video rather than gaining a broken player.
- `/api/admin/cache/stats`, behind a username allowlist.
- Cached answers are labelled "From the library" and offer "Generate a new
  one", which re-asks with the cache bypassed.
- The curated library: hand-reviewed topics under `content/curated/`, rendered
  and published by `scripts/seed_library.py`. One `scene.py` per topic with
  every string in `strings.{kk,ru,en}.yaml`, so the animation is reviewed once
  and each extra language costs only a read-through.
- `seed_library.py --check` validates content without Docker: caption keys
  agreeing across languages, every `S["..."]` the animation reads existing,
  no translation hardcoded into the shared scene, no language left without
  aliases. `--preview` renders every language without publishing, because a
  video cannot be approved before it exists.
- Nothing is published without an explicit approval record in `topic.yaml`,
  per language. A language goes live as soon as it is approved, without
  waiting for the others; an unapproved animation blocks all of them.
- Aliases removed from `topic.yaml` are retired on the next publish, so a
  wording that was dropped stops resolving.
- A published video is reused when only `PIPELINE_VERSION` changed - the
  script is frozen in git, so re-registering is enough. `--rerender` forces
  a new render for a changed scene.

**Changed**

- The live LLM path now goes through OpenRouter (`DEFAULT_LLM_PROVIDER=openrouter`)
  on `google/gemini-3.7-flash`. The previous `gemini-3-flash-preview` is on
  Google's deprecation list. One key reaches every model, so trying another is
  an env change rather than a code change. Screenshot analysis still calls the
  Google API directly and still needs `GEMINI_API_KEY`.


### Phase B1 - backend/main.py split into a package

**Changed**

- `backend/main.py` (1149 lines: config, database, auth, four routers, two
  WebSocket endpoints and the connection managers in one file) is now the
  `backend/app/` package. The largest module is 199 lines.
- `backend/main.py` remains as a 13-line entry point, because the image runs
  `uvicorn main:app`; the Dockerfile is unchanged.
- Routes are registered through `APIRouter` instead of `@app.*` decorators.
  The route table is identical - same paths, same methods, same handlers.
- `api/media.py` reads `config.MEDIA_DIR` at call time rather than binding it
  at import, so tests can point it at a temporary directory.

Behaviour is unchanged by design (the standing refactoring rule): names,
signatures and comments were moved verbatim. Verified by an AST diff showing
all 59 functions/classes and all 31 module constants still present, an
identical route table, and the full test suite passing with **unchanged test
bodies** - only the conftest wiring moved.


### Phase D (partial) - the video player

**Fixed**

- **The scrub bar could not seek.** Three independent causes, all measured on
  the running stack:
  1. `/media` ignored `Range` (starlette 0.36's `FileResponse` always answers
     200). Asking for 101 bytes of a 784KB video returned all 784KB. Range is
     now implemented in the endpoint, with `ETag`, `If-Range` and 416.
  2. Manim wrote the `moov` atom at the END of the file (measured at 99% of
     the way in), so the browser could not build a seek index without
     downloading everything. Renders are now remuxed with `+faststart`.
  3. The client cleared its "seeking" flag from `mouseup` on the range input;
     releasing anywhere else stranded the flag and froze the bar. Replaced
     with a pointer-capture bar driven by the video's `seeking`/`seeked`.
- **The brush turned itself on.** The canvas took pointer events whenever the
  video was paused, so clicks meant to resume playback drew instead. Drawing
  is now an explicit toggle (button or `D`), off by default.
- `message_count` was 0 for every chat: the aggregation joined an ObjectId
  against a string `chat_id`.
- Error bubbles rendered as `role: "assistant"`, so a failed pipeline looked
  like an answer. They now carry `data-role="error"`.

**Changed**

- `VideoPanel.tsx` (756 lines) split into `features/player/`.
- Canvas honours `devicePixelRatio` and survives a resize; annotations are no
  longer wiped when playback resumes; the pen has a colour palette; player
  controls carry ARIA roles and labels.
- Keyboard: space play/pause, arrows seek 5s (10s with shift), `D` draw mode,
  `P`/`E` pen and eraser.


### Phase A - repository cleanup and structure

**Security**

- Removed `logs/cookies.txt`, which held a live `anyq_session` token valid into
  September 2026, and `logs/sig.json`, which held the `e2e_user` password.
  Test credentials are now generated per run instead of living on disk.

**Added**

- `tests/` - the smoke, e2e and UI scripts from `logs/` rewritten as a pytest
  suite. `tests/backend` and `tests/agent` run with no Docker; `tests/e2e` and
  `tests/ui` are marked and skipped unless `ANYQ_STACK_UP=1`.
- `pyproject.toml` with a ruff configuration, `pytest.ini`, `requirements-dev.txt`.
- `Makefile` replacing the macOS-only `start.sh` (`make up/down/test/lint`).
- `.github/workflows/ci.yml` - lint plus tests for python, lint plus build for
  the frontend, and a docker build of every service.
- `.editorconfig`, `CHANGELOG.md`.

**Changed**

- Docs moved to `docs/`: `AUDIT_2026-08.md`, `REFACTORING_NOTES.md`,
  `PROJECT_MEMORY.md`, `IMPROVEMENT_PLAN.md`.
- Debug scripts moved to `scripts/`; `agent/check.sh` moved there too.
- Containers and the network renamed `spoon-*` to `anyq-*`. Named volumes are
  unchanged, so no data is affected - but run `docker compose down` **before**
  the first `make up` on the new names, otherwise the old `spoon-*` containers
  linger as orphans.
- Default `DATABASE_NAME` is now `anyq_db` in both `backend/main.py` and
  `docker-compose.yml`, matching the README and the existing `.env`. Deployments
  that relied on the old `spoon_chat` fallback (i.e. never set `DATABASE_NAME`)
  must set it explicitly or migrate the database.
- Default model in `docker-compose.yml` is now `gemini-3-flash-preview`,
  matching the README and `.env`.
- `signup` now raises its 409 with `from None`, so a Mongo `DuplicateKeyError`
  can never surface in a traceback.

**Removed**

- `logs/` in its entirety - it mixed tests, debug scripts, a virtualenv,
  run artefacts and credentials.
- `frontend/dist/` and `compose_up*.log` build artefacts; `start.sh`.
