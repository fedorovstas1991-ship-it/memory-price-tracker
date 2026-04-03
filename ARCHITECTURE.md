# Memory Price Tracker — Архитектура

## Обзор

Telegram Mini App для мониторинга цен на чипы памяти. Два таба: **Каталог** (25K+ позиций из 6 магазинов) и **Рынок** (биржевые цены с DRAMeXchange и TrendForce, 15 месяцев истории).

## VPS: 165.22.193.71 (DigitalOcean, 8GB/2vCPU, Ubuntu 24.04)

SSH: `ssh root@165.22.193.71`

### Структура `/opt/mpt/`

```
/opt/mpt/
├── .env                    # Все секреты (DB, bot token, TrendForce/DRAMeX креды)
├── .venv/                  # Python venv (asyncpg, httpx, scrapling, uvicorn, fastapi)
├── api/
│   └── main.py             # FastAPI — /api/prices, /api/stats, /api/market, /api/market/history/{item}
├── bot/
│   └── index.js            # grammY бот @memorydash_bot
├── scraper/
│   ├── crawl_all.py         # Каталог: JLCPCB, LCSC, FindChips, eBay, MemoryMarket, SZLCSC
│   └── market_crawl.py      # Рынок: DRAMeXchange (спот) + TrendForce (15 мес история)
└── webapp/
    └── index.html           # Единый HTML — весь UI (Lit-free, vanilla JS + Chart.js)
```

### Systemd сервисы

| Сервис | Что делает | Порт |
|--------|-----------|------|
| `mpt-api` | FastAPI + uvicorn | 8000 |
| `mpt-bot` | Telegram бот (grammY) | — |
| `cf-tunnel` | Cloudflare Quick Tunnel | → :80 |

### Nginx (порт 80)

- `/` → `/opt/mpt/webapp/index.html` (no-cache, no ETag)
- `/api/` → `proxy_pass http://127.0.0.1:8000/api/`

### Cloudflare Tunnel

Quick tunnel (бесплатный, URL меняется при рестарте):
- Текущий: `wilson-neutral-continental-shake.trycloudflare.com`
- Настраивается в: `.env` → `WEBAPP_URL`, бот, menu button

### Cron (каждые 4 часа)

```
0 */4 * * * crawl_all.py     # Каталог (25K+ позиций)
0 */4 * * * market_crawl.py  # Рынок (спот + история)
```

## База данных: PostgreSQL

DB: `memoryprices`, User: `mpt`, Pass: `mpt_secure_2026`

### Таблицы

| Таблица | Записей | Что хранит |
|---------|---------|-----------|
| `prices` | 25K+ | Каталог: парт-номер, цена USD/RUB, сток, источник, URL |
| `market_prices` | 7.4K+ | Биржа: спот/контракт цены, high/low/avg, дата |
| `history` | 42K+ | История каталожных цен (append-only) |

## Источники данных

### Каталог (crawl_all.py)

| Источник | Метод | Записей |
|----------|-------|---------|
| LCSC | REST API (wmsc.lcsc.com) + категория Memory ICs | ~5K |
| JLCPCB | REST API (jlcpcb.com) | ~3.5K |
| FindChips | HTML scraping + pagination | ~4K |
| eBay | Stealth browser (Scrapling) | ~400 |
| MemoryMarket | HTML scraping (main + detail pages) | ~70 |
| SZLCSC | SSR HTML (__NEXT_DATA__) | ~30 |

### Рынок (market_crawl.py)

| Источник | Метод | Логин | Позиций | История |
|----------|-------|-------|---------|---------|
| DRAMeXchange | HTML scraping (homepage) | Не нужен | 32 | Только текущие цены |
| TrendForce | REST API (AJAX) | Да | 61 | 15 месяцев |

TrendForce креды: `.env` → `TRENDFORCE_USER`, `TRENDFORCE_PASS`
DRAMeXchange креды: `.env` → `DRAMEX_USER`, `DRAMEX_PASS` (пока не используются)

## API Endpoints

| Endpoint | Описание |
|----------|---------|
| `GET /api/prices?limit=&sort=&order=&type=&brand=&source=&search=` | Каталог |
| `GET /api/stats` | Сводка каталога |
| `GET /api/types` | Типы чипов |
| `GET /api/brands` | Бренды |
| `GET /api/sources` | Источники |
| `GET /api/history/{part_number}` | История цены парт-номера |
| `GET /api/market` | Рыночные цены (последние, по категориям) |
| `GET /api/market/history/{item}` | История рыночной позиции |

## Telegram Bot: @memorydash_bot

- Token: `8007263809:AAFY...`
- Команды: `/start`, `/search <парт-номер>`, `/stats`
- WebApp URL: Cloudflare tunnel (настраивается в `.env`)
- Menu button: настраивается через `setChatMenuButton` API

## Типичные операции

```bash
# Перезапуск сервисов
systemctl restart mpt-api mpt-bot

# Новый tunnel URL (после рестарта cf-tunnel)
# 1. Посмотреть новый URL:
journalctl -u cf-tunnel --no-pager -n 20 | grep trycloudflare
# 2. Обновить .env, бот, menu button

# Ручной запуск краулера
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 crawl_all.py
cd /opt/mpt/scraper && /opt/mpt/.venv/bin/python3 market_crawl.py

# Проверка БД
PGPASSWORD=mpt_secure_2026 psql -U mpt -h 127.0.0.1 -d memoryprices

# Логи
tail -f /tmp/crawl_all.log
tail -f /tmp/market_crawl.log
journalctl -u mpt-api -f
journalctl -u mpt-bot -f
```

## GitHub

Repo: `github.com/fedorovstas1991-ship-it/memory-price-tracker`
Branch: `main`
GitHub Pages: `fedorovstas1991-ship-it.github.io/memory-price-tracker/` (устаревший, не используется)
