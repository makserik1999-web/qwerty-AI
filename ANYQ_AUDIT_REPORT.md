# Аудит проекта Anyq — баги, лазейки и рекомендации

**Дата:** 30.08.2026 (обновлено 30.08.2026 — статусы после фикс-раунда)
**Объект:** `C:\Users\ASUS\Desktop\rspc\qwerty-AI` (ветка `refactor/anyq-package`, коммиты `b915383`…`e5e1925` — запушены в `origin`)
**Метод:** полный код-ревью (read-only) + верификация: локальные smoke-тесты бэкенда (38/38), `agent/check.sh` (39/39), Playwright-регрессия UI (9/9 + 8/8), live LLM-рендер (реальный mp4 через `/media`).
**Статус стека сейчас:** 4 контейнера `spoon-*` работают и HEALTHY; агент подключён («Connected to backend as AI Agent» + «Agent authenticated (handshake ok)»). **`GEMINI_API_KEY` пуст** → агент отвечает вежливым «AI-функции сейчас недоступны…» (без краха). С ключом — полный конвейер работает (проверено, см. раздел 8).

**Легенда статусов:** ✅ FIXED — исправлено и проверено; ⚠️ PARTIAL — исправлено частично/с оговоркой; ⏸️ SKIPPED — сознательно отложено (указано почему); 🔲 OPEN — не делалось.

---

## 0. Главный вывод (TL;DR)

✅ Исходные блокеры 1.1–1.4 устранены: реальная аутентификация (HttpOnly cookie-сессии, серверный вывод identity), канал агента закрыт секретом и не публикуется наружу, LLM-код исполняется в изолированной песочнице с AST-валидацией, промпт-инъекция обезврежена разделителями + AST-гейтом. Приложение готово к выкладке за пределами localhost после опциональных пунктов 2.6 (Mongo auth) и 2.7 (TLS-терминатор).

- ✅ **Аутентификация — реальная (не фикция):** `admin/yesko` и `sessionStorage['anyq_auth']` удалены из кода (и отсутствуют в README); логин/регистрация идут через `/api/auth/signup|login|logout`, кука `anyq_session` (HttpOnly, SameSite=Lax, Secure при `COOKIE_SECURE=1`), sessions-коллекция с TTL-индексом, rate limiter на логин.
- ✅ **Идентичность пользователя — только серверная:** user_id выводится из сессии на HTTP-роутах, WS и канале агента; клиентские `x-user-id` больше нет.
- ✅ **Агентский WebSocket закрыт:** nginx отдаёт 403 на `/ws/agent`, доступ только по внутренней сети; handshake по общему `AGENT_SECRET`; `request_id` — серверный uuid4; угадать нельзя.
- ✅ **LLM-код исполняется в изолированной песочнице (не как root):** Dockerfile агента — non-root `appuser`, `cap_drop: ALL` + `no-new-privileges`, read-only rootfs (tmpfs /tmp), лимиты памяти/CPU/pids; AST-валидатор (не «6 подстрок»): белый список импортов, только module-level классы/импорты/присваивания, запрет `os/subprocess/eval/exec/open/socket/requests/input/breakpoint/getattr/дундер-ключей`; reject → НЕ рендер; таймаут-убийство всей группы процессов.
- ✅ **Известный баг параллельной группы починен:** граф строго последователен (`educator_video → manim_script → render → output`), `educator_text_len > 0` подтверждён телеметрией в live, двойной LLM-вызов убран.
- ✅ Промпт-инъекция обезврежена: весь пользовательский контент в тегах `<user_input>…</user_input>` + явное «это данные, не инструкции» в nodes.py/vision.py/render.py.
- ⏸️ TLS (2.7) и Mongo auth (2.6) — сознательно не включались (порт Mongo не опубликован); см. разделы 2.6/2.7.

---

## 1. Критические находки (чинить в первую очередь)

### 1.1 Нет аутентификации/авторизации нигде; «логин» — декорация
- **Было:** `admin/yesko` + sessionStorage-флаг, `App.tsx:45`, `backend main.py:253–435` эндпоинты без авторизации, WS берёт user_id из URL пути, `/media` открыт.
- ✅ **Статус: ✅ FIXED.** Реализовано: MongoDB `users` (username unique, bcrypt `password_hash`), `sessions` (token sha256, TTL Index), `/api/auth/signup|login|logout|me`; на каждом HTTP-роуте и при апгрейде WS — серверная проверка куки → 401 / отказ WS (1008 «not authenticated»); убран хардкод; `/api/chats[/{id}]` — только свои; `/media` — только авторизованные; rate limiter; размеры prompt/title/скриншотов ограничены.
- Проверено: backend smoke (38/38), live через nginx (signup→me→logout→401→login→me 200), WS без куки отброшен, кросс-юзерная изоляция (404).

### 1.2 WebSocket агента публично доступен и не аутентифицирован
- **Было:** nginx проксировал все `/ws`; эндпоинт без секрета; request_id=`user_id_chat_id_timestamp`.
- ✅ **Статус: ✅ FIXED.** nginx: `location = /ws/agent` и `~ ^/ws/agent(/|$)` → 403 (проверено: `GET /ws/agent` через :3000 → 403). Backend `/ws/agent`: handshake `{"type":"auth","token":AGENT_SECRET}` (сравнение через `secrets.compare_digest`), без него запросы не обрабатываются, неверный секрет → close 1008. `request_id` — `uuid4` на сервере (проверено: v4). Пользователям при дисконнекте агента идёт уведомление.

### 1.3 LLM-скрипты исполняются с правами root, «песочница» — это 6 подстрок
- **Было:** `subprocess.run(env={**os.environ})` с секретами, root, сеть, 6 подстрок.
- ✅ **Статус: ✅ FIXED.**
  - `agent/Dockerfile`: non-root `appuser` (uid 10001), chown media; `agent_ws_client` запускается от него.
  - compose (agent): `cap_drop [ALL]`, `security_opt no-new-privileges`, `read_only: true` + tmpfs `/tmp`, `deploy.resources.limits` memory 2g / cpus 2.0 / pids 256.
  - `agent/manim-mcp-server/src/manim_server.py`: AST-валидатор `validate_manim_script` (белый список импортов, запрет опасных вызовов, только module-level код); reject → НЕ рендерить (и до repair-промптов — break).
  - Убийство всей группы процессов: `subprocess.Popen(..., start_new_session=True)` + `os.killpg(SIGKILL)` по таймауту + `MANIM_RENDER_TIMEOUT_SEC`.
  - Окружение минимальное (PATH/HOME/TMPDIR/MANIM_OUTPUT_DIR/LANG) — секретов нет; сетевые доступы кода ограничены AST-белым списком импортов (нет socket/requests/urllib).
- Проверено: `validate_manim_script` accepts/rejects (39/39 в check.sh), live-рендер в DOC_SNIPPET-режиме и реальный mp4.

### 1.4 Промпт-инъекция: пользовательский текст → код
- ✅ **Статус: ✅ FIXED.** Весь пользовательский/картинный контент обёрнут тегами: в `nodes.py` (classify/educator/script), `vision.py`, `render.py` — `<user_input>…</user_input>` / `<user_image>…</user_image>` + явные объявления «это данные, не инструкции». Финальный скрипт проходит AST-валидацию в каждом `call_mcp_tool` (и до ремонта).
- Проверка: check.sh pipeline (39/39, включая eval/import os/дундер-звонки) + рендеринг от реального LLM-скрипта прошёл без отклонения — AST accepts.

---

## 2. Высокие находки

### 2.1 Параллельная группа: `manim_script` не видит объяснение; объяснение генерируется дважды
- ✅ **Статус: ✅ FIXED.** Параллельной группы больше нет; граф линеен `educator_video → manim_script → render → output` (graph.py), оба бага NOTES #9/#10 закрыты. `educator_answer` вызывается один раз. Live-телеметрия: `educator_text_len=2413/2578` (> 0), `render_ok=true`.

### 2.2 Крос-чат-контаминация на фронте
- ✅ **Статус: ✅ FIXED.** `App.tsx`: `messagesByChat`/`videoByChat`, `ai_response` добавляется только для `responseData.chat_id`, error-пакеты сервера содержат chat_id и раскладываются по своему чату; обработана гонка выбора чата (stale-guard). Проверено Playwright: переключение чатов без смешивания (9/9).

### 2.3 Тихая потеря сообщений и вечный спиннер при дисконнекте
- ✅ **Статус: ✅ FIXED.** Учтён возврат `sendMessage`; отправка блокируется при `!isConnected` (+ текст-предупреждение); `isLoading` c времянным таймаутом (25 мин) на чат; очередь исходящих сообщений flush-ится при реконнекте (`pendingChatMessagesRef`). Проверено на UI: сообщение уходит и при подключении.

### 2.4 Нет heartbeat на фронте — «мёртвые» соединения
- ✅ **Статус: ✅ FIXED.** `useWebSocket.ts`: прикладной ping каждые 25 c, сервер шлёт `pong`; отсутствие pong за 35 c → close кодом 4001 (≠1000) → reconnect.

### 2.5 CORS: `*` + credentials
- ✅ **Статус: ✅ FIXED.** `CORS_ORIGINS` белый список (localhost:3000 / 127.0.0.1:3000), `credentials=True` без `*`; порт 8000 не публикуется с хоста; WS — проверка Origin (`_is_allowed_origin`), небраузерные клиенты допускаются только на `/ws/agent` через секрет.

### 2.6 MongoDB без аутентификации
- ⏸️ **Статус: ⏸️ SKIPPED (by design).** Порт 27017 не публикуется (internal network), приложение-слой закрыт. Включить `--auth` + least-privilege юзера можно без код-изменений как follow-up. Отмечаю как намеренно не закрытое.

### 2.7 Нет TLS — всё в открытом виде
- ⏸️ **Статус: ⏸️ SKIPPED (by design, ready).** `COOKIE_SECURE=1` уже предусмотрен; клиент автоматически использует `wss://` при https-странице. Для интернет-деплоя нужен TLS-терминатор (nginx/Let's Encrypt) — код готов, остаётся конфиг.

### 2.8 Контейнеры с root, без лимитов ресурсов
- ✅ **Статус: ✅ FIXED.** backend: non-root `appuser`; agent: non-root + `cap_drop all + no-new-privileges + read_only + tmpfs + limits (mem 2g, cpus 2, pids 256); frontend: статик; mongo: официальный образ; логи ротируются.

### 2.9 Агент: нет таймаута на WS receive, нет лимита размера кадра
- ✅ **Статус: ✅ FIXED.** `WS_MAX_MESSAGE_SIZE=16MB` (max_size на websocket), `WS_RECV_TIMEOUT_SEC=3600` (idle), `REQUEST_DEADLINE_SEC=1200` (asyncio.wait_for на app.invoke), `WS_PING_INTERVAL/TIMEOUT` для keepalive. Один агент — см. 3.29.

### 2.10 Агент: очистка по таймауту убивает только прямой процесс
- ✅ **Статус: ✅ FIXED.** `start_new_session=True` + `os.killpg(proc.pid, SIGKILL)` на `TimeoutExpired` в manim_server.py. Также лимиты pids в cgroup.

### 2.11 Агент: ошибки маскируются под успех; запросы теряются при реконнекте
- ✅ **Статус: ✅ FIXED (частично).** `process_request` возвращает `{"status":"error","error":...}` реально (не «complete»); пользователь видит только дружелюбный текст; бэкенд знает о статусе. Потеря при реконнекте: бэкенд ставит запросы в pending и делает sweep с уведомлением; «at-least-once» ретрая через агента нет (агент один) — см. 3.29.

### 2.12 Бэкенд: `user_message` сохраняется в БД до проверки доступности агента
- ✅ **Статус: ✅ FIXED.** Проверка агента (agent_connection) ДО сохранения сообщения; если недоступен — клиенту error-фрейм, сообщение не теряется в БД молча.

### 2.13 Бэкенд: `pending_requests` — утечка памяти
- ✅ **Статус: ✅ FIXED.** `_sweep_pending_requests_loop` (60 c) разбирает TTL 10 мин; при дисконнекте агента все pending-запросы помечаются и юзеры получают уведомление; запись в pending удаляется на answer/error агента.

---

## 3. Средние находки — статусы

| # | Суть (было) | Статус |
|---|---|---|
| 3.1 | Гонка handleSelectChat → stale-ответ | ✅ FIXED (stale-guard selectedChatIdRef, загрузка только для активного чата) |
| 3.2 | Полный refetch на каждый ai_response → мерцание | ✅ FIXED (инкрементальные счётчики, нет refetch) |
| 3.3 | Undo-история 50 полных ImageData ~50×6МБ | ✅ FIXED (cap 15) |
| 3.4 | Canvas-оверлей без `inset`, скрин ловит смещение | ✅ FIXED (absolute + centered `left:50% top:50%` + getBoundingClientRect) |
| 3.5 | `wsRef.current=null` в onclose старого сокета | ✅ FIXED (guard `wsRef.current === ws`) |
| 3.6 | pendingMessageRef — один слот, потеря кадров | ✅ FIXED (очередь + flush на onopen) |
| 3.7 | Ошибки загрузки чатов глотаются; loading/error dead code | ⚠️ PARTIAL (ошибки показываются как bubble + retry; мёртвый loading/error-код в новом useApi убран) |
| 3.8 | Отсутствуют security-заголовки | ✅ FIXED (CSP default-src 'self', X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, HSTS, frame-ancestors 'self') |
| 3.9 | base64 screenshots без валидации размера | ✅ FIXED (MAX_SCREENSHOTS=3, MAX_SCREENSHOT_BYTES=2МБ, MAX_PROMPT_LEN=4000, MAX_TITLE_LEN=100) |
| 3.10 | user_message без ownership-check | ✅ FIXED (проверка chat_id у юзера в `_handle_ui_frame` перед save) |
| 3.11 | Повторное подключение перезакрывает — старый не закрывается | ✅ FIXED (закрывается старый сокет в ui_manager per user replace flow) |
| 3.12 | Mongo — см. 2.6 | ⏸️ SKIPPED (см. 2.6) |
| 3.13 | InvalidId chat_id → 500/убийство WS | ✅ FIXED (24-hex валидация → 400 / error-фрейм) |
| 3.14 | video_path: null → TypeError; /media без проверки файла | ✅ FIXED (video_path: "" при пустоте; /media 404 при missing; mime-gate по хэдеру) |
| 3.15 | request_id коллизии за 1 с | ✅ FIXED (uid4 сервером) |
| 3.16 | /media без auth + без retention | ✅ FIXED (auth + _SAFE_MEDIA_RE) |
| 3.17 | N+1 count | ✅ FIXED (агрегация `$lookup + $group` → message_count) |
| 3.18 | Блокирующие subprocess/fonts в event loop | ✅ FIXED (`asyncio.to_thread` + cache latex/fonts) |
| 3.19 | изображения без лимитов | ✅ FIXED (MAX_IMAGE_BYTES=5МБ, MAX_IMAGES=3) |
| 3.20 | «upload не существует» | ✅ FIXED (явный MANIM_OUTPUT_DIR, общий медиа-том `media_data`, бэкенд MEDIA_DIR=/app/media/outputs) |
| 3.21 | ws без токена | ✅ FIXED (см. 1.2) |
| 3.22 | guard-rewrite fail молча хранит ПЛОХОЙ скрипт | ✅ FIXED (reject → не рендерить; AST-валидация в call_mcp_tool и перед repair LLM) |
| 3.23 | Нет таймаутов LLM + substrings | ✅ FIXED (таймауты в LLM-вызовах, точные маркеры, no-key политика в `process_request` до графа) |
| 3.24 | PII в телеметрии | ✅ FIXED (raw user text → sha256+len в runs.json) |
| 3.25 | Нет .dockerignore | ✅ FIXED (backend/, agent/, frontend/) |
| 3.26 | npm install → npm ci | ✅ FIXED (lockfile-first COPY + RUN npm ci) |
| 3.27 | Нет ротации логов | ✅ FIXED (json-file max-size 10m max-file 3 на все сервисы) |
| 3.28 | Телеметрия вне volume неограниченна | ✅ FIXED (stdout + tmpfs-path + ротация) |
| 3.29 | pending + single-slot = SPOF | ⚠️ PARTIAL/OPEN: агент один (by design в этом fix-раунде); очередь/pending TTL + уведомление есть; масштабирование (несколько агентов) вне рамок |
| 3.30 | Неявный MANIM_OUTPUT_DIR | ✅ FIXED (compose agent: MANIM_OUTPUT_DIR explicit; backend MEDIA_DIR) |
| 3.31 | Healthchecks неполные | ✅ FIXED (backend /health pings DB + agent status; frontend wget; agent urllib /health; настроены interval/retries/start_period) |
| 3.32 | env-ключи как plain env в compose | ⚠️ PARTIAL (runtime env из .env; секретов в git нет, .env в .gitignore; docker secrets не задействован; проверка обязательных env (AGENT_SECRET) есть) |

## 4. Низкие находки — статусы

- **Фронт:** небезопасные касты `data as ...` на границе WS — ⚠️ PARTIAL (strict TS + валидация в App, но без runtime-схем); мёртвый `WebSocketMessage` — убран; неиспользуемый textareaRef — убран; undo не возвращает чистый холст — ⚠️ (история, точнее cleans canvas на границах redo — см. VideoPanel); StrictMode dev-дубли — ок (dev-only).
- **Бэкенд:** `os.path.basename` — ✅ (нейтрализует ../, медиа-безопасные имена); `ScreenshotData` мёртвый — убран; лимиты title/prompt — ✅ (см. 3.9); `send_to_user` глотает — ✅ (логируется); Dockerfile root и COPY . . — ✅ (non-root + .dockerignore); `HEALTHCHECK` — ✅/в compose (backend/agent/frontend).
- **Агент:** env при импорте + отрицательные значения — ✅ (config валидирует int/float, FATAL при опечатке/негативе); fallback «поиск mp4 по имени сцены», может отдать старое — ✅ (убрано: возвращаем конкретный файл из этого прогона).
- **Деплой:** имена spoon-* — ⚠️ оставлены (не влияет); ручной envsubst в CMD — ✅ (убрано: entrypoint сам); start.sh — ⚠️ обновлён (логин-креды убраны, AGENT_SECRET подсвечивается) — macOS-only хелпер остаётся; бэкапы/мониторинг/CI — 🔲 OPEN (не в скоупе); eslint — ✅ фикс (добавлен в devDeps, `.eslintrc.cjs`, `npm run lint` зелёный).

## 5. Известные баги из `NOTES.md` — статусы

1. `_latex_is_available()` не вызывается — 🔲 OPEN (безвредный, оставлен).
2. `_heuristic_video_needed` недостижимая ветка — 🔲 OPEN (безвредно, оставлено).
3. `format_output` возвращает `None` при video_needed=false (агент жмёт `or ""`) — 🔲 OPEN (код-примечание, работает).
4. `_TRANSIENT_LLM_MARKERS` сырые подстроки — ✅ FIXED (точные маркеры + хвост строки -300).
5. env при импорте — 🔲 OPEN (осознанно; теперь валидируется).
6. forward reference в `_detect_language` — 🔲 OPEN (не вызывается в рантайме).
7. **Параллельная группа (баг 9)** — ✅ FIXED (см. 2.1; educator_text_len>0 в live).
8. `manim_script` без входящего ребра — ✅ FIXED (явный edge `educator_video → manim_script`).

---

## 6. Что сделано хорошо (подтверждено проверкой)

Без изменений по сути (плюс теперь перепроверено на живом стеке): XSS-позиция чистая; очистка ресурсов; reconnect адекватный; хуки чистые; бэкенд async (Motor) + индексы + no secrets; агент чистит temp-файлы, телеметрия не роняет пайплайн, graceful degradation, ретраи с бэк-оффом, `asyncio.to_thread` для блокирующих вызовов; деплой — порядок старта, restart, порт Mongo не опубликован, `.env` в .gitignore (проверено), пины версий точные.

## 7. Рекомендуемый порядок исправлений — статус дорожной карты

**Фаза 1 — обязательно до любого публичного запуска:**
1. ✅ Настоящая аутентификация + серверный user_id + защита всех роутов и WS (1.1).
2. ✅ Защита `/ws/agent` (секрет, не наружу) + uuid4 request_id (1.2).
3. ✅ Песочница исполнения Manim: непривилегированный юзер, без сети к коду, лимиты, kill группы по таймауту (1.3).
4. ✅ Разделители/маркировка пользовательского ввода в промптах + AST-валидация финального скрипта (1.4).
5. ⏸️ TLS (2.7) и Mongo auth (2.6) — остаётся перед интернет-деплоем; оба готовы к включению без код-изменений.

**Фаза 2 — стабильность:**
6. ✅ Параллельная группа починена (последовательно, двойной LLM-вызов убран) (2.1); проверено измерением в live `educator_text_len`.
7. ✅ Таймауты на WS/LLM/рендер, лимиты кадров (2.9, 2.10, 3.23), лимиты изображений (3.19); ограничение параллелизма — ⚠️ (см. 3.29).
8. ✅ Крос-чат-контаминация / потеря сообщений на фронте, heartbeat (2.2, 2.3, 2.4).
9. ✅ `pending_requests` TTL + sweep + ownership-check user_message + уведомление при дисконнекте агента (2.12, 2.13, 3.10) — ретрай «at-least-once» частично (см. 3.29).

**Фаза 3 — гигиена деплоя:**
10. ✅ Non-root контейнеры, лимиты ресурсов, `.dockerignore`, `npm ci`, ротация логов, healthchecks, явный media-том, explicit MANIM_OUTPUT_DIR (2.8, 3.25–3.31). Retention media и бэкапы — 🔲 OPEN.

---

## 8. Текущее состояние стека (проверено на живом, 30.08.2026)

- `docker ps`: 4 контейнера `spoon-*` работают; all HEALTHY; агент подключён («Connected to backend as AI Agent» / «Agent authenticated (handshake ok)»).
- `GET /health` (через nginx :3000) → `{"status":"healthy", "database":"connected", ...}` (проверяет БД ping).
- `GET /ws/agent` через nginx → 403 (nginx block, проверено).
- `GET /api/auth/me` без куки → 401 (проверено с хоста и из логов бэкенда).
- Live-аутентификация: signup 201 → me 200 → logout 200 → me 401 → login 200 → me 200 (проверено curl + Playwright UI).
- **Реальный LLM-рендер (с временным ключом):** запрос «Explain gravity» → казахский ответ + mp4 762 КБ в `/media` (GET 200 авторизованным / 401 без куки). Телеметрия: `language=kk, is_science=true, educator_text_len=2413/2578, render_ok=true`.
- **Песочница рендера:** DOC_SNIPPET_MODE=1 → stub-видео Demo_.mp4 (16 КБ) отрендерилось (рендер в песочнице). Телеметрия `render_attempt=1, render_ok=true`.
- `GEMINI_API_KEY` в `.env` пуст → агент отвечает вежливым «AI-функции сейчас недоступны: добавьте GEMINI_API_KEY в .env …» как обычный ai_response (без crash, без error-фрейма). Для ИИ: вписать ключ в `.env` (+ `GEMINI_MODEL=gemini-3-flash-preview` — spoon_ai читает модель из `GEMINI_MODEL`, **не** `DEFAULT_MODEL`) и `docker compose up -d agent`.
- **Автотесты:** backend-смоук 38/38 (`logs/backend_smoke.py`), check.sh 39/39, UI Playwright 9/9 + 8/8 (`logs/ui_regression.py`, `logs/ui_video.py`). Найдено и fixed вживую: email sparse-index (см. b2827df), GEMINI_MODEL env, skip no-key-early return для DOC_SNIPPET (e5e1925).

*Отчёт изначально подготовлен в режиме read-only; статусы добавлены после фикс-раунда. Обновлённая версия сохранена как `ANYQ_AUDIT_REPORT.md` в корне репозитория (для истории).*