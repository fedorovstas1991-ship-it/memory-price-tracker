import { Bot, InlineKeyboard } from "grammy";
import fetch from "node-fetch";

const BOT_TOKEN =
  process.env.BOT_TOKEN || "8007263809:AAFYZkUvsn9lWHusf9U_1sLBZUG-aK-dJpQ";
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";
const WEBAPP_URL =
  process.env.WEBAPP_URL ||
  "https://fedorovstas1991-ship-it.github.io/memory-price-tracker/";

const bot = new Bot(BOT_TOKEN);

// /start command
bot.command("start", async (ctx) => {
  const keyboard = new InlineKeyboard()
    .webApp("Открыть дашборд", WEBAPP_URL)
    .row()
    .text("Поиск по парт-номеру", "search_prompt")
    .text("Статистика", "stats");

  await ctx.reply(
    `Привет! Я отслеживаю цены на чипы памяти из 7 источников по всему миру.\n\n` +
      `📊 ~40 000 позиций\n` +
      `🔄 Обновление каждые 4 часа\n\n` +
      `Основной инструмент — дашборд:\n` +
      `• Фильтры по типу, бренду, объёму, источнику\n` +
      `• Графики распределения цен и трендов\n` +
      `• Таблица с сортировкой и поиском\n` +
      `• Детализация по каждому чипу со сравнением цен`,
    { reply_markup: keyboard }
  );
});

// /search command
bot.command("search", async (ctx) => {
  const query = ctx.match?.trim();

  if (!query) {
    await ctx.reply(
      "Укажите парт-номер для поиска. Например: /search KLMAG1JETD"
    );
    return;
  }

  await ctx.reply(`🔍 Ищу "${query}"...`);

  let data;
  try {
    const res = await fetch(
      `${API_URL}/api/prices?search=${encodeURIComponent(query)}&limit=10`,
      { signal: AbortSignal.timeout(10000) }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    await ctx.reply("Данные временно недоступны");
    return;
  }

  const items = data?.items ?? data?.results ?? data ?? [];
  if (!Array.isArray(items) || items.length === 0) {
    await ctx.reply(`🔍 По запросу "${query}" ничего не найдено.`);
    return;
  }

  // Group by part number
  const grouped = {};
  for (const item of items) {
    const partNumber = item.part_number ?? item.partNumber ?? item.sku ?? "—";
    if (!grouped[partNumber]) grouped[partNumber] = [];
    grouped[partNumber].push(item);
  }

  let text = `🔍 Результаты для "${query}":\n\n`;
  for (const [partNumber, entries] of Object.entries(grouped)) {
    text += `${partNumber}\n`;
    const last = entries.length - 1;
    entries.forEach((entry, idx) => {
      const source = entry.source ?? entry.supplier ?? "—";
      const price =
        entry.price != null
          ? `$${Number(entry.price).toFixed(2)}`
          : "—";
      const prefix = idx === last ? "└" : "├";
      text += `${prefix} ${source}: ${price}\n`;
    });
    text += "\n";
  }

  const keyboard = new InlineKeyboard().webApp(
    "Открыть в дашборде",
    WEBAPP_URL
  );

  await ctx.reply(text.trim(), { reply_markup: keyboard });
});

// /stats command
async function sendStats(ctx) {
  let data;
  try {
    const res = await fetch(`${API_URL}/api/stats`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    await ctx.reply("Данные временно недоступны");
    return;
  }

  const fmt = (n) =>
    n != null ? Number(n).toLocaleString("en-US") : "—";

  const updatedAt =
    data?.updated_at ?? data?.updatedAt ?? data?.last_updated ?? null;
  const updatedStr = updatedAt
    ? new Date(updatedAt).toISOString().replace("T", " ").slice(0, 16) + " UTC"
    : "—";

  const text =
    `📊 Статистика\n\n` +
    `Позиций: ${fmt(data?.total ?? data?.count ?? data?.positions)}\n` +
    `Типов: ${fmt(data?.types ?? data?.type_count)}\n` +
    `Брендов: ${fmt(data?.brands ?? data?.brand_count)}\n` +
    `Источников: ${fmt(data?.sources ?? data?.source_count ?? 7)}\n` +
    `Обновлено: ${updatedStr}`;

  await ctx.reply(text);
}

bot.command("stats", sendStats);

// Callback query handlers
bot.callbackQuery("search_prompt", async (ctx) => {
  await ctx.answerCallbackQuery();
  await ctx.reply(
    "Введите парт-номер для поиска (например KLMAG1JETD):\n\n" +
      "Используйте команду: /search <парт-номер>"
  );
});

bot.callbackQuery("stats", async (ctx) => {
  await ctx.answerCallbackQuery();
  await sendStats(ctx);
});

// Catch-all for unhandled callback queries
bot.on("callback_query", async (ctx) => {
  await ctx.answerCallbackQuery();
});

// Error handling
bot.catch((err) => {
  console.error("Bot error:", err);
});

console.log("Starting Memory Price Tracker bot...");
bot.start();
