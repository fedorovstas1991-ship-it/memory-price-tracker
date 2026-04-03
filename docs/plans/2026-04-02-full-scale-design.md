# Memory Price Tracker v2 — Full Scale Design

## Цель

Собрать ВСЕ Flash-память и ВСЕ RAM-память из ВСЕХ доступных источников (Китай, РФ, СНГ, США) в единую БД. Дашборд через Telegram Mini App с фильтрами по типу, объёму, бренду.

## Архитектура

```
GitHub Pages                    VPS (165.22.193.71)
┌──────────────┐     API        ┌─────────────────────────┐
│  Mini App    │ ◄──────────►   │  FastAPI (port 8000)    │
│  (static)    │    /api/*      │    ├── /api/prices       │
└──────────────┘                │    ├── /api/types        │
                                │    ├── /api/brands       │
@memorydash_bot                 │    └── /api/stats        │
┌──────────────┐                │                         │
│  grammY bot  │ ◄──────────►   │  PostgreSQL (local)     │
│  (inline KB) │    queries     │    └── prices, history   │
└──────────────┘                │                         │
                                │  Python scrapers (cron)  │
                                │    ├── findchips (ALL)    │
                                │    ├── szlcsc (ALL)       │
                                │    ├── jlcpcb (ALL)       │
                                │    ├── memorymarket (ALL) │
                                │    ├── chipdip (ALL)      │
                                │    └── ebay (Playwright)  │
                                └─────────────────────────┘
```

## Компоненты

### 1. PostgreSQL

```sql
CREATE TABLE prices (
    id BIGSERIAL PRIMARY KEY,
    chip_type TEXT NOT NULL,        -- eMMC, DDR4, NAND, NOR, UFS, LPDDR4X, DDR5...
    part_number TEXT NOT NULL,
    description TEXT,
    brand TEXT,                     -- Samsung, Micron, SK Hynix, Kioxia, Winbond...
    capacity TEXT,                  -- 16GB, 4Gbit, 512Mb...
    source TEXT NOT NULL,           -- findchips, szlcsc, chipdip, memorymarket, jlcpcb, ebay
    distributor TEXT,               -- LCSC, Win Source, Mouser (from findchips)
    price_usd NUMERIC(12,4),
    price_rub NUMERIC(12,2),
    price_cny NUMERIC(12,4),
    moq INT DEFAULT 1,
    stock INT,
    url TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE history (
    id BIGSERIAL PRIMARY KEY,
    part_number TEXT NOT NULL,
    source TEXT NOT NULL,
    price_usd NUMERIC(12,4),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_prices_type ON prices(chip_type);
CREATE INDEX idx_prices_brand ON prices(brand);
CREATE INDEX idx_prices_source ON prices(source);
CREATE INDEX idx_prices_part ON prices(part_number);
CREATE INDEX idx_history_part_date ON history(part_number, fetched_at);
```

### 2. Scrapers (Python, полный каталог)

Вместо watchlist из 34 чипов — **полный обход каталогов**:

| Источник | Подход | Ожидаемый объём |
|----------|--------|-----------------|
| FindChips | Поиск по категориям: "eMMC", "DDR4", "NAND Flash", "NOR Flash", "UFS", "LPDDR", "DDR5" | ~5000-20000 |
| SZLCSC | Каталог категорий: IC Memory → подкатегории, пагинация | ~5000-10000 |
| JLCPCB | POST API с keyword по категориям, пагинация | ~2000-5000 |
| MemoryMarket | Все страницы спотовых индексов + прямые ссылки /price/in/ID | ~200-500 |
| ChipDip | Каталог IC Memory, все страницы пагинации | ~500-2000 |
| eBay | Playwright, поиск по категориям | ~1000-3000 |

**Итого: ~15000-40000 записей за прогон.**

Каждый скрейпер:
1. Обходит каталог/категорию целиком (не по watchlist)
2. Извлекает brand из part_number или description
3. Пишет batch INSERT в PostgreSQL
4. Перед записью — TRUNCATE prices (атомарно в транзакции)
5. Параллельно пишет в history (append-only)

### 3. FastAPI (REST API для Mini App)

```
GET /api/prices?type=DDR4&brand=Samsung&capacity=8Gbit&source=findchips&sort=price_usd&limit=100&offset=0
GET /api/types          → [{type: "DDR4", count: 5234}, ...]
GET /api/brands         → [{brand: "Samsung", count: 2100}, ...]
GET /api/sources        → [{source: "findchips", count: 15000}, ...]
GET /api/stats          → {total: 35000, types: 12, brands: 45, sources: 6, updated: "..."}
GET /api/history/{part} → [{date, source, price_usd}, ...]
GET /api/charts/avg_by_type → [{type, avg_price}, ...]
GET /api/charts/by_source   → [{source, count}, ...]
```

CORS: `Access-Control-Allow-Origin: https://fedorovstas1991-ship-it.github.io`

### 4. Telegram Bot (@memorydash_bot)

grammY на Node.js (или Python aiogram). Trade-bot стиль:

```
/start → "Выберите тип памяти"
  [eMMC] [DDR4] [DDR5] [NAND] [NOR] [UFS] [LPDDR4X] [Все]
    → "Выберите бренд"
      [Samsung] [Micron] [SK Hynix] [Kioxia] [Все]
        → "Объём?"
          [4GB] [8GB] [16GB] [32GB] [64GB] [Все]
            → Таблица результатов (top-20 по цене)
            → Кнопка [Открыть дашборд] → Mini App

/search KLMAG1JETD → прямой поиск по part number
/stats → общая статистика
/alerts → настройка уведомлений (v2)
```

### 5. Mini App (GitHub Pages)

Полноценный дашборд, данные через FastAPI с VPS:
- Dropdown селекторы: Type, Brand, Capacity, Source
- KPI метрики (total, types, brands, sources)
- Графики: distribution by type, by source, avg price by type
- Сортируемая таблица с пагинацией
- Детальный модал с историей цен

## Стек на VPS

- **Python 3.11** + uv — scrapers
- **PostgreSQL 16** — БД
- **FastAPI + uvicorn** — REST API
- **Node.js 22 + grammY** — Telegram bot
- **nginx** — reverse proxy (API на :8000 → :443)
- **systemd** — сервисы (bot, api)
- **cron** — scrapers каждые 4 часа

## Бот UX (@memorydash_bot)

### /start
```
Привет! Я отслеживаю цены на чипы памяти
из 7 источников по всему миру.

📊 ~40 000 позиций
🔄 Обновление каждые 4 часа

Основной инструмент — дашборд:
• Фильтры по типу, бренду, объёму, источнику
• Графики распределения цен и трендов
• Таблица с сортировкой и поиском
• Детализация по каждому чипу со сравнением цен

         [Открыть дашборд]

Также можно прямо здесь:
[Поиск по парт-номеру]  [Статистика]
```

### /search <part>
Прямой поиск → таблица результатов inline.

### /stats
Общая статистика: кол-во позиций, источники, последнее обновление.

### Источники (v1 — 7 штук)
FindChips (~20K), SZLCSC (~10K), JLCPCB (~5K), ChipDip (~2K),
MemoryMarket (~500), eBay (~3K via Playwright), DigiKey (~30K via Playwright).

Итого: ~40K-70K записей.

## Деплой план

1. VPS setup: PostgreSQL 16, Python 3.11, Node.js 22, nginx, Cloudflare Tunnel
2. Создать БД и таблицы
3. Scrapers v2: каталожный обход + PostgreSQL вместо Sheets
4. FastAPI REST API
5. grammY бот с inline keyboards + Mini App кнопка
6. Mini App v2: API вместо CSV
7. systemd сервисы (bot, api)
8. Первый полный прогон
9. Cron каждые 4 часа
