"""
🤖 API Finder Telegram Bot
Searches the public-apis/public-apis GitHub repo and returns matching APIs.
"""

import os
import logging
import asyncio
import aiohttp
import re
from functools import lru_cache
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from data_loader import APIDataLoader

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
MAX_RESULTS = 10          # Max APIs per response page
RESULTS_PER_PAGE = 5      # APIs shown per page

# ─── Initialize data loader (loads once, stays in memory) ───────────────────
data_loader = APIDataLoader()


# ─── Helpers ─────────────────────────────────────────────────────────────────
def format_api_entry(api: dict, index: int) -> str:
    """Format a single API entry for Telegram Markdown."""
    name = api.get("Name", "Unknown")
    desc = api.get("Description", "No description available.")
    link = api.get("Link", "#")
    auth = api.get("Auth", "")
    https = api.get("HTTPS", False)
    cors = api.get("Cors", "unknown")

    https_badge = "🔒" if https else "⚠️"
    auth_badge = f"🔑 `{auth}`" if auth else "🆓 No Auth"
    cors_badge = "✅ CORS" if cors == "yes" else ("❌ No CORS" if cors == "no" else "")

    badges = f"{https_badge} {auth_badge}"
    if cors_badge:
        badges += f"  {cors_badge}"

    return (
        f"*{index}. {name}*\n"
        f"📝 {desc}\n"
        f"{badges}\n"
        f"🔗 [View API]({link})\n"
    )


def build_results_message(results: list, keyword: str, page: int, total: int) -> str:
    """Build the full paginated results message."""
    start = page * RESULTS_PER_PAGE
    end = min(start + RESULTS_PER_PAGE, len(results))
    page_results = results[start:end]

    total_pages = (len(results) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE

    header = (
        f"🔍 *Results for:* `{keyword}`\n"
        f"📦 Found *{total}* APIs  |  Page *{page + 1}/{total_pages}*\n"
        f"{'─' * 30}\n\n"
    )

    body = "\n".join(
        format_api_entry(api, start + i + 1) for i, api in enumerate(page_results)
    )

    footer = f"\n{'─' * 30}\n💡 _Tip: Try keywords like_ `weather`, `ai`, `crypto`, `finance`"
    return header + body + footer


def build_pagination_keyboard(keyword: str, page: int, total: int) -> InlineKeyboardMarkup:
    """Build inline keyboard for pagination."""
    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    buttons = []

    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page:{keyword}:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("Next ▶️", callback_data=f"page:{keyword}:{page + 1}"))
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔄 New Search", callback_data="new_search"),
        InlineKeyboardButton("📋 Categories", callback_data="categories"),
    ])

    return InlineKeyboardMarkup(buttons)


# ─── Command Handlers ────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start."""
    user = update.effective_user
    msg = (
        f"👋 *Hey {user.first_name}!*\n\n"
        f"I'm your *API Finder Bot* 🤖\n"
        f"I search through *1000+ public APIs* so you don't have to.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*How to use me:*\n"
        f"Just send any keyword:\n"
        f"• `ai` → AI & Machine Learning APIs\n"
        f"• `weather` → Weather APIs\n"
        f"• `crypto` → Cryptocurrency APIs\n"
        f"• `music` → Music APIs\n\n"
        f"*Commands:*\n"
        f"/start — Show this message\n"
        f"/help — Detailed help\n"
        f"/categories — Browse all categories\n"
        f"/random — Discover a random API\n"
        f"/stats — Bot statistics\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Go ahead — send a keyword!*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help."""
    msg = (
        "📖 *API Finder Bot — Help*\n\n"
        "*Search Tips:*\n"
        "• Use single keywords: `finance`, `games`, `music`\n"
        "• Try category names: `animals`, `books`, `sports`\n"
        "• Tech terms work too: `blockchain`, `machine learning`\n\n"
        "*Understanding Results:*\n"
        "🔒 = HTTPS supported\n"
        "⚠️ = HTTP only\n"
        "🔑 = Requires API key / OAuth\n"
        "🆓 = No auth needed\n"
        "✅ CORS = Browser-friendly\n\n"
        "*Data Source:*\n"
        "All APIs sourced from [public-apis/public-apis](https://github.com/public-apis/public-apis) "
        "— the legendary open-source list with 1000+ entries.\n\n"
        "*Commands:*\n"
        "/categories — See all available categories\n"
        "/random — Get a random API suggestion\n"
        "/stats — Show data stats\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /categories."""
    cats = data_loader.get_categories()
    if not cats:
        await update.message.reply_text("⚠️ Categories not loaded yet. Try again in a moment.")
        return

    # Build category grid display
    cat_list = "\n".join(
        f"• `{cat}` ({count} APIs)" for cat, count in sorted(cats.items(), key=lambda x: -x[1])[:30]
    )

    msg = (
        f"📂 *Available Categories* ({len(cats)} total)\n\n"
        f"{cat_list}\n\n"
        f"_...and more! Just type any keyword to search._"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Random API", callback_data="random")]
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)


async def random_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /random."""
    api = data_loader.get_random_api()
    if not api:
        await update.message.reply_text("⚠️ No data loaded yet. Try /start first.")
        return

    msg = (
        "🎲 *Random API Discovery!*\n\n"
        + format_api_entry(api, 1)
        + f"\n📂 *Category:* `{api.get('Category', 'Unknown')}`"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Another Random", callback_data="random"),
         InlineKeyboardButton("📂 Categories", callback_data="categories")]
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats."""
    stats = data_loader.get_stats()
    msg = (
        "📊 *Bot Statistics*\n\n"
        f"🗂 Total APIs indexed: *{stats['total']}*\n"
        f"📂 Categories: *{stats['categories']}*\n"
        f"🔒 HTTPS APIs: *{stats['https_count']}*\n"
        f"🆓 No-auth APIs: *{stats['no_auth_count']}*\n"
        f"✅ CORS-friendly: *{stats['cors_count']}*\n\n"
        f"_Data from_ [public-apis/public-apis](https://github.com/public-apis/public-apis)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)


# ─── Message Handler ─────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user keyword search."""
    keyword = update.message.text.strip().lower()

    if not keyword or len(keyword) < 2:
        await update.message.reply_text(
            "🔍 Please send a keyword with at least 2 characters.\nExample: `ai`, `weather`, `crypto`",
            parse_mode="Markdown"
        )
        return

    if len(keyword) > 50:
        await update.message.reply_text("⚠️ Keyword too long. Keep it under 50 characters.")
        return

    # Show typing indicator
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    results = data_loader.search(keyword)

    if not results:
        suggestions = data_loader.get_suggestions(keyword)
        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n\n💡 *Did you mean?*\n" + "\n".join(f"• `{s}`" for s in suggestions)

        msg = (
            f"😔 *No APIs found for:* `{keyword}`\n\n"
            f"Try more general terms like:\n"
            f"`ai`, `weather`, `crypto`, `finance`, `music`, `games`, `books`"
            f"{suggestion_text}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Browse Categories", callback_data="categories"),
             InlineKeyboardButton("🎲 Random API", callback_data="random")]
        ])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
        return

    # Store results in context for pagination
    context.user_data[f"results_{keyword}"] = results

    msg = build_results_message(results, keyword, 0, len(results))
    keyboard = build_pagination_keyboard(keyword, 0, len(results))

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ─── Callback Query Handler ───────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "new_search":
        await query.message.reply_text(
            "🔍 *Send me a keyword to search!*\nExample: `ai`, `weather`, `crypto`",
            parse_mode="Markdown"
        )

    elif data == "categories":
        cats = data_loader.get_categories()
        cat_list = "\n".join(
            f"• `{cat}` ({count})" for cat, count in sorted(cats.items(), key=lambda x: -x[1])[:25]
        )
        await query.message.reply_text(
            f"📂 *Categories:*\n\n{cat_list}",
            parse_mode="Markdown"
        )

    elif data == "random":
        api = data_loader.get_random_api()
        if api:
            msg = "🎲 *Random API:*\n\n" + format_api_entry(api, 1)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 Another", callback_data="random")]
            ])
            await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True)

    elif data.startswith("page:"):
        _, keyword, page_str = data.split(":", 2)
        page = int(page_str)

        results = context.user_data.get(f"results_{keyword}")
        if not results:
            results = data_loader.search(keyword)
            context.user_data[f"results_{keyword}"] = results

        if not results:
            await query.message.reply_text(f"⚠️ Results expired. Search `{keyword}` again.")
            return

        msg = build_results_message(results, keyword, page, len(results))
        keyboard = build_pagination_keyboard(keyword, page, len(results))

        await query.message.edit_text(
            msg,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


# ─── Error Handler ────────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors gracefully."""
    logger.error(f"Update {update} caused error: {context.error}")
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Something went sideways. Try again in a moment!\n"
            "If it keeps happening, try /start to reset."
        )


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    """Start the bot."""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ Set TELEGRAM_BOT_TOKEN env variable first!")
        return

    logger.info("📥 Loading API data...")
    data_loader.load()
    logger.info(f"✅ Loaded {data_loader.get_stats()['total']} APIs")

    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("categories", categories_command))
    app.add_handler(CommandHandler("random", random_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    logger.info("🚀 Bot is live! Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
