# Changelog

All notable changes to Anyq are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

### Motion layer, behind MOTION_LAYER=1

Off by default; with it off, the prompt, the guards and the renderer are
exactly what they were. Turning it on changes every new video, so raise
PIPELINE_VERSION in the same deploy.

**Added**

- MotionScene (agent/manim-mcp-server/src/anyq_motion.py): the narrated scene
  with a background layer - a dark blue backdrop that slowly breathes,
  drifting particles and a progress bar along the top, all computed from the
  scene clock on every frame. Colours taken from the reference videos. The
  camera draws the layer under everything and it is not one of the scene's
  mobjects, so a script that fades out or clears self.mobjects cannot take it
  away.
- With the flag on, the prompt names MotionScene as the base class, and a
  guard rewrites any scene base the model writes to it - after every rewrite
  and repair too. A script that still does not subclass it is not rendered.
- Telemetry records whether a run had the layer (`motion_layer`).
- Idle motion: once a shape is on screen it floats on a small circle - 1.5%
  of its size, 0.02 to 0.07 units - and a round one also pulses. A circle,
  not a bob, so it never stands still mid-cycle; it eases in, and picks up
  from wherever an animation of the shape left it. Text, formulas, lines,
  arrows, axes and graphs never move, nor does a group with a label in it,
  a shape the script moves itself, or one wider than 60% of the frame.
- Changes of step morph instead of fading to an empty frame. Under the flag
  rule L8 asks for TransformMatchingTex between two forms of a formula and
  ReplacementTransform between two shapes, with formulas written in parts so
  the matching parts travel. A guard rewrites the plain "fade the old one
  out, write the new one in" pairs the model still writes - only for two
  formulas or two shapes, in the same block, when the old one is not used
  again; captions are never morphed. Telemetry counts the morphs made
  (`transitions_morphed`) and the fades to an empty frame left
  (`fade_clears_left`).
- Active hold: while a sentence is spoken about a formula, the term being
  said turns amber and an underline grows beneath the formula up to it; both
  go back as the sentence ends. Formulas never move - only their colour
  changes. The script names each term's word with
  `self.read_formula(formula, "Күш", "массаның", ...)` (rule M3, which also
  asks for formulas in parts); a formula a block puts on screen without it
  is followed anyway. Matching tolerates Kazakh and Russian endings.
- Word timings: under the flag each line is synthesised through the Azure
  Speech SDK - already installed with manim-voiceover[azure] - which reports
  when each word is said, and the manifest carries them. The same voice,
  SSML and mp3 format as before; if the SDK fails, that line goes through
  REST exactly as it always did and its formula's terms take turns evenly.

Measured on a 32-second test scene at 720p30: the share of 0.3 s windows in
which the frame stands still went from 86% to 0%; rendering took 28 s
instead of 17 s, because every frame of every pause is now drawn.

### Monitoring stops crying wolf during deploys

**Fixed**

- Every deploy was reported as an outage: replacing containers looked like
  services down. deploy.sh now leaves a marker while it builds and restarts,
  and monitor.sh does not check while it is there (30 minutes at most, so a
  deploy that died does not silence it for good).
- While a container is being replaced, compose lists two for the service, and
  the alert came out as "frontend: running" and a bare "created". The best of
  the service's containers now speaks for it.
- An alert Telegram did not take - the server's own internet down - was lost,
  and only "back to normal" arrived, saying nothing. Undelivered alerts are
  sent again on the next run, and "back to normal" lists what was wrong and
  for how long.
- A failed http -> https check in deploy.sh now names the Cloudflare setting
  (Always Use HTTPS) instead of pointing at the tunnel.

### The app fits a phone

**Fixed**

- Single-column layouts were `1fr`, which is never narrower than its widest
  unbreakable child: on a phone one row of buttons made the Explain page 444
  pixels wide, everything was cut off on the right and the page scrolled
  sideways. Every single-column grid is now `minmax(0, 1fr)`.
- The Explain history stuck to the top of the screen at every width, so on a
  phone the question form scrolled underneath it and the choices' hints showed
  through. It sticks only beside the answer on a wide screen, and on one
  column it comes after the question.
- The choices under the question (voice, length, format, quality, language)
  take a whole row each on a phone, share its width, and wrap their hints
  instead of running over the next control. A row of options too wide for the
  screen wraps instead of scrolling, so "Басқа" after four lesson lengths is
  no longer hidden past the edge.
- On a 320-pixel phone the quality row was wider than the card and the
  browser zoomed the page out to fit it, sliding the tab bar half off the
  screen.
- The phone's tab bar held eight tabs and an avatar: labels wrapped onto two
  lines and the last tab was cut off. It now holds four, with a short label
  where the full one does not fit ("Жоспар"), and the avatar becomes "Тағы",
  a menu with the rest.

### Portrait videos, boxes that fit their text, and invites that expire

**Added**

- Portrait (9:16) videos for phones: a "Пішім" choice beside the length. The
  scene is laid out for the narrow frame - the prompt swaps its two frame
  rules - and rendered at the quality's own pixels turned on their side
  (1080x1920 at 1080p), with landscape's pixels per unit so font sizes look
  the same. Portrait is its own variant in the wording cache and its own shelf
  in the topic library; the player shows such a video upright.

**Fixed**

- Text stuck out of the boxes drawn around it: the model drew a fixed-width
  Rectangle and put the text in afterwards. A new prompt rule, L9, has it
  frame the text with SurroundingRectangle, or fit the text to a shape that
  must keep its size. The prompt hash pinned in scripts/check.sh moves with it.
- An invite code stayed in the browser for good, so anyone who later signed up
  on that computer was told a colleague had invited them and got the +2
  videos. It now lasts 30 days and goes as soon as any account signs in or up
  there, and the server ignores an invite made from a browser the inviter
  uses.
- The trial watermark is sized to a video's shorter side, so it is not nearly
  twice as large on a portrait video.

### Plan limits sized to how teachers work, and two variants per paper

**Changed**

- Ұстаз gives 20 БЖБ/ТЖБ a month instead of 40, and the unused ones carry
  into the next month (up to 20), the way videos already did: papers come in
  a rush at the end of a term. The summer pause keeps them too.
- Quizzes stay unlimited on the page, with a fair-use ceiling of 100 a month
  on Ұстаз - named under the meter and on the plan card, and answered with
  "opens again next month" rather than "used up".
- A database seeded before these settings gets them on the next start;
  numbers an admin set are left alone, so the 40 → 20 is set in the panel.

**Added**

- One generation can write the paper twice, 1-нұсқа and 2-нұсқа, for students
  sitting side by side: the same skills for the same marks, different
  numbers. It counts as one paper. Each variant is edited and swapped on its
  own, and the DOCX and the printout put each on its own sheet.
- Metrics count who ran out of what: refusals and teachers per resource, on
  the trial and on Ұстаз, and how many Ұстаз teachers ran out before day 15
  of their month - the sign that a limit is too small.
- The admin panel edits the БЖБ carry-over cap and the quiz fair-use ceiling.

### Silent videos stop being served to people who asked for a voice

**Fixed**

- A video that came out silent with narration on (no Azure key, quota spent)
  was filed under the question's exact wording and served to the next person
  asking the same words - even after it was deleted from the library. It is
  no longer kept there, the topic library no longer hands a known-silent video
  to a voiced request, and rejecting or deleting a library video also clears
  it from the wording cache.
- A narration test waited for an acknowledgement when an earlier test's agent
  had declared "ack" at its handshake.

**Added**

- `python -m app.cache_cli forget "<question>"` takes every stored answer to
  that question out of the cache, matched the way the cache matches.

### Confirming a payment by its code

- The Telegram message about a payment links to that payment
  (`/admin?tab=payments&code=AK-...`), and the payments tab has a search by
  the code from the Kaspi comment, however it was copied.
- "Confirm" asks once more with the code and the sum before it switches the
  plan on: confirming the wrong row gives somebody a plan they did not pay for.

### Confirm the email before the app, and a way back in without mail

**Changed**

- With REQUIRE_VERIFIED_EMAIL=1 an unconfirmed account sees nothing of the
  app but a "confirm your email" page: "I have confirmed", "send again" (with
  a cooldown) and "sign out". It rechecks when the tab comes back into view,
  so opening the link on a phone unlocks the laptop. `/api/auth/me` says so
  with `verify_needed`. Generation was already refused server-side.

**Added**

- `python -m app.staff reset-link <email>` prints a one-time link to set a
  new password, for an admin who forgot theirs or a teacher whose mail never
  came. Audited. The account summary in the command now says whether the
  address is confirmed.

### Ready for the pilot: check notes, problem reports, role fixes

**Added**

- "AI wrote this - check it before the lesson" above every paper, lesson plan
  and quiz the model wrote; hidden when printing.
- "Report a problem" on those and on every explanation: stored, sent to the
  team's Telegram, and listed in a new admin tab «Обращения» where staff mark
  them done (audited). Twenty a day per account.
- Staff can switch an account between teacher and student, with a reason in
  the audit log, for whoever picked the wrong role at sign-up.

**Fixed**

- A refusal on the explain page offered "retry", which could only be refused
  again: not-a-teacher now offers nothing, a plan refusal links to the plan.
- English (and other) explanations could open with a sentence about "visual
  stages for an animation": the prompt now says the text is read beside the
  video and must not mention it.
- A school-year plan bought from 15 May ran only to 1 June; it now runs to
  June of the next year.

### Payments to Telegram, privacy policy and consent

**Added**

- When a teacher presses "I have paid", the team's Telegram gets the amount,
  plan, code, account and a link straight to the payments tab
  (`/admin?tab=payments`). Same bot as the server monitor
  (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID), optionally its own chat
  (PAYMENT_TELEGRAM_CHAT_ID). `python -m app.services.telegram` sends a test.
- A privacy policy at `/privacy`, in Kazakh and Russian, linked from the
  footer: who the operator is, what is kept and why, where (Kazakhstan),
  who it is passed to (the AI models, Azure, Cloudflare, mail, SMS, Google,
  Telegram - cross-border where it is), how long, and how to delete it.
- Sign-up requires ticking consent; the version agreed to and the time are
  stored. Anyone who has not agreed to the current version - every existing
  account, a Google account made from the sign-in page, everyone after the
  policy changes - is asked once inside the app (agree or sign out).
- The admin page opens the tab named in `?tab=`.

**Changed**

- Deleting an account also takes its name off the topic videos it made; the
  videos stay in the shared library.
- The footer's dead "terms" link is gone until there is an offer to link to.

### Plan switching, a real phone field, any lesson length, English explanations

**Fixed**

- Choosing a plan on the plan page did nothing: without Kaspi details the
  month and school-year cards had no button, yet looked selectable, and the
  year one was highlighted as if chosen. They are now a real choice - radio
  cards, the current plan marked - with one action under them: pay, extend,
  or switch, or, before Kaspi is set up, the chosen plan named next to the
  contacts.
- Switching between month and school year started the new plan from today:
  a school-year teacher who paid for a month was cut to one month, and every
  switch handed out a fresh month of videos. Paid days now stay (a month is
  added after the year; a year runs to 1 June or longer), and so does the
  month in progress.
- The phone field took anything. It now holds +7 and ten digits, grouped as
  +7 707 123 45 67; a leading 8, letters and extra digits are dropped, a
  pasted number in any common form lands right, and the button waits for a
  whole Kazakhstan mobile.
- A test of the pending-request sweep failed on a machine up less than 30
  minutes: it aged a request to 0 on a clock that counts from boot.

**Changed**

- A lesson plan can be any length from 10 to 480 minutes, not only 40 or 45:
  presets for 40, 45, 80 and 90, and "other" for any number. Stages may now
  be as long as the lesson.

**Added**

- Explanations in English, and the answer-language choice on the explain
  page actually reaches the agent (it never did). The choice is part of the
  cache key, the topic library keeps a shelf per language, and a video is
  filed under the language the agent says it answered in.

### Generation tasks, system health, metrics; no more 524 on lesson plans

**Added**

- Every generation is a task in `generation_jobs`: queued, running, done or
  failed, with the render time (the agent's own measure for videos), the
  error type, and for videos the length, whether it has sound and the Azure
  characters spent. A task left open by a backend restart is closed at
  start-up and its plan unit given back.
- The admin «Задачи» tab (admin and support): the queue, failures, a silent
  filter, and a restart for a failed video or lesson plan - once, on the
  teacher's own plan, written to the audit log.
- «Система» (admin and support): the agent's connection and its heartbeat
  (busy or idle, how much is waiting), the work in flight, the oldest
  request, free disk, the database, and warnings when any of them is wrong.
- «Метрики» (admin only): the funnel from sign-up to payment, active
  teachers, revenue by month, renders per day, failures by type, and Azure
  TTS characters this month against the free 500k, with a projection.
- The agent reports `error_type`, `elapsed_sec` and `tts_chars` with every
  answer and sends a heartbeat every 30 seconds (feature `heartbeat`).

**Changed**

- Lesson plans and quiz drafts are made in the background: the page sends
  `Prefer: respond-async`, gets a job id at once and polls `/api/jobs/{id}`.
  Cloudflare's 100-second limit no longer cuts off a slow plan, and a plan
  is saved even if the tab was closed. Without the header the endpoints
  answer as before.
- A task keeps the question only while it may be restarted: dropped on
  success, and two weeks after a failure. Deleting an account strips its
  tasks of the question and the owner.
- The admin tab strip and filters scroll sideways on a phone instead of
  widening the page.

**Fixed**

- The lesson plan page showed a plan refusal (no plan, plan used up) as the
  server's English sentence: its client dropped the error code.

### Referrals

**Added**

- An invite code per teacher, with a link, "copy" and "share on WhatsApp" on
  the plan page. Signing up through the link (or through Google from it)
  records who invited the account, once.
- The invited teacher's trial gets +2 videos. The inviter gets +1 month of
  Ұстаз when the invited teacher's first subscription payment is confirmed
  - extending whatever plan is running, never switching it - at most six
  months in any 365 days; a capped reward is still recorded.
- Sign-up and sign-in keep keyed hashes of the IP and of a random browser id
  (never the values). The admin «Рефералы» tab shows who invited whom,
  whether it paid, invitees on the inviter's own device or network, and
  devices or networks shared by three or more accounts.

### Topics: one video per topic, served to everyone who asks

**Added**

- A fixed list of 354 school topics (`agent/anyq/topics.json`, mirrored in
  `backend/app/data/topics.json`; a test keeps them equal). Questions are
  filed by picking an id from it - never by embedding similarity, which puts
  a theorem and its converse side by side.
- Before rendering, the backend asks the agent (new `classify` request, off
  the render queue) whether the question is general or specific and which
  topic it is. Unclear means specific; an invented id is dropped; no answer
  within `CLASSIFY_TIMEOUT_SEC` means render.
- `video_cache`: every successful video for a general question, filed under
  its topic and language, up to three versions; the best by 👍/👎 is served
  instead of rendering - free, students included. A new version replaces the
  worst unchecked one only if it is rated down.
- Under a topic answer: which topic it was matched to, 👍/👎, and «Менің
  сұрағым бойынша жаңасын жасау» - a new render for that exact question,
  charged to the plan. The existing "ask again" on a semantic hit now really
  asks again (it used to find the same library answer).
- «Бейнетека»: the showcase of videos the team has checked. Admin «Библиотека»
  tab (support too): review queue, publish, reject, delete, fix title and
  topic, silent-video filter. Every change is audited.
- The agent reports each video's duration and whether it has sound, read
  from the file with ffprobe.

**Changed**

- The embedding-based "similar question" layer is off by default
  (`CACHE_SEMANTIC_ENABLED=0`); the exact-wording cache is unchanged.

### Paying through Kaspi, confirmed by a person

**Added**

- Orders (`payments`): a teacher picks a plan and gets the amount, the Kaspi
  number and a code for the transfer comment (`AK-` + five unambiguous
  characters), then presses "I have paid". Nothing is applied on that word:
  an admin checks Kaspi and confirms in the panel, which applies the plan
  (a month, the school year, or +10 videos on a running Ұстаз). Rejections
  carry a reason the teacher sees; refunds are recorded and can take the
  plan back. Every decision is in the audit log; money is admin only.
- The order keeps the price it was made at; unpaid orders close after three
  days; at most three open orders per account.
- Staff are emailed when a teacher reports a payment
  (`PAYMENT_NOTIFY_EMAILS`); revenue by month on the payments tab.
- Payment is offered only once `KASPI_PAY_PHONE` or `KASPI_PAY_LINK` is
  set; until then the plan page shows the team's contact, as before.

### Plans: Сынақ and Ұстаз, counted

**Added**

- Plans in the database (`plans`), seeded with Сынақ, Ұстаз by the month
  (4 990 ₸), Ұстаз for the school year (29 900 ₸, to 1 June) and +10 videos
  (990 ₸). Limits, prices, the carry-over cap and the quality ceiling are
  edited in the admin panel without a deploy.
- Сынақ: starts by itself when a teacher confirms a phone; once per number,
  ever - an HMAC of the number (`PHONE_HASH_SECRET`) is kept in
  `trial_claims` and outlives the account. 2 videos with the «Akron · сынақ»
  mark at up to 720p, 2 БЖБ/ТЖБ, 3 AI quizzes, 2 lesson plans; no expiry.
- Ұстаз: counted in monthly periods from the day it started; unused videos
  carry into the next period (capped at 20); bought videos are spent after
  the month's. 1080p, no mark, no DOCX signature.
- Every generation takes one unit before it starts, with an atomic
  conditional increment, and gives it back if nothing came of it (a failed
  render, a text-only answer, a lost agent, a timed-out request). Library
  answers cost nothing. Refusals carry `plan_required` / `plan_exhausted`
  and the resource, translated in the interface.
- The watermark is burned in by the agent with ffmpeg after rendering; the
  clean render is what the shared library keeps.
- DOCX of an assessment (python-docx, built in the request): the paper in its
  own language, with «Akron арқылы жасалды» in the footer unless on Ұстаз.
- Summer pause for the monthly plan (15 May to August): the paid days left
  resume on 1 September, automatically or earlier by hand.
- Email reminder three days before a subscription ends.
- «Тариф» page: what the account is on, meters for what is left, the trial
  offer with the phone form, the pause, the school-year suggestion after 25
  days, prices with a contact line until payment exists. The Explain page
  shows the videos left by the button.
- Admin: grant or extend Ұстаз, end it, add videos (admin); reset a trial,
  block and unblock (support too); edit plans. A reason is required and
  goes into the audit log. Blocked accounts are signed out on their next
  request and cannot sign in.
- AI quiz drafts say `purpose`: "new" is one of the plan's quizzes, "edit"
  (up to 5 questions into an existing quiz) is not counted.

### Real accounts: a confirmed email, password reset, Google, a phone

**Added**

- Email confirmation. Signup mails a link (Kazakh and Russian); the link
  opens `/verify-email`, which POSTs the token, so a mail scanner opening the
  link spends nothing. Tokens are stored as sha256, single use, 48 hours.
  Changing the address unconfirms it and mails the new one; a link for the
  old address cannot confirm the new one. Until confirmed, the app shows a
  banner with "send it again".
- `REQUIRE_VERIFIED_EMAIL=1` (off by default): generating anything - a
  video, a paper, a lesson plan, a quiz draft - needs a confirmed address.
  The refusal carries `code: email_unverified`, said in the reader's
  language. `deploy.sh` refuses to turn it on without SMTP.
- Password reset by email: `/forgot-password` answers the same whether or
  not the address has an account; the link (one hour, single use) sets a new
  password, ends every other session and signs in. "Forgot password?" on the
  sign-in page used to be a dead `#reset` link.
- Sign in with Google: OpenID Connect code flow with PKCE, state and nonce;
  the id_token is read from Google's token endpoint and its issuer, audience,
  expiry and nonce are checked. Matching an existing account by email clears
  its password and sessions when that account had never confirmed the
  address (someone may have registered it first). A new account needs a
  role, so sign-in sends an unknown person to sign-up.
- Phone confirmation by SMS code (smsc.kz or mobizon.kz; `log` prints the
  code). Kazakhstan mobile numbers only; one number per account; six digits,
  ten minutes, five tries, salted hash stored. Sending is rationed in the
  database: one a minute and five a day per account, five a day per number,
  ten an hour per address, and `SMS_DAILY_MAX` for the whole site.
- Mail over SMTP with the standard library, so any provider works; `log`
  prints messages instead. No new dependencies.
- Admin: users are searchable by phone, and show whether email and phone are
  confirmed and whether Google is linked.

**Changed**

- Error responses may carry a `code` next to `detail`, for the interface to
  translate.

### Nothing on screen that is not true

**Removed**

- The wallet: a balance of 18 400 ₸ every new account started with, a top-up
  button, invented transactions, spending charts and a demo-state switcher.
  None of it ever reached a server.
- Per-action prices and the "charges" after each explanation and paper - a
  number taken off that same balance in the browser.
- «Проверка работ»: the page was a static stub with made-up students and
  marks. It returns when marking exists.

**Changed**

- «Баланс» is now «Тариф»: it says the pilot is free and shows the one real
  limit, the video quota from `/api/quota`.
- Only teachers start a new generation. A student still gets any answer the
  library already holds; otherwise the server refuses with
  `code: teacher_only`, which the interface says in the reader's language.
  The voice, length and quality controls are hidden from students, since
  they only shape a video the student cannot make.
- Role, plan and settings texts in all three languages no longer promise
  marking, a balance or unlimited explanations.

### Staff roles and an admin panel

**Added**

- `staff_role` on the account: `admin` or `support`, separate from `role`
  (student/teacher), which people pick themselves. It is written only by a
  command on the server - `docker compose exec backend python -m app.staff
  grant|revoke|list` - which shows the account and asks before changing it.
  Signup, the profile and the panel itself cannot set it.
- `/api/admin/*`: users with search and per-person usage, statistics by day,
  the audit log and the cache statistics. Every route sits on one router that
  requires a staff role; everyone else gets 404, support gets 403 on the
  admin-only routes. The role is read from the database on every request, so
  revoking it works immediately. A test calls every route under `/api/admin`
  as a stranger, a student, a teacher, support and admin, so a route added
  later is checked without anyone remembering to.
- An audit log (`admin_audit`): who did what to whom, when and why. Grants and
  revocations from the server command are recorded.
- A usage log (`usage_log`): one small document per finished explanation
  (with or without video, from the library, or failed), assessment, lesson
  plan and AI quiz draft - never the question text. The quota counters could
  not serve as statistics: they are refunded on failure and expire in two
  days.
- `/admin` in the interface, in Russian, loaded as its own chunk. Staff see an
  «Админка» item in the account menu. `docs/DEPLOY.md` explains granting roles
  and putting `/admin` behind Cloudflare Access.

**Removed**

- `ADMIN_USERS`. The cache statistics need the admin role instead. With
  nobody granted, the endpoint is closed, as before.

**Changed**

- `/api/admin/cache/stats` answers 404 rather than 401 without a session.

### The agent asks for the key of the provider it uses

**Fixed**

With `DEFAULT_LLM_PROVIDER=openrouter` and only `OPENROUTER_API_KEY` - the
default, and what production runs - every text question was answered "add
GEMINI_API_KEY", and every screenshot failed. The gate now checks
`{PROVIDER}_API_KEY`, and screenshots go through OpenRouter when there is no
Google key (Google is still used when there is).

### The product is called Akron

**Changed**

Everything a person sees says Akron instead of Anyq: the wordmark (AKRON,
without the AI), the page title and description, every interface string in
Kazakh, Russian and English, the quiz join page, the footer, the teacher deck
(PPTX), the fallback name of a downloaded file (`akron-export`), and the
Telegram alerts from `deploy/monitor.sh`.

The code keeps `anyq` on purpose - the Python package, container and volume
names, the database, the session cookie, the browser storage keys and the
`ANYQ_*` variables. Renaming those would log everyone out, reset saved
settings and leave the data in volumes nothing mounts.

### Production: a home server behind a Cloudflare tunnel

**Changed**

Production moved from a VPS with Let's Encrypt to a home server with no
public address: Debian 12 on an Ivy Bridge i3, 8 GB, behind
`akronustaz.com` and a Cloudflare tunnel. `docs/DEPLOY.md` is rewritten for
it, including what to set in the Cloudflare dashboard.

- **The tunnel.** A `cloudflared` service (pinned, no self-update, token
  from `TUNNEL_TOKEN`, healthy only when connected to Cloudflare's edge)
  carries the traffic to nginx on port 80. Nothing is published: the one
  port is `127.0.0.1:8080`, for checking the site from the box itself.
- **TLS left the stack.** certbot, `deploy/init-tls.sh`, the 443 listener,
  the certificate mounts, the ACME path, the http-to-https and www
  redirects, and the development TLS mode with `scripts/make_dev_cert.sh`
  are gone - a redirect to https in nginx would loop forever behind the
  tunnel. Cloudflare terminates TLS; the cookie's Secure flag comes from
  `COOKIE_SECURE=1`. The entrypoint is now `15-anyq-listen.sh`.
- **The client's address.** nginx takes it from `CF-Connecting-IP`, trusting
  only private-network peers and only with `TRUST_CF_CONNECTING_IP=1` -
  without it every visitor arrived as cloudflared and they all shared one
  set of sign-in, sign-up and quiz-join limits. `X-Forwarded-For` is
  replaced with that address instead of appended to, `X-Forwarded-Proto` is
  passed on from Cloudflare, and uvicorn in the backend and quiz service
  runs with `--proxy-headers`.
- **mongo pinned to 7.0.43** in all three places: the box has AVX but no
  AVX2, and 8 does not start on it. In production its cache is capped at
  1 GB, which otherwise sizes itself from the whole machine.
- **Rendering yields to the site:** `cpu_shares: 512` and CPU caps on the
  agent and exporter; renders were already one at a time. Videos start at
  480p (`EFFORT_DEFAULT=low`) until render times on the box are measured.
- Log rotation on every production service, cloudflared included.
- `deploy.sh` checks the box and then the way in through Cloudflare: the
  agent channel 403 on both, http to https, a websocket handshake through
  Cloudflare, and that the backend sees the address from `CF-Connecting-IP`.
  `prepare-server.sh` no longer touches the firewall.

**Known, next:** Cloudflare gives up on a response after 100 seconds (524).
A lesson plan can take up to 150 and a quiz draft up to 120. Both should
become background jobs the page polls; written down in `docs/DEPLOY.md`.

### Production: one VPS with Docker

**Added**

`docker-compose.prod.yml` and `deploy/`: the same stack on any Linux server
with Docker, under a real domain. `docs/DEPLOY.md` is the walkthrough.

- **HTTPS from Let's Encrypt.** `deploy/init-tls.sh` gets the first
  certificate: the site comes up once on plain HTTP, certbot proves the
  domain through it, and the stack switches to HTTPS - the frontend still
  refuses to start without a certificate, so this is the only way round that.
  A certbot service renews it; nginx notices the changed files within the
  hour and reloads by itself, gracefully. `www.` answers with a 301 to the
  bare domain over HTTPS too, so there is one origin and one session cookie.
- **Nightly backups** at 02:00 Astana: `mongodump` of the database, kept 14
  days, and a mirror of the rendered videos beside it. On the host, outside
  every docker volume. The service logs in as the app user - the root
  password stays out of it - and goes unhealthy when no dump has finished in
  26 hours. `deploy/restore.sh` takes a fresh backup before replacing
  anything and asks for the domain to confirm.
- **Monitoring.** `deploy/monitor.sh`, from cron every five minutes: services
  and healthchecks, the site from the outside in, days left on the
  certificate, disk. Alerts to Telegram, once per change rather than every
  five minutes.
- **`deploy/deploy.sh`** refuses an `.env` that would come up quietly wrong -
  a secret still from the example, TLS off, CORS pointing at localhost - then
  builds, starts, waits for every healthcheck, and checks from outside:
  `/ws/agent` 403, http to https 301, HSTS, the agent connected. A deploy
  that changed nothing restarts nothing: on Docker 29's image store BuildKit's
  provenance record gave every cached rebuild a new image ID, and every
  service was recreated - quiz sockets and all - so it is switched off.
- `deploy/init-env.sh` writes that `.env` with fresh random secrets;
  `deploy/prepare-server.sh` adds swap, the backups directory, the cron line
  and, when asked, the firewall.

**Fixed**

Found by deploying a clean export of the repository - what a server clones -
onto fresh volumes:

- **A fresh database had no app user.** The mongo image creates the root user
  on an empty volume and nothing else; every service logs in as `anyq_app`,
  so a new server's backend was refused by its own database and the site
  never started. `scripts/mongo-init/10-app-user.js` creates it on that first
  boot, and `deploy.sh` makes sure of it on every deploy.
- **A fresh clone could not build the frontend.** `*.png` in `.gitignore`
  (meant for render output) had kept `frontend/src/assets/logo.png` out of git
  all along. Committed, with an exception for the interface's own images, and
  a test that fails when a file under a build directory is ignored.
- Shell scripts are pinned to LF in `.gitattributes`: a CR is part of the
  command to bash on Linux.

### Playback speed

**Added**

A speed menu in the player - 0.5×, 0.75×, normal, 1.25×, 1.5×, 2× - for the
rendered video and for the built-in scenes alike. The choice is remembered on
the device, so the next answer starts at the same speed, and the button is
tinted while it is anything but normal. The video keeps its voice at pitch.
On a phone the seek bar now takes a row of its own above the buttons; next to
the new menu, between them, it had no room left.

### Quizzes: a service of their own, from the editor to the projector

**Added**

A quiz mode, built from the editor prototype and taken further: a teacher's
list of quizzes, the editor, a projector screen, a phone screen for students,
and a results page. Teachers only, like the other documents; students need no
account - they join with a six-character code, or by pointing a camera at the
projector's QR code.

**A service, not a module.** `quiz/` is its own FastAPI service and container
(`anyq-quiz`) with its own collections and live channels, sharing no code
with the backend. It crosses into the rest of the system in three places,
each on purpose: it asks the backend's `/api/auth/me` who a teacher is;
questions are written by the agent through the backend (`/api/quiz-drafts`)
and only saved here; and a deleted account reaches it through an outbox
(`account_events`) the backend writes in the same request. The frontend's
quiz screens are likewise a module (`frontend/src/quiz/`) loaded as its own
chunk. `docs/QUIZ_SERVICE.md` has the boundaries and what a second replica
would need.

**What makes a question worth asking is its wrong answers.** Every wrong
option carries a note - for the teacher only - naming the misunderstanding
behind it. When a quarter of the class or more picks the same wrong option,
the results lead with it: "9 answered 20 m/s² - multiplied force by mass",
and one click opens Explain with that question already written, aimed at
exactly what went wrong.

**What a phone is never told.** The right answer before it has answered; the
next question before this one; the notes. Answers are marked on the server,
once (a double tap is one answer), against the server's clock - the phone
works out its own offset from `serverNow`, so a wrong clock cannot buy time.

**The stage** has a look of its own: four answer colours from the steppe and
four marks from Kazakh ornament (шаңырақ, crescent, nested rhombus, ram's
horn) so no answer depends on colour alone; the code on a split-flap board;
names dropping into the lobby; a synchronized countdown on every phone and
the projector; a lane per student while it runs - progress only, never who
got what wrong, because the projector is a wall the class reads; a podium at
the end. The QR encoder is in-house (no dependency) and was checked against
OpenCV's decoder across versions 1-15.

**Fixed on the way**

- A phone that asked for the next state a moment before the countdown ended
  on the server's clock was told "countdown" again and never asked twice -
  the screen stayed on "1". Seen on a Docker VM whose clock ran 8% slow; any
  network can imitate it. Every answer now schedules the next check.
- The students' socket refused unlisted origins, which would have shut out a
  class joining a stack run on the school network. A token, unlike a cookie,
  has to be sent, so the check protected nothing there; the teacher's socket,
  which does ride on a cookie, keeps it.

160 new tests: the quiz service and its nginx routing 110, the agent 29, the
backend 17, and a live end-to-end run through nginx 4. 851 in the unit suite.

### Sign-in limits that hold, and an account that is really deleted

**Security**

- **The rate limits could be skipped with one header.** The per-IP key was the
  first entry of `X-Forwarded-For`, and nginx appends the real address to the
  END of whatever the client sent. An invented address per request was a fresh
  budget per request, for both sign-in and sign-up. Now `X-Real-IP`, which
  nginx overwrites, and otherwise the last entry. Verified through nginx: fifty
  failures with forged headers, then 429.
- **A successful sign-in wiped the address's count**, so anyone with an account
  of their own could clear it between guesses at other people's. The address
  is now spent by failures only (`LOGIN_IP_MAX_FAILURES`, 50 per 15 minutes)
  and a success does not touch it - which also means a classroom behind one
  address is never locked out by students signing in correctly.
- **Every capitalisation of an address had its own five attempts.** The lookup
  is case-insensitive; the budget key now is too.
- **Deleting an account left its papers, lesson plans and saved answers** in
  the database for good. Those collections arrived after the route and were
  never added to it.
- **Saving a lesson plan stored whatever JSON arrived** - megabytes, fields the
  form does not have (the teacher's name and date included), a stage that is a
  number and cannot be drawn. The save now keeps the document's fields only,
  as strings, with bounded sizes; the teacher's wording is untouched and a
  half-rewritten stage is not dropped.

**Fixed**

- `lesson_plans` had no index; listing them scanned the collection.
- `PENDING_REQUESTS_TTL_SEC` is forwarded by compose.
- Agent: `format_output` returned `None` for a path the state declares a
  string; an unreachable fallback and the unused `_latex_is_available` removed.
- Docs: TLS and Mongo auth marked done in the audit; the storage section of the
  cost report named the wrong file - the bulk was `Demo.wav`, already cleaned.

### Қысқа мерзімді жоспар: the lesson plan a teacher has to submit

**Added**

Not a summary of a lesson - the document with the fixed shape schools in
Kazakhstan require for every lesson taught. Teachers only, like assessments.

A teacher gives the topic, subject, grade, language and lesson length; the plan
comes back with every section of the form - бөлім, оқу мақсаттары with their
codes, сабақ мақсаты, бағалау критерийлері, құндылықтар, пәнаралық байланыс,
алдыңғы білім, the `Сабақтың барысы` table split into басы / ортасы / соңы with
what the teacher does, what the students do, how it is assessed and on what
resources, then саралау, бағалау and денсаулық және қауіпсіздік. Every field is
editable and saved, because it is submitted under the teacher's name.

**What the model is not allowed to write.** The teacher's name, the date, who
was present, and the reflection written after the lesson. A model cannot know
them, and a document arriving with them filled in invites somebody to submit a
plausible-looking lie about their own classroom. The page says so once, near
the top, rather than leaving it to be noticed.

**Three checks, because a plan is judged on its shape before anyone reads it**

- **Objective codes.** The curriculum writes them `grade.section.subsection.item`,
  so 8.2.1.4 is a grade-8 objective and a code whose first number is not the
  grade is one the model invented. The objective's TEXT is kept and the bad code
  dropped: a teacher can look a code up, and cannot un-submit a document that
  carried a made-up one. Seen working live - a plan came back with the code left
  empty and the objective intact, which is the model declining rather than
  guessing.
- **Time.** The stages have to add up to the lesson, within ten per cent. A plan
  refused rather than rescaled: stretching somebody's stages to fit makes a
  different lesson than the one written, and they would have no way to know.
- **Both columns.** A stage with an empty `Оқушының әрекеті` is dropped. That
  column left blank is the most common way one of these documents is useless -
  it becomes a lecture plan with a column for decoration.

**Fixed on the way - nginx cut the request off at sixty seconds**

`location /api` had no `proxy_read_timeout`, so it took nginx's default of 60s.
An assessment takes two to seven seconds and never came near it; a plan is a
much bigger document and measures around forty, with the backend allowing 150.
The teacher got an nginx 504 page while the backend was still working and about
to answer. Now 180s, above the slowest endpoint behind it.

The three request/reply mechanisms over the agent socket became two: assessments
and plans share one, since a third near-copy is where duplication starts costing
something. `request_assessment` keeps its contract exactly.

### A 200 that says the model never ran was being taken for an answer

**Fixed - and it was not an assessment bug, it was every LLM call**

Found by the run log the commit below added. Three assessments in a row came
back empty, which read like the feature being broken. It was not: over 23
papers through the full stack, three failed and all three were inside one
eleven-minute window, with zero failures in the thirty calls after it.

What that window exposed is the real defect. OpenRouter returns a perfectly
ordinary 200 with `finish_reason: "error"` when the provider behind the model
fails mid-generation: the content is empty and **nothing raises**. The retry
wrapper in `_llm_chat` only ever saw exceptions, so it never saw this, and a
momentary upstream failure became a hard failure of the request - while the
product already had the machinery to back off and ask again.

Every caller reads an empty reply as something the model meant:

| caller | what the empty reply became |
|---|---|
| `classify_intent` | no JSON -> `is_science: False` -> a physics question answered "this is not a science question" |
| `educator_answer` | an empty explanation, carried into the video |
| `generate_manim_script` | `RuntimeError`, and the whole request fails |
| `generate_assessment` | "model returned no questions", a 502 to the teacher |

`finish_reason: "error"` now raises `UpstreamLLMError`, which the existing
transient path retries. Deliberately only `error`: not `length`, where the
model ran and asking again would truncate again at the same place for the same
money, and not an empty reply that finished with `stop`, where the model ran
and chose to say nothing.

An unusable assessment reply also now logs what actually came back - the
finish reason, the provider, the length. "model returned no questions" says
the paper is empty and nothing about why, and a refusal, a truncation and an
upstream error all arrive looking identical from the outside.

### The database had no password, and the site could not serve HTTPS

Both were on the audit's "required before a public launch" line.

**MongoDB now requires authentication**

It ran with none. Being on the internal docker network rather than the
internet is what made that feel safe - but that network holds four other
containers, and one of them is the agent, which executes code a language model
wrote. "Not reachable from outside" was the only thing between that code and
every chat, session and account.

- `mongod --auth`, and two users: a root for administration that no service
  ever logs in as, and an app user with `readWrite` on one database and
  nothing else. Verified from inside: that user reads its own database, is
  refused on `admin`, cannot create users, cannot write to another database,
  and `listDatabases` returns only the one it can see.
- The healthcheck authenticates, because under `--auth` an anonymous ping is
  refused - and an unhealthy mongo stops everything with a
  `depends_on: service_healthy` on it from ever starting.
- **`scripts/mongo_enable_auth.sh`** because compose alone cannot do this. The
  mongo image creates `MONGO_INITDB_ROOT_USERNAME` only when the data
  directory is EMPTY, so a deployment with data in it would restart into
  `mongod --auth` with no users and lock itself out. The script creates both
  users in place, while auth is still off, and fills in whatever is missing
  from `.env`.

**TLS, off by default and verified on**

`HTTPS_TERMINATED=1` serves HTTPS on 3443 and answers plain HTTP with a 301,
so nothing is served in clear text. The certificate is a bind mount of
`fullchain.pem` and `privkey.pem` - the names certbot already writes - so a
real certificate is a change of path and no configuration.

- One server block with its listeners in an include, rather than two copies of
  the whole site config that would drift apart. nginx cannot start with an
  `ssl_certificate` pointing at a file that is not there, which is why this
  cannot simply be a line that is always present.
- **It refuses to start without a certificate** instead of falling back to
  HTTP, which is the failure nobody would notice: the site would come up, work,
  and be unencrypted.
- `scripts/make_dev_cert.sh` writes a self-signed pair so the path can be
  exercised on a machine with no domain.
- The session cookie's `Secure` flag comes from the same switch, so HTTPS
  cannot be turned on while the cookie still travels in clear text.

**Found by testing it rather than by reading it**

Three bugs in the above, all caught on the running stack:

- The cookie came back **without `Secure`** with HTTPS on. `COOKIE_SECURE` was
  written as an override in either direction, and every `.env` in existence
  already carries `COOKIE_SECURE=0` from before - so the single switch was
  defeated by a stale line. Either may now switch it on and neither may switch
  it off.
- The frontend went **unhealthy** under TLS: the healthcheck probed port 3000,
  which now answers a 301. It probes 3443 first and falls back, so it works in
  both modes without following a redirect that points at the public port.
- `make_dev_cert.sh` wrote half a certificate in silence: Git Bash rewrote
  `-subj /CN=localhost` into a Windows path, and the script was discarding
  openssl's stderr.

Verified end to end over TLS: TLSv1.3, signup with a `Secure` cookie, `wss://`
ping and chat creation, every security header intact, `/ws/agent` still 403,
and a missing certificate refusing to start.

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
