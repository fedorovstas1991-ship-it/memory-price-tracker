# Memory Price Tracker

Telegram Mini App для мониторинга цен на чипы памяти (DRAM, Flash, eMMC, SSD).
VPS: 165.22.193.71 | Bot: @memorydash_bot | Stack: FastAPI + vanilla JS + Chart.js + PostgreSQL

## Расположение проекта

```
Локально:  ~/memory-price-tracker/        — git repo, main branch
VPS:       /opt/mpt/                       — production deployment
Git:       github.com/fedorovstas1991-ship-it/memory-price-tracker
```

**Связь:** Локальный код деплоится на VPS через `scp`. Git — для версионирования.
**ВАЖНО:** `market_crawl.py` живёт ТОЛЬКО на VPS (`/opt/mpt/scraper/market_crawl.py`), НЕ в git!

## Доступ к VPS

```bash
ssh root@165.22.193.71

# Сервисы (все 4 должны быть active)
systemctl status mpt-api mpt-bot mpt-crawl cf-tunnel --no-pager

# Логи
tail -f /tmp/crawl_all.log      # каталог краулер
tail -f /tmp/market_crawl.log   # рынок краулер
journalctl -u mpt-api -f        # API
journalctl -u mpt-bot -f        # бот

# Ручной краул
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 crawl_all.py
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 market_crawl.py

# БД
PGPASSWORD=mpt_secure_2026 psql -U mpt -h 127.0.0.1 -d memoryprices
```

## Архитектура

```
VPS (/opt/mpt/):
  api/main.py            — FastAPI, 14+ endpoints, asyncpg, include_meta system
  webapp/index.html       — single-file UI (vanilla JS + Chart.js, neon dark theme)
  bot/index.js            — grammY бот @memorydash_bot
  scraper/crawl_all.py    — монолитный краулер, 7 источников (eBay отключен)
  scraper/market_crawl.py — DRAMeXchange + TrendForce + WhereIsMyRam (НЕ в git!)
  .env                    — секреты

Локально (не на VPS):
  scraper/crawlers/       — модульные краулеры (устарели, но с фиксами из сессии 2026-04-04)
  src/scrapers/           — legacy watchlist краулеры (НЕ используются)
```

## Деплой

**ВСЕГДА делать бэкап перед деплоем!**

```bash
# 1. Бэкап на VPS
ssh root@165.22.193.71 "cp /opt/mpt/webapp/index.html /opt/mpt/webapp/index.html.bak.\$(date +%Y%m%d_%H%M%S)"
ssh root@165.22.193.71 "cp /opt/mpt/api/main.py /opt/mpt/api/main.py.bak.\$(date +%Y%m%d_%H%M%S)"

# 2. Frontend + API
scp webapp/index.html root@165.22.193.71:/opt/mpt/webapp/index.html
scp api/main.py root@165.22.193.71:/opt/mpt/api/main.py
ssh root@165.22.193.71 "systemctl restart mpt-api"

# 3. Краулер
scp scraper/crawl_all.py root@165.22.193.71:/opt/mpt/scraper/crawl_all.py
ssh root@165.22.193.71 "systemctl restart mpt-crawl"

# 4. Проверка
ssh root@165.22.193.71 "curl -s http://127.0.0.1:8000/api/stats | python3 -m json.tool"
```

## Cloudflare Tunnel

Quick tunnel — URL меняется при рестарте! При смене обновить:
1. `.env` → `WEBAPP_URL=https://NEW_URL/`
2. Перезапустить бот: `systemctl restart mpt-bot`
3. Menu button: `curl -X POST "https://api.telegram.org/bot$TOKEN/setChatMenuButton" ...`

## UI архитектура (unified filter system)

Ключевой принцип: **один API-вызов, один контур фильтрации**.

```
Фильтр изменён → loadPrices() → GET /api/prices?include_meta=true&...filters...
                                          ↓
                              {items, meta, chart_meta, filter_options}
                                    ↓          ↓           ↓            ↓
                              renderCards  updateKpis  renderChart  repopulate selectors
```

- `meta`: total, stock_total, types_total, sources_total → KPI виджеты
- `chart_meta`: prices_by_capacity, stock_by_capacity, total_stock → графики каталога
- `filter_options`: types[], brands[], sources[], capacities[] (с counts по текущим фильтрам) → dropdown'ы
- Графики показывают топ-5, "Показать все (N)" раскрывает полный список
- Deals chart кликабельный → openDeal() модал с историей, фильтруется всеми фильтрами каталога
- Кнопка ✕ сбрасывает все фильтры
- Loading bar (position:fixed top) показывается во время API-загрузки
- updBadge показывает время обновления отдельно для каталога и рынка

## Фильтры — Telegram WebView совместимость

**КРИТИЧНО**: В Telegram iOS WebView нативный select-picker имеет особенности:
- `change` может файриться при прокрутке колеса (до выбора)
- `blur` может файриться ДО `change`
- Решение: `onfocus` сохраняет snap, `onchange`+`onblur` оба вызывают `selApply()`
- `selApply` сравнивает с snap → дубли невозможны, 50ms setTimeout на blur для race condition
- Capacity input: НЕ oninput (API на каждый символ!), а blur + Enter + datalist-match
- `_loadingPrices` + `_pendingLoad` — guard от параллельных вызовов с очередью

## Правила разработки

- **webapp/index.html** — единый файл, деплоится через `scp` на VPS
- **Telegram WebView** — `<select>` с onfocus/onchange/onblur pattern (см. выше)
- **Telegram кэш** — агрессивный, при изменениях менять tunnel URL или добавлять ?v=N
- **API лимиты** — JLCPCB 403 при быстрых запросах (fresh client per category, 3с между категориями)
- **Cron** — абсолютные пути: `/opt/mpt/.venv/bin/python3`
- **rtk** — на локальной машине стоит RTK (Rust Token Killer). Для отладки API использовать SSH на VPS
- **market_crawl.py** — живёт ТОЛЬКО на VPS, нет в git! При изменениях бэкапить вручную
- **БЭКАПЫ** — ВСЕГДА бэкапить файлы на VPS перед scp deploy

## Краулеры (crawl_all.py)

| # | Источник | Метод | Keywords | Задержки | Записей |
|---|----------|-------|----------|----------|---------|
| 1 | JLCPCB | JSON API POST + XSRF-TOKEN | 68 (EXPANDED_KEYWORDS) | 3s/page, 3s/cat | ~33K |
| 2 | SZLCSC | SSR HTML, Googlebot UA, resume state | 14 | 45+rand/page, 120+rand/kw | ~366 |
| 3 | MemoryMarket | HTML regex + /price/ews/ namespace | main + IDs 100160-100270 + 57 EWS | 0.5s | ~130 |
| 4 | LCSC | JSON API (wmsc.lcsc.com) | phase1: 200 pages + phase2: 68×5 | 2s/1.5s | ~16K |
| 5 | FindChips | HTML + Scrapling, EUR/GBP→USD | 68 × 30 pages | 1.5s + retry | ~5.9K+ |
| 6 | ChipDip | Scrapling headless | 1 catalog URL | 2s | 0 (DC blocked) |
| 7 | eBay | DISABLED | — | — | 0 |

**Currencies**: live USD/RUB (cbr-xml-daily.ru), live CNY/USD + EUR/USD + GBP/USD (er-api.com).
**DB write**: per-source iterative DELETE+COPY в транзакции. History: append-only, 90-day retention.

## Market краулер (market_crawl.py, VPS only)

| Источник | Записей | Метод |
|----------|---------|-------|
| TrendForce | ~7.4K (8 категорий incl eMMC_Spot, Module_Spot, UFS/eMMC Contract) | REST API с логином |
| DRAMeXchange | ~32 (7 категорий: dram/module/flash/gddr/wafer/memory_card/ssd_spot) | HTML scraping, li-tab detection |
| WhereIsMyRam | ~42 (5 стран, с percent_week/percent_month трендами) | REST API |

Cron: каждые 4 часа (`0 */4 * * *`)

## API endpoints

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
| `GET /api/charts/deals` | Выгодные позиции (скидка vs история, все фильтры каталога) |
| `GET /api/charts/market_summary` | Средние цены по рыночным категориям |
| `GET /api/market` | Последние рыночные цены (с percent_week/percent_month) |
| `GET /api/market/history/{item}` | История рыночных цен |

## БД: 3 таблицы

```sql
-- Каталог (DELETE per source + перезапись)
prices: id, chip_type, part_number, description, brand, capacity, source, distributor,
        price_usd, price_rub, price_cny, moq, stock, url, fetched_at

-- Биржевые цены (upsert по source+item+category+price_date)
market_prices: id, source, item, category, daily_high, daily_low,
               session_avg, session_change, price_date, fetched_at,
               percent_week, percent_month

-- История каталога (append-only, 90-day retention)
history: id, part_number, source, price_usd, fetched_at
```

## Фиксы сессии 2026-04-04 (вечерняя)

### Краулеры
- FindChips: per-row/per-tier try/except, retry 429/503, EUR/GBP→USD конвертация
- SZLCSC: exponential backoff на 302 (60→120→240s), resume через /tmp/szlcsc_state.json
- MemoryMarket: +57 EWS products, сужен /price/in/ range, фикс модульной версии
- TrendForce: +3 категории (eMMC_Spot, Module_Spot, eMMC_Contract = 35 items)
- DRAMeXchange: heading-walk через li-табы, SSD table спец-парсер
- WhereIsMyRam: percent_week/percent_month в DB

### UI
- Unified filter architecture (include_meta=true)
- Filter-aware selectors с counts
- Capacity фильтр через regex на description+part_number
- Neon chart styling
- Expandable charts (top-5 → show all)
- Deals chart clickable → openDeal() modal, filter-aware (type/brand/source/capacity/stock/search)
- WIMR trend badges в карточках рынка

### Фиксы сессии 2026-04-05 (ночная)
- Select фильтры: onfocus snap + onchange/onblur selApply с 50ms delay (iOS blur→change race)
- Capacity input: blur+Enter+datalist-match вместо oninput (убран дёрганый reload на каждый символ)
- PAGE_SIZE: 200 → 50
- Deals chart: полный контекст фильтров (type, brand, source, capacity, search, in_stock)
- Loading bar: CSS-only анимация, position:fixed top
- Кнопка ✕ сброса всех фильтров
- updBadge: раздельное время обновления для каталога и рынка
- Хедер не протекает из каталога в рынок
- Deals empty state: HTML вместо обрезанного canvas text
- _pendingLoad queue: второй фильтр не теряется если первый ещё грузится

## Известные проблемы

| Проблема | Где | Статус |
|----------|-----|--------|
| Мусорные capacity из part_number regex (01GB, 12843GB) | API chart_meta | Нужен строже regex |
| DRAMeXchange: contract цены JS-loaded | market_crawl.py (VPS) | Нужен headless browser |
| ChipDip: заблокирован на DC IP | crawl_all.py | Нужен residential proxy |
| market_crawl.py не в git | VPS | Нет бэкапа в git |
| Bot: hardcoded token fallback | bot/index.js | Секьюрити |
