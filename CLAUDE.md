# Memory Price Tracker

Telegram Mini App для мониторинга цен на чипы памяти (DRAM, Flash, eMMC, SSD).
VPS: 165.22.193.71 | Бот: @memorydash_bot | Stack: FastAPI + vanilla JS + Chart.js + PostgreSQL

---

## 1. Проект

**Что это**: Сервис агрегации цен на чипы памяти от дистрибьюторов и биржевых источников. Пользователь открывает Mini App в Telegram и видит актуальные цены, фильтрует по типу/бренду/источнику/объёму, смотрит тренды и выгодные позиции.

**Текущие данные в БД (2026-04-06)**:
- Каталог: **62 437 позиций** (7 источников), из них 19 416 со стоком
- Рынок: **7 528 биржевых котировок** (3 источника)
- Типов чипов: 11 | Брендов: 15 | Источников каталога: 7

**Для кого**: Закупщики, инженеры, любители, кто мониторит цены на память.

---

## 2. Расположение

```
Локально:  ~/memory-price-tracker/        — git repo, main branch
VPS:       /opt/mpt/                       — production deployment
Git:       github.com/fedorovstas1991-ship-it/memory-price-tracker
```

**Связь**: Локальный код деплоится на VPS через `scp`. Git — для версионирования.

**ВАЖНО**: `market_crawl.py` и `crawl_tme_mouser.py` живут ТОЛЬКО на VPS (`/opt/mpt/scraper/`), НЕ в git!

---

## 3. Архитектура

```
VPS 165.22.193.71 (/opt/mpt/):
  ┌─────────────────────────────────────────────────────────────┐
  │  api/main.py         — FastAPI (port 8000), asyncpg         │
  │  webapp/index.html   — single-file UI, 1275 строк           │
  │  bot/index.js        — grammY бот @memorydash_bot           │
  │  scraper/            — краулеры (см. раздел 6)              │
  │  .env                — секреты (DB, tokens, WEBAPP_URL)     │
  └─────────────────────────────────────────────────────────────┘
         ↕ asyncpg                 ↕ grammY webhook
  PostgreSQL (memoryprices)    Telegram Bot API

Cloudflare Quick Tunnel → cf-tunnel.service → FastAPI :8000

OpenClaw Gateway (openclaw-gateway.service, user unit):
  agent: main       → @spravtestbot1_bot  (модель: gpt-5.3-codex)
  agent: support-bot → @Suppdashmem_bot   (модель: gpt-5.4-mini)
```

**Локально (не на VPS)**:
```
scraper/crawlers/       — модульные краулеры (устарели, фиксы сессии 2026-04-04)
src/scrapers/           — legacy watchlist краулеры (НЕ используются)
webapp/index.html       — актуальный frontend (1275 строк)
```

---

## 4. Сервисы VPS

### systemd units (все 4 должны быть active)

| Unit | Описание | Статус |
|------|----------|--------|
| `mpt-api` | FastAPI, port 8000 | active |
| `mpt-bot` | grammY бот @memorydash_bot | active |
| `mpt-crawl` | crawl_forever.sh daemon (crawl_all.py в петле) | active |
| `cf-tunnel` | Cloudflare Quick Tunnel | active |

### OpenClaw Gateway (user unit)

```bash
systemctl --user status openclaw-gateway --no-pager
```

Gateway управляет двумя Telegram-агентами OpenClaw (см. раздел 11).

### Cron (root)

```
*/2 * * * *   /root/.openclaw/watchdog.sh --check >> /root/.openclaw/logs/watchdog.log
*/10 * * * *  /usr/local/bin/openclaw-gateway-watch.sh
0 */4 * * *   cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 market_crawl.py >> /tmp/market_crawl.log
```

**Краулер каталога** (`mpt-crawl`) работает как daemon через `crawl_forever.sh`, а не через cron.
**Краулер рынка** (`market_crawl.py`) — cron каждые 4 часа.
**TME+Mouser** (`crawl_tme_mouser.py`) — запускается вручную или интегрируется в crawl_forever.

---

## 5. Доступ к VPS

```bash
ssh root@165.22.193.71

# Проверка сервисов
systemctl status mpt-api mpt-bot mpt-crawl cf-tunnel --no-pager
systemctl --user status openclaw-gateway --no-pager

# Логи
tail -f /tmp/crawl_all.log      # каталог краулер
tail -f /tmp/market_crawl.log   # рынок краулер
journalctl -u mpt-api -f        # API
journalctl -u mpt-bot -f        # бот

# Ручной запуск краулеров
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 crawl_all.py
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 market_crawl.py
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 crawl_tme_mouser.py

# БД (интерактивно)
PGPASSWORD=mpt_secure_2026 psql -U mpt -h 127.0.0.1 -d memoryprices

# БД (скрипт, без декораций)
PGPASSWORD=mpt_secure_2026 psql -U mpt -h 127.0.0.1 -d memoryprices -t -A -F'|'

# Статистика
curl -s http://127.0.0.1:8000/api/stats | python3 -m json.tool
```

---

## 6. Краулеры

### Каталог дистрибьюторов

`crawl_all.py` — монолитный, работает как daemon через `crawl_forever.sh`.

| # | Источник | Метод | Записей | Особенности |
|---|----------|-------|---------|-------------|
| 1 | **JLCPCB** | JSON API POST + XSRF-TOKEN | **~33 249** | 3s/page, 3s/cat; CSRF fix (4K→33K) |
| 2 | **LCSC** | JSON API (wmsc.lcsc.com) | **~16 435** | Phase1: 200 стр, Phase2: 68×5 ключей |
| 3 | **FindChips** | HTML + Scrapling, EUR/GBP→USD | **~7 083** | retry 429/503, per-row try/except |
| 4 | **Mouser** | REST API (api.mouser.com) | **~5 271** | API ключ, `crawl_tme_mouser.py` |
| 5 | **TME** | REST API (api.tme.eu) + HMAC-SHA1 | **~213** | HMAC подпись, `crawl_tme_mouser.py` |
| 6 | **MemoryMarket** | HTML regex + /price/ews/ namespace | **~130** | 57 EWS, сужен /price/in/ range |
| 7 | **SZLCSC** | SSR HTML, Googlebot UA, resume state | **~56** | exponential backoff, /tmp/szlcsc_state.json |
| — | ChipDip | Scrapling headless | 0 | Заблокирован на DC IP |
| — | eBay | — | 0 | ОТКЛЮЧЁН |

**Итого каталог**: 62 437 позиций

**Валюты**: live USD/RUB (cbr-xml-daily.ru), CNY/USD + EUR/USD + GBP/USD (er-api.com).
**DB write**: per-source iterative DELETE+COPY в транзакции. History: append-only, 90-day retention.

### Рыночные бенчмарки

`market_crawl.py` — только на VPS, cron каждые 4 часа. **Нет в git!**

| Источник | Метод | Записей | Категории |
|----------|-------|---------|-----------|
| **TrendForce** | REST API с логином | **~7 413** | 8 кат.: dram_spot, dram_contract, flash_spot, flash_contract, module_spot, emmc_spot, eMMC_Contract, UFS |
| **WhereIsMyRam** | REST API | **~83** | 5 стран, percent_week/percent_month тренды |
| **DRAMeXchange** | HTML scraping, li-tab detection | **~32** | 7 кат.: dram, module, flash, gddr, wafer, memory_card, ssd_spot |

**Итого рынок**: 7 528 позиций

### Вспомогательные скрипты на VPS

| Файл | Описание |
|------|----------|
| `crawl_forever.sh` | Daemon: запускает crawl_all.py в бесконечном цикле |
| `crawl_tme_mouser.py` | TME + Mouser API краулер (ТОЛЬКО на VPS) |
| `market_crawl.py` | Рыночный краулер (ТОЛЬКО на VPS) |
| `monitor_chain.py` | Мониторинг цепочки поставок |
| `monitor_chain_runner.py` | Runner для monitor_chain |
| `snowball.py` | Утилита снежного шара (расширение данных) |
| `quick_source.py` | Быстрая проверка отдельного источника |
| `brand.py` | Нормализация брендов |
| `currency.py` | Конвертация валют |

---

## 7. API Endpoints

FastAPI на порту 8000. Итого **16 endpoints**.

| Endpoint | Описание |
|----------|----------|
| `GET /api/prices` | Каталог с фильтрами + `include_meta=true` → {items, meta, chart_meta, filter_options} |
| `GET /api/types` | Типы чипов с количеством |
| `GET /api/brands` | Бренды с количеством |
| `GET /api/sources` | Источники с количеством |
| `GET /api/stats` | Агрегатная сводка |
| `GET /api/history/{pn}` | История цен (mode=daily/full) |
| `GET /api/capacities` | Regex-извлечённые объёмы |
| `GET /api/charts/avg_by_type` | Средняя цена по типам |
| `GET /api/charts/by_source` | Количество по источникам |
| `GET /api/charts/prices_by_capacity` | Цены по объёмам (standalone) |
| `GET /api/charts/stock_by_capacity` | Стоки по объёмам (standalone) |
| `GET /api/charts/deals` | Выгодные позиции (скидка 15%+ vs история, учитывает все фильтры) |
| `GET /api/charts/market_summary` | Средние цены по рыночным категориям |
| `GET /api/market` | Последние рыночные цены (с percent_week/percent_month) |
| `GET /api/market/history/{item}` | История рыночных цен |
| `GET /api/export` | CSV экспорт каталога с фильтрами |

---

## 8. База данных

PostgreSQL, база `memoryprices`, пользователь `mpt`.

```sql
-- Каталог дистрибьюторов (62K+ позиций, DELETE per source + перезапись)
prices: id, chip_type, part_number, description, brand, capacity, source, distributor,
        price_usd, price_rub, price_cny, moq, stock, url, fetched_at

-- Биржевые цены (upsert по source+item+category+price_date)
market_prices: id, source, item, category, daily_high, daily_low,
               session_avg, session_change, price_date, fetched_at,
               percent_week, percent_month

-- История каталога (append-only, 90-day retention)
history: id, part_number, source, price_usd, fetched_at
```

**Deals-логика** (deals chart):
- Сравнивает `price_usd` из `prices` с `avg(price_usd)` из `history`
- Условия: `price_usd < avg_hist * 0.85` AND `stock >= 100` AND `COUNT(history) >= 3`
- Учитывает все активные фильтры каталога

---

## 9. Mini App UI

Единый файл `webapp/index.html` (1 275 строк), vanilla JS + Chart.js, neon dark theme.

### Архитектура фильтрации (unified filter system)

```
Фильтр изменён → loadPrices() → GET /api/prices?include_meta=true&...filters...
                                         ↓
                             {items, meta, chart_meta, filter_options}
                                   ↓          ↓           ↓            ↓
                             renderCards  updateKpis  renderChart  repopulate selectors
```

- `meta`: total, stock_total, types_total, sources_total → KPI виджеты
- `chart_meta`: prices_by_capacity, stock_by_capacity → графики
- `filter_options`: types[], brands[], sources[], capacities[] с counts → dropdown'ы
- Графики: топ-5, "Показать все (N)" раскрывает полный список
- Deals chart кликабельный → `openDeal()` модал с историей
- Кнопка ✕ сбрасывает все фильтры
- Loading bar (position:fixed top) — CSS-only анимация
- `updBadge` — раздельное время обновления для каталога и рынка

### Вкладки

**Каталог**: KPI → Фильтры → 3 графика (цены/стоки/deals) → карточки позиций
**Рынок**: биржевые бенчмарки по категориям, trend badges (percent_week/percent_month)

---

## 10. Telegram боты

### @memorydash_bot (grammY, mpt-bot.service)

Основной бот Mini App. Inline keyboard:
- `menu_stats` — статистика
- `menu_deals` — топ скидки
- `menu_market` — рынок
- `menu_search` / `menu_search_new` — поиск
- `menu_back` — назад

Файл: `/opt/mpt/bot/index.js`

### @Suppdashmem_bot (OpenClaw, agent: support-bot)

Аналитический AI-бот на базе OpenClaw. Агент `support-bot`:
- Identity: MemoryDash AI
- Workspace: `/root/.openclaw/workspace-support/`
- Model: `openai-codex/gpt-5.4-mini`
- Binding: telegram accountId=memorydash
- Умеет: SQL запросы к БД, генерация PDF-отчётов, matplotlib графики, CSV экспорт

### @spravtestbot1_bot (OpenClaw, agent: main)

Основной OpenClaw агент:
- Identity: YaBot
- Workspace: `/root/.openclaw/workspace/`
- Model: `openai-codex/gpt-5.3-codex`
- Binding: telegram accountId=main

---

## 11. OpenClaw

OpenClaw Gateway работает как user systemd unit на VPS.

```bash
# Проверить статус
systemctl --user status openclaw-gateway --no-pager

# Список агентов
openclaw agents list --bindings

# Workspace support-bot (MemoryDash AI)
ls /root/.openclaw/workspace-support/

# Workspace main (YaBot)
ls /root/.openclaw/workspace/
```

**Агенты**:

| Агент | Бот | Модель | Workspace |
|-------|-----|--------|-----------|
| `support-bot` | @Suppdashmem_bot | gpt-5.4-mini | `/root/.openclaw/workspace-support/` |
| `main` | @spravtestbot1_bot | gpt-5.3-codex | `/root/.openclaw/workspace/` |

**Ключевые файлы workspace support-bot**:
- `AGENTS.md` — инструкции агента, SQL-запросы, аналитические фреймворки
- `IDENTITY.md` — кто такой MemoryDash AI
- `SOUL.md` — как агент работает

---

## 12. Деплой

**ВСЕГДА делать бэкап перед деплоем!**

```bash
# 1. Бэкап на VPS
ssh root@165.22.193.71 "cp /opt/mpt/webapp/index.html /opt/mpt/webapp/index.html.bak.\$(date +%Y%m%d_%H%M%S)"
ssh root@165.22.193.71 "cp /opt/mpt/api/main.py /opt/mpt/api/main.py.bak.\$(date +%Y%m%d_%H%M%S)"

# 2. Frontend
scp webapp/index.html root@165.22.193.71:/opt/mpt/webapp/index.html

# 3. API
scp api/main.py root@165.22.193.71:/opt/mpt/api/main.py
ssh root@165.22.193.71 "systemctl restart mpt-api"

# 4. Краулер каталога
scp scraper/crawl_all.py root@165.22.193.71:/opt/mpt/scraper/crawl_all.py
ssh root@165.22.193.71 "systemctl restart mpt-crawl"

# 5. Бот
scp bot/index.js root@165.22.193.71:/opt/mpt/bot/index.js
ssh root@165.22.193.71 "systemctl restart mpt-bot"

# 6. Проверка
ssh root@165.22.193.71 "curl -s http://127.0.0.1:8000/api/stats | python3 -m json.tool"
ssh root@165.22.193.71 "systemctl status mpt-api mpt-bot mpt-crawl cf-tunnel --no-pager | grep -E 'Active|●'"
```

---

## 13. Cloudflare Tunnel

Cloudflare Quick Tunnel — **URL меняется при рестарте!**

При смене URL обновить:
1. `.env` → `WEBAPP_URL=https://NEW_URL/`
2. Перезапустить бот: `systemctl restart mpt-bot`
3. Menu button: `curl -X POST "https://api.telegram.org/bot$TOKEN/setChatMenuButton" -d '{"menu_button":{"type":"web_app","text":"Dashboard","web_app":{"url":"https://NEW_URL/"}}}'`

```bash
# Проверить текущий URL
systemctl status cf-tunnel --no-pager
# или
journalctl -u cf-tunnel --since "5 minutes ago" | grep trycloudflare
```

---

## 14. Правила разработки

### Telegram WebView совместимость (КРИТИЧНО)

В iOS Telegram WebView нативный `<select>` имеет особенности:
- `change` может файриться при прокрутке колеса (до выбора)
- `blur` может файриться ДО `change`
- **Решение**: `onfocus` сохраняет snap, `onchange`+`onblur` оба вызывают `selApply()`
- `selApply` сравнивает с snap → дубли невозможны, 50ms setTimeout на blur для race condition
- Capacity input: НЕ `oninput` (API на каждый символ!), а `blur + Enter + datalist-match`
- `_loadingPrices` + `_pendingLoad` — guard от параллельных вызовов с очередью

### Общие правила

- **webapp/index.html** — единый файл, деплоится через `scp`
- **Telegram кэш** — агрессивный, при изменениях менять tunnel URL или добавлять `?v=N`
- **API лимиты** — JLCPCB 403 при быстрых запросах (fresh client per category, 3с между категориями)
- **Cron** — абсолютные пути: `/opt/mpt/.venv/bin/python3`
- **market_crawl.py** и **crawl_tme_mouser.py** — живут ТОЛЬКО на VPS, нет в git! При изменениях бэкапить вручную
- **БЭКАПЫ** — ВСЕГДА бэкапить файлы на VPS перед scp deploy
- **rtk** — на локальной машине стоит RTK (Rust Token Killer), команды прозрачно проксируются

---

## 15. Известные проблемы

| Проблема | Где | Статус |
|----------|-----|--------|
| Мусорные capacity из part_number regex (01GB, 12843GB) | API chart_meta | Нужен строже regex |
| DRAMeXchange: contract цены JS-loaded | market_crawl.py (VPS) | Нужен headless browser |
| ChipDip: заблокирован на DC IP | crawl_all.py | Нужен residential proxy |
| market_crawl.py и crawl_tme_mouser.py не в git | VPS | Нет бэкапа в git, бэкапить вручную |
| Cloudflare Quick Tunnel URL меняется при рестарте | .env, bot | Нужно обновлять вручную |
| Bot: hardcoded token fallback | bot/index.js | Секьюрити |
| SZLCSC медленный (120+s/kw backoff) | crawl_all.py | По дизайну, не баг |

---

## История ключевых изменений

### Сессия 2026-04-04 (дневная)
- FindChips: per-row/per-tier try/except, retry 429/503, EUR/GBP→USD конвертация
- SZLCSC: exponential backoff на 302, resume через /tmp/szlcsc_state.json
- MemoryMarket: +57 EWS products, фикс модульной версии
- TrendForce: +3 категории (eMMC_Spot, Module_Spot, UFS)
- DRAMeXchange: heading-walk через li-табы, SSD table спец-парсер
- WhereIsMyRam: percent_week/percent_month в DB + COALESCE fix

### Сессия 2026-04-04 (вечерняя)
- Unified filter architecture (include_meta=true)
- Filter-aware selectors с counts
- Capacity фильтр через regex на description+part_number
- Deals chart кликабельный → openDeal() modal
- WIMR trend badges в карточках рынка

### Сессия 2026-04-05 (ночная)
- Select фильтры: onfocus snap + onchange/onblur selApply с 50ms delay
- Capacity input: blur+Enter+datalist-match вместо oninput
- PAGE_SIZE: 200 → 50
- Loading bar: CSS-only анимация, position:fixed top
- Кнопка ✕ сброса всех фильтров
- updBadge: раздельное время обновления каталог/рынок
- _pendingLoad queue: второй фильтр не теряется
- TME + Mouser краулер (crawl_tme_mouser.py): +5 271 + 213 позиций
