"""
pinkmen.py v2.0 — Next-Level API Finder Bot
Phase 1: Smart multi-layer ranked search + synonym expansion
Phase 2: Rich UI — inline buttons, cards, filters, detail views
Phase 3: Full command suite — feels like a real product
"""

import os
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from data_loader import APIDataLoader

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
RESULTS_PER_PAGE = 5

# ── Boot up data loader ───────────────────────────────────────────────────────
loader = APIDataLoader()


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — UI BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def badge(api: dict) -> str:
    """Generate compact badge line for an API."""
    https  = "🔒" if api.get("HTTPS") else "⚠️"
    auth   = f"🔑 `{api['Auth']}`" if api.get("Auth") else "🆓 Free"
    cors   = " · ✅ CORS" if api.get("Cors") == "yes" else ""
    return f"{https} {auth}{cors}"


def api_card(api: dict, index: int) -> str:
    """Render a single API as a rich Telegram message card."""
    return (
        f"*{index}. {api['Name']}*\n"
        f"_{api['Description']}_\n"
        f"{badge(api)}\n"
        f"📂 `{api['Category']}`\n"
        f"🔗 [Open API Docs]({api['Link']})\n"
    )


def results_header(query: str, total: int, page: int, total_pages: int,
                   filters_on: list) -> str:
    filter_tag = ""
    if filters_on:
        filter_tag = "  🔽 " + " + ".join(filters_on)
    return (
        f"🔍 *\"{query}\"*{filter_tag}\n"
        f"📦 *{total} APIs found* · Page {page + 1}/{total_pages}\n"
        f"{'━' * 28}\n\n"
    )


def build_results_keyboard(query: str, page: int, total: int,
                            filters_str: str = "") -> InlineKeyboardMarkup:
    """Rich paginated keyboard with filter toggles."""
    total_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    rows = []

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"pg:{query}:{page-1}:{filters_str}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"pg:{query}:{page+1}:{filters_str}"))
    if nav: rows.append(nav)

    # Filter toggle row
    f_parts = filters_str.split(",") if filters_str else []
    def tog(f): return ",".join(sorted((set(f_parts) - {f}) if f in f_parts else (set(f_parts) | {f})))

    rows.append([
        InlineKeyboardButton(
            ("✅" if "https" in f_parts else "🔒") + " HTTPS",
            callback_data=f"pg:{query}:0:{tog('https')}"
        ),
        InlineKeyboardButton(
            ("✅" if "free" in f_parts else "🆓") + " Free",
            callback_data=f"pg:{query}:0:{tog('free')}"
        ),
        InlineKeyboardButton(
            ("✅" if "cors" in f_parts else "🌐") + " CORS",
            callback_data=f"pg:{query}:0:{tog('cors')}"
        ),
    ])

    # Quick actions row
    rows.append([
        InlineKeyboardButton("🎲 Random", callback_data="random"),
        InlineKeyboardButton("📂 Categories", callback_data="cats:0"),
        InlineKeyboardButton("🔄 New Search", callback_data="newsearch"),
    ])

    return InlineKeyboardMarkup(rows)


def build_categories_keyboard(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Paginated categories browser."""
    cats = loader.get_categories()
    cat_list = list(cats.items())  # [(name, count), ...]
    per_page = 12
    total_pages = max(1, (len(cat_list) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    page_cats = cat_list[start:start + per_page]

    text = f"📂 *API Categories* · Page {page+1}/{total_pages}\n\n"
    text += "_Tap any category to browse its APIs:_\n\n"

    # Category buttons grid (2 per row)
    rows = []
    for i in range(0, len(page_cats), 2):
        row = []
        for cat, count in page_cats[i:i+2]:
            row.append(InlineKeyboardButton(
                f"{cat} ({count})",
                callback_data=f"cat:{cat}:0"
            ))
        rows.append(row)

    # Nav row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"cats:{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"cats:{page+1}"))
    if nav: rows.append(nav)

    rows.append([
        InlineKeyboardButton("🎲 Random API", callback_data="random"),
        InlineKeyboardButton("🏠 Home", callback_data="home"),
    ])

    return text, InlineKeyboardMarkup(rows)


def build_category_results(cat_name: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Show all APIs in a specific category with pagination."""
    results = loader.search(cat_name, max_results=100)
    if not results:
        results = [a for a in loader._apis if a["Category"].lower() == cat_name.lower()]

    total = len(results)
    total_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * RESULTS_PER_PAGE
    page_apis = results[start:start + RESULTS_PER_PAGE]

    text = (
        f"📂 *{cat_name}*\n"
        f"📦 *{total} APIs* · Page {page+1}/{total_pages}\n"
        f"{'━' * 28}\n\n"
    ) + "\n".join(api_card(a, start+i+1) for i, a in enumerate(page_apis))

    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"cat:{cat_name}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"cat:{cat_name}:{page+1}"))
    if nav: rows.append(nav)
    rows.append([
        InlineKeyboardButton("◀ All Categories", callback_data="cats:0"),
        InlineKeyboardButton("🎲 Random", callback_data=f"rcat:{cat_name}"),
    ])

    return text, InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"✨ *Hey {user.first_name}!* Welcome to *API Finder Bot v2*\n\n"
        f"I search through *{loader.get_stats()['total']}+ public APIs* instantly.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*🔥 Just send any keyword:*\n"
        f"`ai` · `weather` · `crypto` · `music` · `games`\n\n"
        f"*📋 Commands:*\n"
        f"/search `<keyword>` — Search for APIs\n"
        f"/categories — Browse all categories\n"
        f"/random — Discover a random API\n"
        f"/trending — 🔥 Trending APIs right now\n"
        f"/filter — Search with filters\n"
        f"/stats — Bot statistics\n"
        f"/help — Full help guide\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Go ahead — send a keyword!*"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 Categories", callback_data="cats:0"),
            InlineKeyboardButton("🎲 Random API", callback_data="random"),
        ],
        [
            InlineKeyboardButton("🔥 Trending", callback_data="trending"),
        ]
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *API Finder Bot v2 — Help Guide*\n\n"
        "*🔍 How to Search:*\n"
        "• Just type any keyword: `music`, `finance`, `blockchain`\n"
        "• Use /search command: `/search machine learning`\n"
        "• Use filters to narrow results (HTTPS / Free / CORS)\n\n"
        "*🎯 Commands:*\n"
        "/search `keyword` — Search APIs\n"
        "/categories — All 40+ categories\n"
        "/random — Surprise me!\n"
        "/trending — Hot categories\n"
        "/filter `keyword` — Search with filters\n"
        "/stats — Data breakdown\n\n"
        "*🏷 Badge Guide:*\n"
        "🔒 = HTTPS  ·  ⚠️ = HTTP only\n"
        "🆓 = No auth needed  ·  🔑 = Needs API key\n"
        "✅ CORS = Works from browser\n\n"
        "*📦 Data Source:*\n"
        "[public-apis/public-apis](https://github.com/public-apis/public-apis) — "
        "community-maintained, 1400+ APIs\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /search <keyword>"""
    if not ctx.args:
        await update.message.reply_text(
            "🔍 Usage: `/search <keyword>`\nExample: `/search machine learning`",
            parse_mode="Markdown"
        )
        return
    query = " ".join(ctx.args).strip()
    await _run_search(update, ctx, query, page=0, filters_str="")


async def cmd_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text, kb = build_categories_keyboard(0)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cmd_random(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    api = loader.get_random_api()
    if not api:
        await update.message.reply_text("⚠️ No data yet. Try again in a moment.")
        return
    text = "🎲 *Random API Discovery!*\n\n" + api_card(api, 1)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Another Random", callback_data="random"),
            InlineKeyboardButton(f"📂 {api['Category']}", callback_data=f"cat:{api['Category']}:0"),
        ],
        [InlineKeyboardButton("📋 All Categories", callback_data="cats:0")]
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)


async def cmd_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    apis = loader.get_trending(8)
    text = "🔥 *Trending APIs*\n_Curated picks from popular categories:_\n\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "\n".join(api_card(a, i+1) for i, a in enumerate(apis))
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="trending"),
            InlineKeyboardButton("📂 Categories", callback_data="cats:0"),
        ]
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)


async def cmd_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Open filter picker for a keyword."""
    if not ctx.args:
        await update.message.reply_text(
            "🔽 Usage: `/filter <keyword>`\nExample: `/filter weather`\n\n"
            "Then use the filter buttons to narrow by HTTPS / Free / CORS.",
            parse_mode="Markdown"
        )
        return
    query = " ".join(ctx.args).strip()
    await _run_search(update, ctx, query, page=0, filters_str="")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = loader.get_stats()
    text = (
        "📊 *API Finder Bot — Stats*\n\n"
        f"🗂 Total APIs indexed: *{s['total']}*\n"
        f"📂 Categories: *{s['categories']}*\n"
        f"🔒 HTTPS APIs: *{s['https_count']}* ({s['https_count']*100//max(s['total'],1)}%)\n"
        f"🆓 No-auth APIs: *{s['no_auth_count']}* ({s['no_auth_count']*100//max(s['total'],1)}%)\n"
        f"✅ CORS-friendly: *{s['cors_count']}* ({s['cors_count']*100//max(s['total'],1)}%)\n"
        f"🌟 Free & Secure: *{s['free_and_open']}*\n\n"
        f"_Source: [public-apis/public-apis](https://github.com/public-apis/public-apis)_"
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════════════════════
#  CORE SEARCH RUNNER
# ══════════════════════════════════════════════════════════════════════════════

async def _run_search(update_or_query, ctx, query: str, page: int, filters_str: str):
    """Central search + render function used by both messages and callbacks."""
    f_parts = [f for f in filters_str.split(",") if f] if filters_str else []

    results = loader.search(
        query,
        max_results=100,
        filter_https="https" in f_parts,
        filter_no_auth="free" in f_parts,
        filter_cors="cors" in f_parts,
    )

    # Store in user_data for pagination
    if hasattr(ctx, "user_data"):
        ctx.user_data[f"r:{query}:{filters_str}"] = results

    if not results:
        suggestions = loader.get_suggestions(query)
        sug_text = ""
        if suggestions:
            sug_text = "\n\n💡 *Similar categories:*\n" + "\n".join(f"• `{s}`" for s in suggestions)
        no_result_text = (
            f"😔 *No APIs found for* `{query}`"
            + (f"\n_Active filters: {', '.join(f_parts)}_" if f_parts else "")
            + f"\n\nTry: `ai`, `weather`, `crypto`, `music`, `games`, `finance`"
            + sug_text
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📂 Browse Categories", callback_data="cats:0"),
                InlineKeyboardButton("🎲 Random", callback_data="random"),
            ]
        ])
        if hasattr(update_or_query, "message"):
            await update_or_query.message.reply_text(no_result_text, parse_mode="Markdown", reply_markup=kb)
        else:
            await update_or_query.edit_message_text(no_result_text, parse_mode="Markdown", reply_markup=kb)
        return

    total = len(results)
    total_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * RESULTS_PER_PAGE
    page_apis = results[start:start + RESULTS_PER_PAGE]

    filter_labels = {"https": "HTTPS only", "free": "Free only", "cors": "CORS friendly"}
    active_filters = [filter_labels[f] for f in f_parts if f in filter_labels]

    text = results_header(query, total, page, total_pages, active_filters)
    text += "\n".join(api_card(a, start+i+1) for i, a in enumerate(page_apis))

    kb = build_results_keyboard(query, page, total, filters_str)

    if hasattr(update_or_query, "message"):
        await update_or_query.message.reply_text(
            text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True
        )
    else:
        await update_or_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True
        )


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGE HANDLER — keyword search from plain text
# ══════════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("🔍 Send a keyword with at least 2 characters.")
        return
    if len(text) > 60:
        await update.message.reply_text("⚠️ Too long — keep it under 60 characters.")
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    await _run_search(update, ctx, text.lower(), page=0, filters_str="")


# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER — all inline button interactions
# ══════════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # ── No-op (page counter display button) ──
    if data == "noop":
        return

    # ── New search prompt ──
    if data == "newsearch":
        await q.message.reply_text(
            "🔍 *Send me a keyword!*\nExample: `ai`, `crypto`, `weather`",
            parse_mode="Markdown"
        )

    # ── Home / start ──
    elif data == "home":
        user = update.effective_user
        text = (
            f"🏠 *Back to Home*\n\n"
            f"Send any keyword to search {loader.get_stats()['total']}+ APIs.\n"
            f"Or use the buttons below:"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📂 Categories", callback_data="cats:0"),
                InlineKeyboardButton("🎲 Random", callback_data="random"),
            ],
            [InlineKeyboardButton("🔥 Trending", callback_data="trending")]
        ])
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    # ── Paginated search results ──
    elif data.startswith("pg:"):
        # Format: pg:query:page:filters
        parts = data.split(":", 3)
        query = parts[1]
        page = int(parts[2])
        filters_str = parts[3] if len(parts) > 3 else ""
        await _run_search(q, ctx, query, page, filters_str)

    # ── Category browser (paginated list) ──
    elif data.startswith("cats:"):
        page = int(data.split(":")[1])
        text, kb = build_categories_keyboard(page)
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

    # ── Category drill-down (show APIs in category) ──
    elif data.startswith("cat:"):
        parts = data.split(":", 2)
        cat_name = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        text, kb = build_category_results(cat_name, page)
        await q.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)

    # ── Random API ──
    elif data == "random":
        api = loader.get_random_api()
        if api:
            text = "🎲 *Random API!*\n\n" + api_card(api, 1)
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🎲 Another", callback_data="random"),
                    InlineKeyboardButton(f"📂 {api['Category']}", callback_data=f"cat:{api['Category']}:0"),
                ]
            ])
            await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)

    # ── Random from specific category ──
    elif data.startswith("rcat:"):
        cat = data.split(":", 1)[1]
        api = loader.get_random_api(category=cat)
        if api:
            text = f"🎲 *Random from {cat}!*\n\n" + api_card(api, 1)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 Another from this category", callback_data=f"rcat:{cat}")]
            ])
            await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)

    # ── Trending ──
    elif data == "trending":
        apis = loader.get_trending(8)
        text = "🔥 *Trending APIs*\n_From popular categories:_\n\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += "\n".join(api_card(a, i+1) for i, a in enumerate(apis))
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="trending"),
                InlineKeyboardButton("📂 Categories", callback_data="cats:0"),
            ]
        ])
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def handle_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {ctx.error}")
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Something went wrong. Try again!\nUse /start to reset."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ Set TELEGRAM_BOT_TOKEN env variable!")
        return

    logger.info("📥 Loading API data...")
    loader.load()
    stats = loader.get_stats()
    logger.info(f"✅ {stats['total']} APIs · {stats['categories']} categories · ready!")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("search",     cmd_search))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("random",     cmd_random))
    app.add_handler(CommandHandler("trending",   cmd_trending))
    app.add_handler(CommandHandler("filter",     cmd_filter))
    app.add_handler(CommandHandler("stats",      cmd_stats))

    # Messages + Callbacks
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(handle_error)

    logger.info("🚀 Bot v2 is LIVE — polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
