# Memory Price Tracker

Telegram Mini App для мониторинга цен на чипы памяти (DRAM, Flash, eMMC, SSD).

## Архитектура

Полная документация: [ARCHITECTURE.md](ARCHITECTURE.md)

## Quick Reference

### VPS: 165.22.193.71

```bash
ssh root@165.22.193.71

# Сервисы
systemctl restart mpt-api mpt-bot cf-tunnel
systemctl status mpt-api mpt-bot cf-tunnel

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

### Структура на VPS (/opt/mpt/)

| Файл | Что |
|------|-----|
| `api/main.py` | FastAPI — 8 endpoints (/api/prices, /api/market, etc.) |
| `bot/index.js` | grammY бот @memorydash_bot |
| `scraper/crawl_all.py` | Краулер каталога: 6 источников, 25K+ позиций |
| `scraper/market_crawl.py` | Краулер рынка: DRAMeXchange + TrendForce |
| `webapp/index.html` | Весь UI — single HTML, vanilla JS + Chart.js |
| `.env` | Секреты: DB, bot token, TrendForce/DRAMeX креды, WEBAPP_URL |

### Cloudflare Tunnel

Quick tunnel — URL меняется при рестарте! При смене обновить:
1. `.env` → `WEBAPP_URL=https://NEW_URL/`
2. Перезапустить бот: `systemctl restart mpt-bot`
3. Menu button: `curl -X POST "https://api.telegram.org/bot$TOKEN/setChatMenuButton" -H "Content-Type: application/json" -d '{"menu_button":{"type":"web_app","text":"Dashboard","web_app":{"url":"https://NEW_URL/"}}}'`

### Правила разработки

- **webapp/index.html** — единый файл, деплоится через `scp` на VPS
- **Telegram WebView** — `<select onchange>` НЕ работает, использовать `<button onclick>`
- **Telegram кэш** — агрессивный, при изменениях менять tunnel URL или добавлять ?v=N
- **API лимиты** — JLCPCB 403 при быстрых запросах (15с между категориями)
- **Cron** — абсолютные пути: `/opt/mpt/.venv/bin/python3`, НЕ `source` и НЕ `python -m`
- **rtk** — на локальной машине стоит RTK (Rust Token Killer), сжимает вывод curl. Для отладки API использовать SSH на VPS

### БД: 3 таблицы

```sql
-- Каталог (TRUNCATE + перезапись каждые 4ч)
prices: id, chip_type, part_number, description, brand, capacity, source, distributor, price_usd, price_rub, price_cny, moq, stock, url, fetched_at

-- Биржевые цены (TRUNCATE + перезапись каждые 4ч)
market_prices: id, source, item, category, daily_high, daily_low, session_avg, session_change, price_date, fetched_at

-- История каталога (append-only)
history: id, part_number, source, price_usd, fetched_at
```
