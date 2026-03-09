#!/usr/bin/env python3
import asyncio
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

AI_SERVER_DIR = Path(os.environ.get("AI_SERVER_DIR", Path.home() / "AI-Server"))

# Paths for imports
sys.path.insert(0, str(AI_SERVER_DIR))
sys.path.insert(0, str(AI_SERVER_DIR / "telegram-bob-remote"))

from core import (
    log as _log,
    get_ids as _get_ids,
    load_allowed_ids as _load_allowed_ids,
    save_allowed_ids as _save_allowed_ids,
    chat_allowed as _chat_allowed,
    unauthorized_message as _unauthorized_message,
    tail_log as _tail,
    run_bob as _run_bob_core,
    LOG_FILE,
)

RUN_BOB = AI_SERVER_DIR / "RUN_BOB.command"  # for status only
NOTES_READER = AI_SERVER_DIR / "tools" / "notes_reader.py"

# Event emitter (gracefully fails if Mission Control not running)
try:
    from mission_control import emit, message_received, message_sent, tool_called, tool_result
    MISSION_CONTROL = True
except ImportError:
    MISSION_CONTROL = False
    def emit(*args, **kwargs): pass
    def message_received(*args, **kwargs): pass
    def message_sent(*args, **kwargs): pass
    def tool_called(*args, **kwargs): pass
    def tool_result(*args, **kwargs): pass


def _run_bob(args: str) -> tuple[int, str]:
    tool_called("bob", f"orchestrator {args.split()[0] if args else 'unknown'}")
    code, out = _run_bob_core(args)
    tool_result("bob", "orchestrator", code == 0, out[:100] if out else None)
    return code, out


def get_main_menu_keyboard():
    """Create main menu inline keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📧 Email & Bids", callback_data="menu_email"),
            InlineKeyboardButton("🧠 Knowledge", callback_data="menu_knowledge"),
        ],
        [
            InlineKeyboardButton("📄 Proposals", callback_data="menu_proposals"),
            InlineKeyboardButton("💰 Invoices", callback_data="menu_invoices"),
        ],
        [
            InlineKeyboardButton("🏭 Dealers", callback_data="menu_dealers"),
            InlineKeyboardButton("💳 Subscriptions", callback_data="menu_subs"),
        ],
        [
            InlineKeyboardButton("📈 Investing", callback_data="menu_invest"),
            InlineKeyboardButton("🎯 Leads", callback_data="menu_leads"),
        ],
        [
            InlineKeyboardButton("🔍 SEO", callback_data="menu_seo"),
            InlineKeyboardButton("📊 System", callback_data="menu_system"),
        ],
        [
            InlineKeyboardButton("💰 Revenue", callback_data="action_revenue"),
            InlineKeyboardButton("☀️ Briefing", callback_data="action_morning"),
        ],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, user_id = _get_ids(update)
    allowed = _load_allowed_ids()

    _log(f"/start from chat_id={chat_id} user_id={user_id} allowed_count={len(allowed)}")
    message_received("bob", "/start command", sender=user_id)

    if not allowed and (chat_id or user_id):
        new_allowed = set()
        if chat_id:
            new_allowed.add(chat_id)
        if user_id:
            new_allowed.add(user_id)
        _save_allowed_ids(new_allowed)
        await update.message.reply_text(
            "Auto-locked bot access to this chat/user.\n"
            f"Saved IDs: {', '.join(sorted(new_allowed))}\n"
            f"State file: {STATE_FILE}"
        )

    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return

    await update.message.reply_text(
        "🎼 *Symphony AI Control Center*\n\n"
        "Tap a category below to see options:",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the main menu: /menu"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text(
        "🎼 *Symphony AI Control Center*\n\n"
        "Tap a category below:",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses from inline keyboards."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Sub-menus
    if data == "menu_email":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📬 Check Inbox", callback_data="action_inbox")],
            [InlineKeyboardButton("🏗️ New Bids", callback_data="action_bids")],
            [InlineKeyboardButton("📋 All Bid Invitations", callback_data="action_bid_list")],
            [InlineKeyboardButton("🔍 Search Email", callback_data="prompt_email_search")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("📧 *Email & Bids*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_knowledge":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Research Query", callback_data="prompt_research")],
            [InlineKeyboardButton("📊 Cortex Stats", callback_data="action_cortex")],
            [InlineKeyboardButton("📚 Learning Status", callback_data="action_learning")],
            [InlineKeyboardButton("📰 News Digest", callback_data="action_news")],
            [InlineKeyboardButton("🎓 Learn Now", callback_data="action_learn_once")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("🧠 *Knowledge & Research*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_leads":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔨 Find Builders", callback_data="action_leads_builders")],
            [InlineKeyboardButton("🏘️ Find Realtors", callback_data="action_leads_realtors")],
            [InlineKeyboardButton("🏠 Luxury Listings", callback_data="action_leads_listings")],
            [InlineKeyboardButton("🏢 Property Managers", callback_data="action_leads_property")],
            [InlineKeyboardButton("📋 Recent Leads", callback_data="action_leads_recent")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("🎯 *Lead Generation*\n\nFind new business opportunities:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_proposals":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ New Quote", callback_data="prompt_quote")],
            [InlineKeyboardButton("📋 List All Quotes", callback_data="action_quotes")],
            [InlineKeyboardButton("👁️ View Quote", callback_data="prompt_quote_show")],
            [InlineKeyboardButton("📄 Generate PDF", callback_data="prompt_generate")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("📄 *Proposals*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_invoices":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 List Invoices", callback_data="action_invoices")],
            [InlineKeyboardButton("➕ Create from Proposal", callback_data="prompt_invoice_from")],
            [InlineKeyboardButton("💵 Record Payment", callback_data="prompt_payment")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("💰 *Invoices*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_dealers":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 List Vendor Forms", callback_data="action_dealers")],
            [InlineKeyboardButton("📝 Fill Application", callback_data="prompt_dealer_apply")],
            [InlineKeyboardButton("👁️ Preview Company Data", callback_data="action_dealer_preview")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("🏭 *Dealer Applications*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_subs":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 View Subscriptions", callback_data="action_subs")],
            [InlineKeyboardButton("➕ Add Subscription", callback_data="prompt_sub_add")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("💳 *Subscriptions*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_invest":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌅 Daily Market Scan", callback_data="action_daily_scan")],
            [InlineKeyboardButton("💰 Portfolio Status", callback_data="action_portfolio")],
            [InlineKeyboardButton("🎰 Polymarket Scan", callback_data="action_polymarket")],
            [InlineKeyboardButton("📈 Trending Opps", callback_data="action_trending")],
            [InlineKeyboardButton("🔍 Research Topic", callback_data="prompt_invest_research")],
            [InlineKeyboardButton("📊 Perplexity Usage", callback_data="action_pplx_usage")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("📈 *Investing & Markets*\n\n🎯 Goal: $3,649 for Beatrice Upgrade\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_system":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Usage Monitor", callback_data="action_usage")],
            [InlineKeyboardButton("❤️ Health Check", callback_data="action_status")],
            [InlineKeyboardButton("🌐 Website Status", callback_data="action_website")],
            [InlineKeyboardButton("☀️ Morning Checklist", callback_data="action_morning")],
            [InlineKeyboardButton("📋 Daily Briefing", callback_data="action_briefing")],
            [InlineKeyboardButton("📝 Pending Tasks", callback_data="action_tasks")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("📊 *System Status*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_seo":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Keywords", callback_data="action_seo_keywords"),
             InlineKeyboardButton("📝 Blog Post", callback_data="action_seo_generate")],
            [InlineKeyboardButton("📍 Local SEO", callback_data="action_seo_local"),
             InlineKeyboardButton("🔗 Backlinks", callback_data="action_seo_backlinks")],
            [InlineKeyboardButton("📚 Drafts", callback_data="action_seo_drafts"),
             InlineKeyboardButton("🏷️ Meta Tags", callback_data="action_seo_meta")],
            [InlineKeyboardButton("📖 Story Tweet", callback_data="action_social_story"),
             InlineKeyboardButton("💡 Tip Tweet", callback_data="action_social_tip")],
            [InlineKeyboardButton("🎬 Video Prompt", callback_data="action_social_video"),
             InlineKeyboardButton("📅 Full Week", callback_data="action_social_week")],
            [InlineKeyboardButton("🐦 X Queue", callback_data="action_x_queue"),
             InlineKeyboardButton("🐦 Post Next", callback_data="action_x_post")],
            [InlineKeyboardButton("📊 X Usage", callback_data="action_x_usage")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text(
            "🎯 *SEO & Social — @symphonysmart*\n\n"
            "📝 Blog & SEO\n"
            "📖💡🎬 Social content (stories, tips, video)\n"
            "🐦 X posting & queue\n\n"
            "Select an action:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif data == "menu_auto":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Browser Task", callback_data="prompt_browse")],
            [InlineKeyboardButton("🔧 D-Tools Action", callback_data="prompt_dtools")],
            [InlineKeyboardButton("« Back", callback_data="menu_main")],
        ])
        await query.edit_message_text("🤖 *Automation*\n\nSelect an action:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "menu_main":
        await query.edit_message_text(
            "🎼 *Symphony AI Control Center*\n\n"
            "Tap a category below:",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
    
    # Direct actions (no input needed)
    elif data == "action_inbox":
        await query.edit_message_text("📬 Checking inbox...")
        rc, out = _run_bob("inbox --count 5")
        await query.message.reply_text(out[:3900] if out else "No results", reply_markup=get_back_keyboard("menu_email"))
    
    elif data == "action_bids":
        await query.edit_message_text("🏗️ Checking bids...")
        rc, out = _run_bob("bid_check")
        await query.message.reply_text(out[:3900] if out else "No new bids", reply_markup=get_back_keyboard("menu_email"))
    
    elif data == "action_bid_list":
        await query.edit_message_text("📋 Loading bid list...")
        rc, out = _run_bob("bid_list")
        await query.message.reply_text(out[:3900] if out else "No bids found", reply_markup=get_back_keyboard("menu_email"))
    
    elif data == "action_cortex":
        await query.edit_message_text("📊 Getting cortex stats...")
        cmd = ["bash", str(AI_SERVER_DIR / "tools" / "cortex_status.sh")]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "No stats available"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_knowledge"))
    
    elif data == "action_learning":
        await query.edit_message_text("📚 Getting learning status...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), "--status"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "No learning data"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_knowledge"))
    
    elif data == "action_news":
        await query.edit_message_text("📰 Fetching latest news...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), 
               "--query", "technology business smart home AI news today", "--category", "news"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        # Read latest news
        news_dir = AI_SERVER_DIR / "knowledge" / "news"
        if news_dir.exists():
            files = sorted(news_dir.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
            if files:
                content = files[0].read_text()[:3500]
                await query.message.reply_text(content, reply_markup=get_back_keyboard("menu_knowledge"))
                return
        await query.message.reply_text(p.stdout[:3500] if p.stdout else "News fetch complete", reply_markup=get_back_keyboard("menu_knowledge"))
    
    elif data == "action_learn_once":
        await query.edit_message_text("🎓 Learning something new...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), "--once"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        out = p.stdout or p.stderr or "Learning complete"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_knowledge"))
    
    # Lead generation actions
    elif data == "action_leads_builders":
        await query.edit_message_text("🔨 Scanning for builder partnerships (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "lead_finder.py"), "--builders"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Scan failed"
        if "Symphony Smart Homes" in out:
            out = out[out.find("🔨"):]  # Skip header
        await query.message.reply_text(out[:3900] if len(out) > 3900 else out, reply_markup=get_back_keyboard("menu_leads"))
    
    elif data == "action_leads_realtors":
        await query.edit_message_text("🏘️ Scanning for realtor partnerships (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "lead_finder.py"), "--realtors"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Scan failed"
        if "Symphony Smart Homes" in out:
            out = out[out.find("🏘️"):]
        await query.message.reply_text(out[:3900] if len(out) > 3900 else out, reply_markup=get_back_keyboard("menu_leads"))
    
    elif data == "action_leads_listings":
        await query.edit_message_text("🏠 Scanning luxury listings (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "lead_finder.py"), "--listings"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Scan failed"
        if "Symphony Smart Homes" in out:
            out = out[out.find("🏠"):]
        await query.message.reply_text(out[:3900] if len(out) > 3900 else out, reply_markup=get_back_keyboard("menu_leads"))
    
    elif data == "action_leads_property":
        await query.edit_message_text("🏢 Scanning property managers (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "lead_finder.py"), "--property-managers"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Scan failed"
        if "Symphony Smart Homes" in out:
            out = out[out.find("🏢"):]
        await query.message.reply_text(out[:3900] if len(out) > 3900 else out, reply_markup=get_back_keyboard("menu_leads"))
    
    elif data == "action_leads_recent":
        await query.edit_message_text("📋 Loading recent leads...")
        leads_dir = AI_SERVER_DIR / "knowledge" / "leads"
        if leads_dir.exists():
            files = sorted(leads_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
            if files:
                lines = ["📋 *Recent Lead Scans:*\n"]
                for f in files:
                    lines.append(f"• {f.stem}")
                out = "\n".join(lines)
            else:
                out = "No recent leads found. Run a scan first!"
        else:
            out = "Leads directory not found"
        await query.message.reply_text(out, parse_mode="Markdown", reply_markup=get_back_keyboard("menu_leads"))
    
    elif data == "action_quotes":
        await query.edit_message_text("📋 Loading quotes...")
        rc, out = _run_bob("list_proposals")
        await query.message.reply_text(out[:3900] if out else "No proposals found", reply_markup=get_back_keyboard("menu_proposals"))
    
    elif data == "action_invoices":
        await query.edit_message_text("📋 Loading invoices...")
        rc, out = _run_bob("list_invoices")
        await query.message.reply_text(out[:3900] if out else "No invoices found", reply_markup=get_back_keyboard("menu_invoices"))
    
    elif data == "action_dealers":
        await query.edit_message_text("📋 Loading dealer forms...")
        rc, out = _run_dealer_forms("--list")
        await query.message.reply_text(out[:3900] if out else "No vendors found", reply_markup=get_back_keyboard("menu_dealers"))
    
    elif data == "action_dealer_preview":
        await query.edit_message_text("👁️ Loading company profile...")
        rc, out = _run_dealer_forms("--preview")
        await query.message.reply_text(out[:3900] if out else "No profile found", reply_markup=get_back_keyboard("menu_dealers"))
    
    elif data == "action_subs":
        await query.edit_message_text("💳 Loading subscriptions...")
        cmd = ["python3", str(AI_SERVER_DIR / "integrations" / "telegram" / "subscription_audit.py"), "--dry"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = (p.stdout or "") + (p.stderr or "")
        await query.message.reply_text(out[:3900] if out.strip() else "No subscriptions", reply_markup=get_back_keyboard("menu_subs"))
    
    elif data == "action_usage":
        await query.edit_message_text("📊 Checking usage across all services...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "usage_monitor.py")]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Usage check failed"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="action_usage")],
            [InlineKeyboardButton("⚠️ Alerts Only", callback_data="action_usage_alerts")],
            [InlineKeyboardButton("« Back", callback_data="menu_system")],
        ])
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "action_usage_alerts":
        await query.edit_message_text("⚠️ Checking usage alerts...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "usage_monitor.py"), "--alerts"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Usage check failed"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Full Report", callback_data="action_usage")],
            [InlineKeyboardButton("« Back", callback_data="menu_system")],
        ])
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=keyboard)
    
    elif data == "action_status":
        await query.edit_message_text("❤️ Checking system health...")
        msg = (
            f"RUN_BOB: {'✅' if RUN_BOB.exists() else '❌'}\n"
            f"ORCHESTRATOR: {'✅' if ORCHESTRATOR.exists() else '❌'}\n"
            f"AI_SERVER_DIR: {AI_SERVER_DIR}\n"
        )
        await query.message.reply_text(msg, reply_markup=get_back_keyboard("menu_system"))
    
    elif data == "action_website":
        await query.edit_message_text("🌐 Checking website...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "website_monitor.py"), "--quick"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Check failed"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_system"))
    
    elif data == "action_morning":
        await query.edit_message_text("☀️ Running morning checklist...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "morning_checklist.py"), "--dry"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = (p.stdout or "") + (p.stderr or "")
        await query.message.reply_text(out[:3900] if out.strip() else "Checklist failed", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_system"))
    
    elif data == "action_briefing":
        await query.edit_message_text("📋 Generating briefing...")
        rc, out = _run_daily_digest("")
        await query.message.reply_text(out[:3900] if out else "Briefing failed", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_system"))
    
    elif data == "action_revenue":
        await query.edit_message_text("💰 Analyzing revenue opportunities...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "revenue_finder.py"), "--detailed"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = p.stdout or p.stderr or "Revenue analysis failed"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_main"))
    
    elif data == "action_tasks":
        await query.edit_message_text("📝 Loading tasks...")
        rc, out = _run_bob("list_tasks")
        await query.message.reply_text(out[:3900] if out else "No tasks", reply_markup=get_back_keyboard("menu_system"))
    
    # Investment actions
    elif data == "action_portfolio":
        await query.edit_message_text("💰 Loading portfolio...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "market_intel.py"), "--portfolio"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "No portfolio"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_invest"))
    
    elif data == "action_polymarket":
        await query.edit_message_text("🎰 Scanning Polymarket (this may take 30-60 seconds)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "market_intel.py"), "--polymarket"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        out = p.stdout or p.stderr or "Scan failed"
        # Split long messages
        if len(out) > 3800:
            await query.message.reply_text(out[:3800] + "...", reply_markup=get_back_keyboard("menu_invest"))
        else:
            await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_invest"))
    
    elif data == "action_trending":
        await query.edit_message_text("📈 Scanning trending opportunities...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "market_intel.py"), "--trending"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
        out = p.stdout or p.stderr or "Scan failed"
        if len(out) > 3800:
            await query.message.reply_text(out[:3800] + "...", reply_markup=get_back_keyboard("menu_invest"))
        else:
            await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_invest"))
    
    elif data == "action_pplx_usage":
        await query.edit_message_text("📊 Checking Perplexity usage...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "market_intel.py"), "--usage"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Usage check failed"
        await query.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_invest"))
    
    elif data == "action_daily_scan":
        await query.edit_message_text("🌅 Running full daily market scan (this takes ~30 seconds)...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "daily_market_scan.py")]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Scan failed"
        # Extract just the report part
        if "DAILY MARKET INTELLIGENCE" in out:
            out = out[out.find("DAILY MARKET INTELLIGENCE") - 5:]
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, parse_mode="Markdown", reply_markup=get_back_keyboard("menu_invest"))
    
    # SEO actions
    elif data == "action_seo_keywords":
        await query.edit_message_text("🔍 Researching Vail Valley smart home keywords...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "seo_manager.py"), "--keywords"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = p.stdout or p.stderr or "Keyword research failed"
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_seo_generate":
        await query.edit_message_text("📝 Generating SEO blog post (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "seo_content_generator.py"), "--generate"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Content generation failed"
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_seo_local":
        await query.edit_message_text("📍 Running local SEO audit (30-60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "seo_manager.py"), "--local"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = p.stdout or p.stderr or "Local SEO audit failed"
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_seo_backlinks":
        await query.edit_message_text("🔗 Finding backlink opportunities...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "seo_manager.py"), "--backlinks"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        out = p.stdout or p.stderr or "Backlink search failed"
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_seo_drafts":
        await query.edit_message_text("📚 Loading drafts...")
        drafts_dir = AI_SERVER_DIR / "knowledge" / "seo" / "drafts"
        if drafts_dir.exists():
            files = sorted(drafts_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
            if files:
                import json as _json
                lines = ["📚 *SEO Blog Drafts:*\n"]
                for f in files:
                    try:
                        d = _json.loads(f.read_text())
                        lines.append(f"📝 *{d.get('title', f.stem)}*")
                        lines.append(f"   🎯 Keyword: `{d.get('keyword', 'N/A')}`")
                        lines.append(f"   📅 {d.get('generated', 'unknown')[:10]}")
                        lines.append("")
                    except:
                        lines.append(f"• {f.stem}")
                out = "\n".join(lines)
            else:
                out = "No drafts yet. Generate one first!"
        else:
            out = "No drafts directory found"
        await query.message.reply_text(out, parse_mode="Markdown", reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_seo_meta":
        await query.edit_message_text("🏷️ Generating optimized meta tags...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "seo_manager.py"), "--meta"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Meta tag generation failed"
        if len(out) > 3800:
            out = out[:3700]
        await query.message.reply_text(f"```json\n{out}\n```", parse_mode="Markdown", reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_social_story":
        await query.edit_message_text("📖 Generating project story tweet...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "social_content.py"), "--story", "--queue"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Generation failed"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_social_tip":
        await query.edit_message_text("💡 Generating daily tip tweet...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "social_content.py"), "--tip", "--queue"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Generation failed"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_social_video":
        await query.edit_message_text("🎬 Generating video prompt + tweet...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "social_content.py"), "--video-prompt", "--queue"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Generation failed"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_social_week":
        await query.edit_message_text("📅 Generating full week of content (this takes ~60 sec)...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "social_content.py"), "--series", "--queue"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        out = p.stdout or p.stderr or "Generation failed"
        if len(out) > 3900:
            out = out[:3800] + "\n\n... [truncated]"
        await query.message.reply_text(out, reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_x_queue":
        await query.edit_message_text("🐦 Loading X post queue...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "x_poster.py"), "--queue"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=15)
        out = p.stdout or p.stderr or "Queue empty"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_x_post":
        await query.edit_message_text("🐦 Posting next tweet to @symphonysmart...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "x_poster.py"), "--auto"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Post failed"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    elif data == "action_x_usage":
        await query.edit_message_text("📊 Checking X usage...")
        cmd = ["python3", str(AI_SERVER_DIR / "tools" / "x_poster.py"), "--usage"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=15)
        out = p.stdout or p.stderr or "Usage check failed"
        await query.message.reply_text(out[:3900], reply_markup=get_back_keyboard("menu_seo"))

    # Prompts (need user input)
    elif data.startswith("prompt_"):
        prompts = {
            "prompt_email_search": ("🔍 Search Email", "Type: /email_search <query>"),
            "prompt_invest_research": ("🔍 Investment Research", "Type: /invest <topic>\n\nExamples:\n• /invest Bitcoin ETF flows\n• /invest Trump election odds\n• /invest AI chip stocks"),
            "prompt_research": ("🔍 Research", "Type: /research <your question>"),
            "prompt_troubleshoot": ("🔧 Troubleshoot", "Type: /troubleshoot <topic>"),
            "prompt_protocol": ("📡 Protocol", "Type: /protocol <name>"),
            "prompt_quote": ("➕ New Quote", "Type: /quote <ClientName> <description>"),
            "prompt_quote_show": ("👁️ View Quote", "Type: /quote_show <ID>"),
            "prompt_generate": ("📄 Generate", "Type: /generate <ID>"),
            "prompt_invoice_from": ("➕ Create Invoice", "Type: /invoice_from <ProposalID>"),
            "prompt_payment": ("💵 Record Payment", "Type: /payment <InvoiceID> <amount>"),
            "prompt_dealer_apply": ("📝 Dealer Apply", "Type: /dealer_apply <vendor_key or URL>"),
            "prompt_sub_add": ("➕ Add Sub", "Type: /sub_add"),
            "prompt_browse": ("🌐 Browser Task", "Type: /browse <task description>"),
            "prompt_dtools": ("🔧 D-Tools", "Type: /dtools_auto <action>"),
        }
        title, instruction = prompts.get(data, ("Input Needed", "Type the command manually"))
        await query.edit_message_text(
            f"*{title}*\n\n{instruction}",
            parse_mode="Markdown",
            reply_markup=get_back_keyboard("menu_main")
        )


def get_back_keyboard(back_to: str):
    """Create a keyboard with just a back button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=back_to)],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")],
    ])


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all available commands grouped by category."""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text(
        "🎼 *Symphony AI Commands*\n\n"
        
        "📧 *Email & Bids*\n"
        "/inbox - Check email\n"
        "/bids - BuildingConnected bids\n"
        "/bid\\_list - All invitations\n"
        "/bid\\_create ID - Create proposal\n"
        "/email\\_search query - Search\n\n"
        
        "🧠 *Knowledge & Research*\n"
        "/research query - Search Cortex + Perplexity\n"
        "/cortex - Knowledge base stats\n"
        "/cortex\\_build category - Build more\n"
        "/troubleshoot topic - Find guides\n"
        "/protocol name - Protocol info\n\n"
        
        "📄 *Proposals*\n"
        "/quote ClientName - Quick proposal\n"
        "/quotes - List all\n"
        "/quote\\_show ID - Details\n"
        "/add\\_item ID SKU QTY Room\n"
        "/generate ID - Create HTML\n\n"
        
        "💰 *Invoices*\n"
        "/invoices - List all\n"
        "/invoice\\_from ID - From proposal\n"
        "/payment ID amount\n\n"
        
        "💳 *Subscriptions*\n"
        "/subs - Monthly costs\n"
        "/sub\\_add - Add subscription\n\n"
        
        "🏭 *Dealer Applications*\n"
        "/dealers - List vendor forms\n"
        "/dealer\\_apply vendor - Fill application\n"
        "/dealer\\_preview - Preview company data\n\n"
        
        "📊 *System*\n"
        "/usage - Service usage monitor\n"
        "/status - Health check\n"
        "/briefing - Daily briefing\n"
        "/morning - Morning checklist\n"
        "/website - Website uptime check\n"
        "/tasks - Pending tasks\n\n"
        
        "🤖 *Automation*\n"
        "/browse task - Browser agent\n"
        "/dtools\\_auto action - D-Tools\n"
        "/claude task - Claude Code (parallel, with context)\n",
        parse_mode="Markdown"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, user_id = _get_ids(update)
    await update.message.reply_text(f"chat_id={chat_id}\nuser_id={user_id}")


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show usage across all metered services: /usage [--alerts]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    args = context.args or []
    alerts_only = "--alerts" in args or "-a" in args
    
    await update.message.reply_text("📊 Checking service usage...")
    
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "usage_monitor.py")]
    if alerts_only:
        cmd.append("--alerts")
    
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        out = p.stdout or p.stderr or "Usage check failed"
        await update.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    await update.message.reply_text(
        f"RUN_BOB: {'OK' if RUN_BOB.exists() else 'MISSING'}\n"
        f"ORCHESTRATOR: {'OK' if ORCHESTRATOR.exists() else 'MISSING'}\n"
        f"AI_SERVER_DIR: {AI_SERVER_DIR}\n"
        f"Log: {LOG_FILE}\n"
        f"State: {STATE_FILE}"
    )


async def tail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    await update.message.reply_text(_tail(LOG_FILE, 80)[:3900])


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    await update.message.reply_text("Starting: refresh_everything")
    rc, out = _run_bob("refresh_everything")
    msg = "Finished: refresh_everything\n"
    msg += f"Exit code: {rc}\n"
    if out:
        msg += "\nOutput (last 40 lines):\n" + "\n".join(out.splitlines()[-40:])
    msg += "\n\nOrchestrator log (last 40 lines):\n" + _tail(LOG_FILE, 40)
    await update.message.reply_text(msg[:3900])


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text("Usage: /analyze <project_name_part>")
        return
    project = " ".join(context.args).strip()
    await update.message.reply_text(f"Starting: analyze_project {project}")
    rc, out = _run_bob(f"analyze_project {shlex.quote(project)}")
    msg = f"Finished: analyze_project {project}\nExit code: {rc}\n"
    if out:
        msg += "\nOutput (last 60 lines):\n" + "\n".join(out.splitlines()[-60:])
    msg += "\n\nOrchestrator log (last 40 lines):\n" + _tail(LOG_FILE, 40)
    await update.message.reply_text(msg[:3900])


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text("Usage: /export <project_name_part>")
        return
    project = " ".join(context.args).strip()
    await update.message.reply_text(f"Starting: export_dtools {project}")
    rc, out = _run_bob(f"export_dtools {shlex.quote(project)}")
    msg = f"Finished: export_dtools {project}\nExit code: {rc}\n"
    if out:
        msg += "\nOutput (last 80 lines):\n" + "\n".join(out.splitlines()[-80:])
    await update.message.reply_text(msg[:3900])


def _run_notes(args: str) -> tuple[int, str]:
    """Run notes_reader.py with given arguments."""
    cmd = ["python3", str(NOTES_READER)] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def notes_folders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all Notes folders."""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_notes("--list-folders")
    await update.message.reply_text(out[:3900] if out else "No output")


async def notes_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search notes: /notes_search <query>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text("Usage: /notes_search <query>")
        return
    query = " ".join(context.args).strip()
    rc, out = _run_notes(f"--search {shlex.quote(query)}")
    await update.message.reply_text(out[:3900] if out else "No results")


async def notes_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get project summary from notes: /notes_project <project_name>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text("Usage: /notes_project <project_name>")
        return
    project = " ".join(context.args).strip()
    rc, out = _run_notes(f"--project-summary {shlex.quote(project)}")
    await update.message.reply_text(out[:3900] if out else "No results")


async def notes_read(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Read a specific note by ID: /notes_read <id>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text("Usage: /notes_read <note_id>")
        return
    note_id = context.args[0].strip()
    if not note_id.isdigit():
        await update.message.reply_text("Note ID must be a number")
        return
    rc, out = _run_notes(f"--read {note_id}")
    await update.message.reply_text(out[:3900] if out else "Note not found")


async def notes_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List notes in a folder: /notes_list <folder_name>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /notes_list <folder_name>\n"
            "Folders: Symphony SH, Previous Work, Work Cheats"
        )
        return
    folder = " ".join(context.args).strip()
    rc, out = _run_notes(f"--list {shlex.quote(folder)} --limit 25")
    await update.message.reply_text(out[:3900] if out else "No notes found")


def _run_knowledge_query(args: str) -> tuple[int, str]:
    """Run knowledge_query.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "knowledge_query.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def protocol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Query protocol info: /protocol <name>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /protocol <name>\n"
            "Examples: mDNS, ZigBee, Clear Connect, ONVIF, SSDP"
        )
        return
    query = " ".join(context.args).strip()
    rc, out = _run_knowledge_query(f"protocol {shlex.quote(query)}")
    await update.message.reply_text(out[:3900] if out else "No protocol found")


def _run_notes_sync(args: str) -> tuple[int, str]:
    """Run notes_sync.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "notes_sync.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def learning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List learning notes/courses: /learning"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_notes_sync("--list-courses")
    await update.message.reply_text(out[:3900] if out else "No courses found")


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List ideas from My Stuff: /ideas"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_notes_sync("--list-ideas")
    await update.message.reply_text(out[:3900] if out else "No ideas found")


async def sync_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sync notes to knowledge base: /sync_notes [photos|learning|ideas|all]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    sync_type = context.args[0].lower() if context.args else "all"
    
    if sync_type == "photos":
        await update.message.reply_text("📸 Syncing photos by project...")
        rc, out = _run_notes_sync("--sync-photos")
    elif sync_type == "learning":
        await update.message.reply_text("📚 Syncing learning notes...")
        rc, out = _run_notes_sync("--sync-learning")
    elif sync_type == "ideas":
        await update.message.reply_text("💡 Syncing ideas...")
        rc, out = _run_notes_sync("--sync-ideas")
    else:
        await update.message.reply_text("🔄 Syncing all notes...")
        rc, out = _run_notes_sync("--sync-all")
    
    await update.message.reply_text(out[:3900] if out else "Sync complete")


def _run_notes_watcher(args: str) -> tuple[int, str]:
    """Run notes_watcher.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "notes_watcher.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def watch_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check for new notes and auto-categorize: /watch_notes"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🔍 Checking for new notes...")
    rc, out = _run_notes_watcher("--check")
    await update.message.reply_text(out[:3900] if out else "No changes found")


async def watch_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show notes watcher status: /watch_status"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_notes_watcher("--status")
    await update.message.reply_text(out[:3900] if out else "No status available")


async def troubleshoot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Find troubleshooting guides: /troubleshoot <product or issue>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /troubleshoot <product or issue>\n"
            "Examples:\n"
            "  /troubleshoot Sonos\n"
            "  /troubleshoot RTSP\n"
            "  /troubleshoot mDNS\n"
            "  /troubleshoot Lutron"
        )
        return
    query = " ".join(context.args).strip()
    rc, out = _run_knowledge_query(f"troubleshoot {shlex.quote(query)}")
    await update.message.reply_text(out[:3900] if out else "No troubleshooting info found")


def _run_task_board(args: str) -> tuple[int, str]:
    """Run task_board.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "task_board.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending tasks: /tasks"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_task_board("list --status pending --limit 15")
    await update.message.reply_text(out[:3900] if out else "No pending tasks")


async def task_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a task: /task_add <title> [--type research|documentation|troubleshooting] [--priority high|medium|low]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /task_add <title>\n"
            "Options: --type, --priority\n\n"
            "Example: /task_add Research EA-5 manual --type research --priority high"
        )
        return
    args = " ".join(context.args)
    rc, out = _run_task_board(f"add {args}")
    await update.message.reply_text(out[:3900] if out else "Task created")


async def task_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Task board status: /task_status"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_task_board("status")
    await update.message.reply_text(out[:3900] if out else "No status")


async def task_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get work report: /task_report [hours]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    hours = context.args[0] if context.args else "2"
    rc, out = _run_task_board(f"report --hours {hours}")
    await update.message.reply_text(out[:3900] if out else "No report available")


def _run_notes_analyzer(args: str) -> tuple[int, str]:
    """Run notes_analyzer.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "notes_analyzer.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def notes_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show notes needing review: /notes_review"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_notes_analyzer("--review")
    await update.message.reply_text(out[:3900] if out else "No items to review", parse_mode="Markdown")


async def notes_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve notes by number: /approve 1,3,5"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /approve 1,3,5\n"
            "Send the numbers of items to approve.\n"
            "Items not approved will be marked 'maybe later'."
        )
        return
    numbers = ",".join(context.args)
    rc, out = _run_notes_analyzer(f"--approve {numbers}")
    
    # Auto-defer remaining items not approved
    if "items still need review" in out:
        await update.message.reply_text(out[:3900])
        await update.message.reply_text(
            "💡 Reply /defer to mark remaining items as 'maybe later'\n"
            "Or /notes_review to see what's left"
        )
    else:
        await update.message.reply_text(out[:3900] if out else "Approved")


async def notes_defer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Defer remaining items to 'maybe later': /defer [numbers or all]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if context.args:
        numbers = ",".join(context.args)
        rc, out = _run_notes_analyzer(f"--defer {numbers}")
    else:
        rc, out = _run_notes_analyzer("--defer all")
    
    await update.message.reply_text(out[:3900] if out else "Deferred")


async def notes_analysis_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show notes analysis status: /notes_status"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    rc, out = _run_notes_analyzer("--status")
    await update.message.reply_text(out[:3900] if out else "No analysis yet", parse_mode="Markdown")


def _run_proposal_generator(args: str) -> tuple[int, str]:
    """Run proposal_generator.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "proposal_generator.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_incoming_processor(args: str) -> tuple[int, str]:
    """Run incoming_task_processor.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "incoming_task_processor.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_polymarket(args: str) -> tuple[int, str]:
    """Run polymarket_client.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "integrations" / "polymarket" / "polymarket_client.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_poly_signals(args: str) -> tuple[int, str]:
    """Run polymarket_signals.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "integrations" / "polymarket" / "polymarket_signals.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_alpaca(args: str) -> tuple[int, str]:
    """Run alpaca_trader.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "trading" / "alpaca_trader.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_trading_dashboard(args: str) -> tuple[int, str]:
    """Run trading_dashboard.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "trading" / "trading_dashboard.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_strategy_engine(args: str) -> tuple[int, str]:
    """Run strategy_engine.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "trading" / "strategy_engine.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_risk_manager(args: str) -> tuple[int, str]:
    """Run risk_manager.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "trading" / "risk_manager.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_backtest(args: str) -> tuple[int, str]:
    """Run backtest.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "trading" / "backtest.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_proposal_agent(args: str) -> tuple[int, str]:
    """Run proposal_agent.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "agents" / "proposal_agent.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_dtools_agent(args: str) -> tuple[int, str]:
    """Run dtools_browser_agent.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "agents" / "dtools_browser_agent.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=180)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def proposal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a proposal: /proposal <description>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /proposal <description>\n\n"
            "Example:\n"
            "/proposal 5000sqft condo, hybrid lighting, shades, Araknis wifi multi-gig, Control4"
        )
        return
    
    description = " ".join(context.args)
    await update.message.reply_text(f"🔨 Generating proposal for:\n_{description}_", parse_mode="Markdown")
    
    rc, out = _run_proposal_generator(f'"{description}" --telegram --save')
    await update.message.reply_text(out[:3900] if out else "Error generating proposal", parse_mode="Markdown")


async def incoming_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check and process Incoming Tasks: /incoming"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📥 Checking Incoming Tasks...")
    rc, out = _run_incoming_processor("--check")
    await update.message.reply_text(out[:3900] if out else "No tasks found", parse_mode="Markdown")


async def incoming_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show Incoming Tasks status: /incoming_status"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_incoming_processor("--status")
    await update.message.reply_text(out[:3900] if out else "No status available")


async def poly_trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show trending Polymarket markets: /poly"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_polymarket("--trending")
    await update.message.reply_text(out[:3900] if out else "Error fetching markets", parse_mode="Markdown")


async def poly_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search Polymarket: /poly_search <query>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /poly_search <query>\nExample: /poly_search Trump")
        return
    
    query = " ".join(context.args)
    rc, out = _run_polymarket(f'--search "{query}"')
    await update.message.reply_text(out[:3900] if out else "No results", parse_mode="Markdown")


async def poly_arb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Find Polymarket arbitrage opportunities: /poly_arb"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🔍 Scanning for arbitrage opportunities...")
    rc, out = _run_polymarket("--arbitrage")
    await update.message.reply_text(out[:3900] if out else "No arbitrage found", parse_mode="Markdown")


async def poly_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Full Polymarket signal scan: /poly_signals"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📊 Running full signal scan...")
    rc, out = _run_poly_signals("--scan")
    await update.message.reply_text(out[:3900] if out else "Error running scan")


async def poly_expiring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Markets expiring soon: /poly_expiring"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_poly_signals("--expiring")
    await update.message.reply_text(out[:3900] if out else "No expiring markets", parse_mode="Markdown")


async def trading_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check Alpaca paper trading status: /trading"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_alpaca("--status")
    await update.message.reply_text(out[:3900] if out else "Error fetching status")


async def trading_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check current stock positions: /positions"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_alpaca("--positions")
    await update.message.reply_text(out[:3900] if out else "No positions")


async def trading_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Full trading dashboard: /dash"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📊 Loading dashboard...")
    rc, out = _run_trading_dashboard("--overview --telegram")
    await update.message.reply_text(out[:3900] if out else "Error loading dashboard", parse_mode="Markdown")


async def trading_opportunities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Best trading opportunities: /opps"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("⚡ Scanning for opportunities...")
    rc, out = _run_trading_dashboard("--opportunities")
    await update.message.reply_text(out[:3900] if out else "No opportunities found")


async def trading_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get trade recommendations: /recommend"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🎯 Generating recommendations...")
    rc, out = _run_strategy_engine("--recommend")
    await update.message.reply_text(out[:3900] if out else "No recommendations")


async def trading_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check portfolio risk: /risk"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_risk_manager("--check")
    await update.message.reply_text(out[:3900] if out else "Error checking risk")


async def trading_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Calculate position size: /size SPY 500"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /size SYMBOL RISK_AMOUNT\nExample: /size SPY 500")
        return
    
    symbol = context.args[0].upper()
    risk = context.args[1]
    rc, out = _run_risk_manager(f"--size {symbol} {risk}")
    await update.message.reply_text(out[:3900] if out else "Error calculating size")


async def trading_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Backtest strategy: /backtest SPY 30"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    symbol = context.args[0].upper() if context.args else "SPY"
    days = context.args[1] if len(context.args) > 1 else "30"
    
    await update.message.reply_text(f"📊 Backtesting {symbol} ({days} days)...")
    rc, out = _run_backtest(f"--compare --symbol {symbol} --days {days}")
    await update.message.reply_text(out[:3900] if out else "Backtest failed")


async def proposal_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending proposals: /proposals"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_proposal_agent("--list")
    # Truncate to first 20 projects
    lines = out.split("\n")
    if len(lines) > 25:
        out = "\n".join(lines[:25]) + f"\n... and {len(lines) - 25} more"
    await update.message.reply_text(out[:3900] if out else "No projects found")


async def proposal_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate proposal: /proposal_gen ProjectName"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /proposal_gen ProjectName\nExample: /proposal_gen Kelly")
        return
    
    project = " ".join(context.args)
    await update.message.reply_text(f"🔧 Generating proposal for {project}...")
    rc, out = _run_proposal_agent(f'--project "{project}"')
    await update.message.reply_text(out[:3900] if out else "Generation failed")


async def proposal_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process all pending proposals: /proposal_batch"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🔄 Processing all pending proposals... This may take a while.")
    rc, out = _run_proposal_agent("--batch")
    await update.message.reply_text(out[:3900] if out else "Batch failed")


async def dtools_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Upload proposal to D-Tools Cloud: /dtools_upload ProjectName"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /dtools_upload ProjectName\nExample: /dtools_upload Mitchell")
        return
    
    project = " ".join(context.args)
    await update.message.reply_text(f"🌐 Uploading {project} to D-Tools Cloud...")
    rc, out = _run_dtools_agent(f'--full "{project}"')
    await update.message.reply_text(out[:3900] if out else "Upload failed")


async def dtools_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search D-Tools Cloud: /dtools_search ProjectName"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /dtools_search ProjectName")
        return
    
    project = " ".join(context.args)
    await update.message.reply_text(f"🔍 Searching D-Tools for {project}...")
    rc, out = _run_dtools_agent(f'--search "{project}"')
    await update.message.reply_text(out[:3900] if out else "Search failed")


# --- Symphony Proposals System ---

def _run_symphony_cli(args: str) -> tuple[int, str]:
    """Run symphony proposals CLI."""
    cmd = f"python3 -m symphony.proposals.cli {args}"
    return _run_script(cmd.split())


def _run_smart_proposal(args: str) -> tuple[int, str]:
    """Run smart_proposal.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "smart_proposal.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def sym_quick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """AI-powered quick proposal: /quote <description>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "📄 *AI Smart Proposal*\n\n"
            "Usage: /quote <project description>\n\n"
            "Examples:\n"
            "• /quote 5000sqft home, whole home audio, lighting\n"
            "• /quote Mitchell 8000sqft luxury, 12 zones audio, shades, security\n"
            "• /quote condo, 6 rooms, Control4, basic automation\n\n"
            "I'll analyze the scope and generate equipment + pricing automatically!",
            parse_mode="Markdown"
        )
        return
    
    description = " ".join(context.args)
    
    # Extract client name if first word looks like a name
    parts = description.split()
    if parts[0][0].isupper() and len(parts[0]) > 2 and not any(c.isdigit() for c in parts[0]):
        client = parts[0]
        description = " ".join(parts[1:]) if len(parts) > 1 else parts[0]
    else:
        client = "Client"
    
    await update.message.reply_text(f"🤖 Generating AI proposal for {client}...\n\n_{description}_", parse_mode="Markdown")
    
    rc, out = _run_smart_proposal(f'"{description}" --client "{client}" --save')
    
    if out:
        await update.message.reply_text(out[:3900], parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to generate proposal")


async def sym_proposals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all proposals: /quotes"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_symphony_cli("proposal list")
    await update.message.reply_text(out[:3900] if out else "No proposals found")


async def sym_proposal_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show proposal details: /quote_show P-20260306-XXXX"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /quote_show PROPOSAL_ID")
        return
    
    proposal_id = context.args[0]
    rc, out = _run_symphony_cli(f"proposal show {proposal_id}")
    await update.message.reply_text(out[:3900] if out else "Proposal not found")


async def sym_invoices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all invoices: /invoices"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_symphony_cli("invoice list")
    await update.message.reply_text(out[:3900] if out else "No invoices found")


async def sym_invoice_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create invoice from proposal: /invoice_from P-20260306-XXXX"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /invoice_from PROPOSAL_ID")
        return
    
    proposal_id = context.args[0]
    rc, out = _run_symphony_cli(f"invoice create --from-proposal {proposal_id}")
    await update.message.reply_text(out[:3900] if out else "Failed to create invoice")


async def sym_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record payment: /payment INV-XXXX 5000"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /payment INVOICE_ID AMOUNT\nExample: /payment INV-20260306-XXXX 5000")
        return
    
    invoice_id = context.args[0]
    amount = context.args[1]
    rc, out = _run_symphony_cli(f"invoice payment {invoice_id} --amount {amount}")
    await update.message.reply_text(out[:3900] if out else "Failed to record payment")


async def sym_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show proposal stats: /quote_stats"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_symphony_cli("stats")
    await update.message.reply_text(out[:3900] if out else "No stats available")


async def sym_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all clients: /clients"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_symphony_cli("client list")
    await update.message.reply_text(out[:3900] if out else "No clients found")


async def sym_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add item to proposal: /add_item P-XXXX SKU QTY Room"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /add_item PROPOSAL_ID SKU QTY [ROOM]\n"
            "Example: /add_item P-20260306-XXXX C4-EA5 1 \"Equipment Room\""
        )
        return
    
    proposal_id = context.args[0]
    sku = context.args[1]
    qty = context.args[2]
    room = " ".join(context.args[3:]) if len(context.args) > 3 else ""
    
    cmd = f'proposal add-item {proposal_id} --sku {sku} --qty {qty}'
    if room:
        cmd += f' --room "{room}"'
    
    rc, out = _run_symphony_cli(cmd)
    await update.message.reply_text(out[:3900] if out else "Failed to add item")


async def sym_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate proposal HTML: /generate P-XXXX"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /generate PROPOSAL_ID")
        return
    
    proposal_id = context.args[0]
    rc, out = _run_symphony_cli(f"proposal generate {proposal_id}")
    await update.message.reply_text(out[:3900] if out else "Failed to generate")


# --- Email Integration ---

async def email_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check inbox summary: /inbox"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📧 Checking inbox...")
    
    try:
        from symphony.email.client import EmailClient
        client = EmailClient()
        summary = client.get_inbox_summary(limit=8)
        
        if summary.get("error"):
            await update.message.reply_text(f"❌ {summary['error']}")
            return
        
        lines = [
            f"📬 *Inbox: {summary['email']}*",
            f"",
            f"📨 Unread: {summary['unread']}",
            f"📋 Recent (7 days): {summary['recent_count']}",
            ""
        ]
        
        if summary.get("recent"):
            lines.append("*Recent:*")
            for e in summary["recent"][:8]:
                sender = e['from'][:25]
                subj = e['subject'][:40]
                lines.append(f"• {sender}")
                lines.append(f"   _{subj}_")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def email_bids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check BuildingConnected bid invitations: /bids"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🏗️ Checking for BuildingConnected bids...")
    
    try:
        from symphony.email.building_connected import BuildingConnectedMonitor
        monitor = BuildingConnectedMonitor()
        
        # Check for new bids
        new_bids = monitor.check_for_new_bids(since_days=30)
        all_bids = monitor.get_all_invitations()
        
        lines = [f"🏗️ *BuildingConnected Bids*", ""]
        
        if new_bids:
            lines.append(f"🆕 *{len(new_bids)} NEW bid(s) found!*")
            for inv in new_bids[:3]:
                lines.append(f"• {inv.project_name}")
                lines.append(f"   GC: {inv.general_contractor}")
                if inv.bid_due_date:
                    lines.append(f"   Due: {inv.bid_due_date}")
            lines.append("")
        
        # Summary
        new_count = len([b for b in all_bids if b.status == "new"])
        created_count = len([b for b in all_bids if b.status == "proposal_created"])
        
        lines.append(f"📊 *Summary:*")
        lines.append(f"   New: {new_count}")
        lines.append(f"   Proposal Created: {created_count}")
        lines.append(f"   Total: {len(all_bids)}")
        
        lines.append(f"\nUse /bid\\_list to see all")
        lines.append(f"Use /bid\\_create ID to create proposal")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def email_bid_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all bid invitations: /bid_list"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    try:
        from symphony.email.building_connected import BuildingConnectedMonitor
        monitor = BuildingConnectedMonitor()
        
        all_bids = monitor.get_all_invitations()
        
        if not all_bids:
            await update.message.reply_text("📋 No bid invitations found.\n\nUse /bids to check for new ones.")
            return
        
        lines = ["🏗️ *All Bid Invitations*", ""]
        
        status_emoji = {"new": "🆕", "reviewed": "👀", "proposal_created": "✅", "declined": "❌"}
        
        for inv in all_bids[:15]:
            emoji = status_emoji.get(inv.status, "❓")
            lines.append(f"{emoji} *{inv.project_name}*")
            lines.append(f"   GC: {inv.general_contractor}")
            if inv.bid_due_date:
                lines.append(f"   Due: {inv.bid_due_date}")
            lines.append(f"   ID: `{inv.email_uid}`")
            lines.append("")
        
        if len(all_bids) > 15:
            lines.append(f"_...and {len(all_bids) - 15} more_")
        
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def email_bid_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create proposal from bid: /bid_create EMAIL_UID"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "Usage: /bid_create EMAIL_UID\n\n"
            "Get EMAIL_UID from /bid_list"
        )
        return
    
    email_uid = context.args[0]
    
    await update.message.reply_text(f"📄 Creating proposal from bid {email_uid}...")
    
    try:
        from symphony.email.building_connected import BuildingConnectedMonitor
        monitor = BuildingConnectedMonitor()
        
        proposal_id = monitor.create_proposal_from_invitation(email_uid)
        
        if proposal_id:
            await update.message.reply_text(
                f"✅ Proposal created!\n\n"
                f"ID: `{proposal_id}`\n\n"
                f"Use /quote_show {proposal_id} to view\n"
                f"Use /add_item {proposal_id} SKU QTY ROOM to add equipment",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ Bid not found: {email_uid}")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def email_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search emails: /email_search query"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /email_search query\nExample: /email_search Mitchell")
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Searching for: {query}...")
    
    try:
        from symphony.email.client import EmailClient
        client = EmailClient()
        
        if not client.connect():
            await update.message.reply_text("❌ Could not connect to email")
            return
        
        try:
            results = client.search(
                folder="INBOX",
                subject_contains=query,
                since_days=60,
                limit=10
            )
            
            if not results:
                await update.message.reply_text(f"No emails found matching: {query}")
                return
            
            lines = [f"📧 *Search Results: {query}*", f"Found: {len(results)}", ""]
            
            for e in results[:8]:
                lines.append(f"• *{e.subject[:50]}*")
                lines.append(f"   From: {e.sender_name or e.sender[:30]}")
                lines.append(f"   {e.date[:16]}")
                lines.append("")
            
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            
        finally:
            client.disconnect()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# --- Browser Automation ---

async def browser_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run autonomous browser task: /browse <task description>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "🤖 *Autonomous Browser*\n\n"
            "Usage: /browse <task>\n\n"
            "Examples:\n"
            "• /browse Go to buildingconnected.com and check for new bids\n"
            "• /browse Search Google for Control4 EA-5 specs\n"
            "• /browse Log into D-Tools and list all projects",
            parse_mode="Markdown"
        )
        return
    
    task = " ".join(context.args)
    await update.message.reply_text(f"🤖 Starting browser task...\n\n_{task}_", parse_mode="Markdown")
    
    try:
        import asyncio
        from symphony.browser.autonomous import AutonomousBrowser
        
        browser = AutonomousBrowser(headless=True)
        result = await browser.run_task(task, max_steps=30)
        
        if result.success:
            response = f"✅ *Task Complete* ({result.duration_seconds:.1f}s)\n\n{result.result[:3500]}"
        else:
            response = f"❌ *Task Failed*\n\n{result.error}"
        
        await update.message.reply_text(response, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# --- Knowledge & Research ---

def _run_cortex(args: str) -> tuple[int, str]:
    """Run cortex_builder.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "cortex_builder.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


def _run_perplexity(args: str) -> tuple[int, str]:
    """Run perplexity_research.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "perplexity_research.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def cortex_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show cortex knowledge base status: /cortex"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_cortex("--summary")
    await update.message.reply_text(f"🧠 *Knowledge Cortex*\n\n{out[:3500]}" if out else "Cortex empty", parse_mode="Markdown")


async def cortex_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Build cortex category: /cortex_build [category]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        rc, out = _run_cortex("--list")
        await update.message.reply_text(
            f"📚 *Cortex Categories*\n\n{out[:3500]}\n\n"
            "Usage: /cortex\\_build category\n"
            "Example: /cortex\\_build lutron",
            parse_mode="Markdown"
        )
        return
    
    category = context.args[0].lower()
    await update.message.reply_text(f"🔨 Building cortex: {category}...\nThis runs in background.")
    
    # Run in background
    subprocess.Popen(
        ["python3", str(AI_SERVER_DIR / "tools" / "cortex_builder.py"), "-c", category],
        cwd=str(AI_SERVER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


async def learning_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show continuous learning status: /learning"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), "--status"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = p.stdout or p.stderr or "No status"
        await update.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def learn_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger one learning cycle: /learn [topic]"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📚 Learning something new...")
    
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), "--once"]
    if context.args:
        topic = " ".join(context.args)
        cmd.extend(["--query", topic, "--category", "company"])
    
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = p.stdout or p.stderr or "Learning complete"
        await update.message.reply_text(f"```\n{out[:3800]}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def news_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get latest news relevant to business: /news"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📰 Fetching latest news...")
    
    # Learn news topics
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "continuous_learning.py"), 
           "--query", "smart home technology news today market trends AI", "--category", "news"]
    
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        
        # Read latest news file
        news_dir = AI_SERVER_DIR / "knowledge" / "news"
        if news_dir.exists():
            files = sorted(news_dir.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
            if files:
                content = files[0].read_text()
                # Truncate content
                if len(content) > 3500:
                    content = content[:3500] + "\n\n... [truncated]"
                await update.message.reply_text(content, parse_mode="Markdown")
                return
        
        await update.message.reply_text(p.stdout[:3500] if p.stdout else "No news fetched")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Smart research - searches Cortex, pricing, then Perplexity: /research <query>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "🔍 *Smart Research*\n\n"
            "Usage: /research <query>\n\n"
            "Examples:\n"
            "• /research Control4 EA-5 specs\n"
            "• /research Lutron HomeWorks vs RadioRA3\n"
            "• /research Denver low voltage codes\n"
            "• /research audio distribution 8 zones",
            parse_mode="Markdown"
        )
        return
    
    query = " ".join(context.args)
    await update.message.reply_text(f"🔍 Researching: _{query}_...", parse_mode="Markdown")
    
    # Use smart research tool
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "smart_research.py"), query]
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=60, cwd=str(AI_SERVER_DIR))
        out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
        
        if out.strip():
            # Split into chunks if too long
            if len(out) > 3800:
                await update.message.reply_text(out[:3800] + "...", parse_mode="Markdown")
            else:
                await update.message.reply_text(out, parse_mode="Markdown")
        else:
            await update.message.reply_text("No results found")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏱️ Research timed out - try a more specific query")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# --- Subscriptions ---

def _run_subscription_audit(args: str) -> tuple[int, str]:
    """Run subscription_audit.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "integrations" / "telegram" / "subscription_audit.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show subscription costs: /subs"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_subscription_audit("--dry")
    await update.message.reply_text(out[:3900] if out else "No subscriptions tracked", parse_mode="Markdown")


async def subscription_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add subscription info: /sub_add"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text(
        "💳 *Add Subscription*\n\n"
        "Edit directly:\n"
        "`~/AI-Server/knowledge/subscriptions.json`\n\n"
        "Or run interactively:\n"
        "`python3 ~/AI-Server/integrations/telegram/subscription_audit.py --add`",
        parse_mode="Markdown"
    )


# --- Claude Code (parallel with Cursor) ---

async def claude_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Launch Claude Code with task + context from WORK_IN_PROGRESS. /claude <task>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return

    task = " ".join(context.args) if context.args else ""
    if not task:
        await update.message.reply_text(
            "🤖 *Claude Code* — Run tasks in parallel with Cursor\n\n"
            "Usage: `/claude <task>`\n\n"
            "Example:\n"
            "• `/claude` Refactor handlers/menus.py into smaller modules\n"
            "• `/claude` Add type hints to tools/competitor_research.py\n"
            "• `/claude` Review integrations/dtools for error handling\n\n"
            "Context from WORK_IN_PROGRESS and task board is automatically included so Claude knows what we're working on.",
            parse_mode="Markdown"
        )
        return

    try:
        sys.path.insert(0, str(AI_SERVER_DIR / "tools"))
        from claude_runner import run_claude_task
        ok, msg = run_claude_task(task)
        if ok:
            await update.message.reply_text(
                f"🤖 *Claude job started*\n\n"
                f"Task: _{task[:80]}{'...' if len(task) > 80 else ''}_\n\n"
                f"Context from WORK_IN_PROGRESS + task board included.\n\n"
                f"Output: `{msg}`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"Failed to start Claude: {msg}")
    except Exception as e:
        await update.message.reply_text(f"Failed to start Claude: {e}")


# --- Daily Briefing ---

def _run_daily_digest(args: str) -> tuple[int, str]:
    """Run daily_digest.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "integrations" / "telegram" / "daily_digest.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send daily briefing now: /briefing"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("📋 Generating briefing...")
    rc, out = _run_daily_digest("")
    await update.message.reply_text(out[:3900] if out else "Briefing failed", parse_mode="Markdown")


async def morning_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run morning checklist: /morning"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("☀️ Running morning checklist...")
    cmd = ["python3", str(AI_SERVER_DIR / "orchestrator" / "morning_checklist.py"), "--dry"]
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    await update.message.reply_text(out[:3900] if out.strip() else "Checklist failed", parse_mode="Markdown")


async def website_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check website health: /website"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    quick = not context.args or context.args[0] != "full"
    flag = "--quick" if quick else ""
    
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "website_monitor.py")] + ([flag] if flag else [])
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    out = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    await update.message.reply_text(f"```\n{out[:3800]}\n```" if out.strip() else "Check failed", parse_mode="Markdown")


# --- Dealer Forms ---

def _run_dealer_forms(args: str) -> tuple[int, str]:
    """Run dealer_forms.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "dealer_forms.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def dealer_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List known dealer application forms: /dealers"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_dealer_forms("--list")
    await update.message.reply_text(out[:3900] if out else "No vendors found")


async def dealer_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fill dealer application: /dealer_apply <vendor or URL>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "📝 *Dealer Application Filler*\n\n"
            "Usage:\n"
            "• /dealer\\_apply origin\\_acoustics\n"
            "• /dealer\\_apply https://vendor.com/form\n\n"
            "Options:\n"
            "• /dealers - List known vendors\n"
            "• /dealer\\_preview - Preview your company data\n\n"
            "I'll fill the form and save a draft for your review.",
            parse_mode="Markdown"
        )
        return
    
    target = " ".join(context.args)
    
    await update.message.reply_text(f"📝 Preparing dealer application for: {target}...")
    
    # Determine if it's a URL or vendor key
    if target.startswith("http"):
        rc, out = _run_dealer_forms(f'--url "{target}" --save-draft')
    else:
        rc, out = _run_dealer_forms(f'--vendor {target} --save-draft')
    
    await update.message.reply_text(out[:3900] if out else "❌ Failed to process form")


async def dealer_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Preview company profile data: /dealer_preview"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_dealer_forms("--preview")
    await update.message.reply_text(out[:3900] if out else "No profile found")


# --- Investment Commands ---

def _run_market_intel(args: str) -> tuple[int, str]:
    """Run market_intel.py with given arguments."""
    cmd = ["python3", str(AI_SERVER_DIR / "tools" / "market_intel.py")] + shlex.split(args)
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def invest_research(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Research an investment topic: /invest <topic>"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    if not context.args:
        await update.message.reply_text(
            "📈 *Investment Research*\n\n"
            "Usage: /invest <topic>\n\n"
            "Examples:\n"
            "• /invest Polymarket Trump odds\n"
            "• /invest Bitcoin ETF flows\n"
            "• /invest AI chip stocks NVDA AMD\n"
            "• /invest Fed rate decision March\n\n"
            "🎯 Goal: $3,649 for Beatrice Upgrade",
            parse_mode="Markdown"
        )
        return
    
    topic = " ".join(context.args)
    await update.message.reply_text(f"🔍 Researching: {topic}\n\n_This may take 30-60 seconds..._", parse_mode="Markdown")
    
    rc, out = _run_market_intel(f'--research "{topic}"')
    
    # Split long messages
    if len(out) > 4000:
        await update.message.reply_text(out[:4000])
        if len(out) > 4000:
            await update.message.reply_text(out[4000:8000] if len(out) > 8000 else out[4000:])
    else:
        await update.message.reply_text(out if out else "Research failed")


async def portfolio_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show portfolio status: /portfolio"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    rc, out = _run_market_intel("--portfolio")
    await update.message.reply_text(f"```\n{out[:3900]}\n```" if out else "No portfolio", parse_mode="Markdown")


async def polymarket_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scan Polymarket opportunities: /polymarket"""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return
    
    await update.message.reply_text("🎰 Scanning Polymarket opportunities...\n\n_This may take 60-90 seconds..._", parse_mode="Markdown")
    
    rc, out = _run_market_intel("--polymarket")
    
    if len(out) > 4000:
        await update.message.reply_text(out[:4000])
        if len(out) > 4000:
            await update.message.reply_text(out[4000:8000] if len(out) > 8000 else out[4000:])
    else:
        await update.message.reply_text(out if out else "Scan failed")


async def dtools_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """D-Tools automation: create/import/batch proposal workflows."""
    if not _chat_allowed(update):
        await update.message.reply_text(_unauthorized_message(update))
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "🔧 *D-Tools Automation*\n\n"
            "Usage:\n"
            "• /dtools_auto create \"Project Name\" \"Client Name\"\n"
            "• /dtools_auto import P-XXXX (creates project + imports equipment from symphony proposal)\n\n"
            "• /dtools_auto batch P-XXXX P-YYYY ... (run multiple imports)\n\n"
            "_Full autonomous browser control - no hand-holding_",
            parse_mode="Markdown"
        )
        return

    action = context.args[0].lower()

    if action == "import":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /dtools_auto import P-XXXX")
            return
        proposal_id = context.args[1].strip()

        # Prepare proposal: load from symphony, export CSV
        try:
            sys.path.insert(0, str(AI_SERVER_DIR / "integrations" / "dtools"))
            from proposal_workflow import prepare_proposal_for_dtools_import

            prep = prepare_proposal_for_dtools_import(proposal_id)
            if not prep.get("ok"):
                await update.message.reply_text(f"❌ {prep.get('error', 'Unknown error')}")
                return

            project_name = prep["project_name"]
            client_name = prep["client_name"]
            address = prep.get("address", "")
            csv_path = prep["csv_path"]
            item_count = prep.get("item_count", 0)

            await update.message.reply_text(
                f"📄 *Importing proposal {proposal_id}*\n"
                f"Project: {project_name}\n"
                f"Client: {client_name}\n"
                f"Items: {item_count}\n\n"
                f"🔧 Starting headless browser (Playwright)...",
                parse_mode="Markdown"
            )

            from agents.dtools_browser_agent import DToolsBrowserAgent

            agent = DToolsBrowserAgent(headless=True)
            if not await agent.start():
                await update.message.reply_text("❌ Browser start failed. Run: pip install playwright && playwright install chromium")
                return

            try:
                result = await agent.full_workflow(
                    project_name=project_name,
                    client_name=client_name,
                    address=address,
                    csv_path=csv_path,
                )

                if result.get("success"):
                    lines = [f"✅ *D-Tools import complete*"]
                    for step in result.get("steps", []):
                        sres = step.get("result", {})
                        status = "✅" if sres.get("success") else "❌"
                        lines.append(f"  {status} {step.get('step', '?')}")
                    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                else:
                    await update.message.reply_text(
                        f"❌ *Failed*\n\n{result.get('error', 'Unknown error')}",
                        parse_mode="Markdown"
                    )
            finally:
                await agent.stop()
            return

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    if action == "batch":
        proposal_ids = [p.strip() for p in context.args[1:] if p.strip()]
        if not proposal_ids:
            await update.message.reply_text("Usage: /dtools_auto batch P-XXXX P-YYYY ...")
            return
        await update.message.reply_text(
            f"🚀 *Batch import started*\nCount: {len(proposal_ids)}\nIDs: {', '.join(proposal_ids[:6])}",
            parse_mode="Markdown",
        )
        try:
            sys.path.insert(0, str(AI_SERVER_DIR / "integrations" / "dtools"))
            from tonight_proposal_runner import _run_batch  # type: ignore

            report = await _run_batch(
                proposal_ids=proposal_ids,
                retries=1,
                visible=False,
                api_first=True,
            )
            ok_count = report.get("success_count", 0)
            fail_count = report.get("failed_count", 0)
            lines = [f"✅ Done. Success: {ok_count}  Failed: {fail_count}"]
            for r in report.get("results", [])[:10]:
                status = "✅" if r.get("ok") else "❌"
                lines.append(f"{status} {r.get('proposal_id')}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"❌ Batch failed: {e}")
        return

    if action == "create":
        if len(context.args) < 2:
            await update.message.reply_text("Usage: /dtools_auto create \"Project Name\" \"Client Name\"")
            return

        # Parse quoted args
        full_text = " ".join(context.args[1:])
        import re
        quotes = re.findall(r'"([^"]+)"', full_text)
        project_name = quotes[0] if quotes else context.args[1]
        client_name = quotes[1] if len(quotes) > 1 else "Unknown"

        # Search before create (dtools.mdc workflow)
        try:
            sys.path.insert(0, str(AI_SERVER_DIR / "integrations" / "dtools"))
            from proposal_workflow import search_before_create, format_search_result
            search_result = search_before_create(project_name, client_name)
            msg = format_search_result(search_result)
            if search_result.get("matches") or search_result.get("similar_projects"):
                await update.message.reply_text(
                    f"🔍 *Search before create:*\n\n{msg}\n\n"
                    "Proceeding with create in 5s. Reply /cancel to stop.",
                    parse_mode="Markdown"
                )
                await asyncio.sleep(5)
        except Exception as e:
            await update.message.reply_text(f"⚠️ Search skipped: {e}")

        await update.message.reply_text(f"🔧 Starting headless browser (Playwright)...")

        try:
            from agents.dtools_browser_agent import DToolsBrowserAgent

            agent = DToolsBrowserAgent(headless=True)
            if not await agent.start():
                await update.message.reply_text("❌ Browser start failed. Run: pip install playwright && playwright install chromium")
                return

            try:
                result = await agent.create_project(
                    project_name=project_name,
                    client_name=client_name,
                )
                if result.get("success"):
                    await update.message.reply_text(f"✅ *D-Tools: project created*\n\n{project_name}", parse_mode="Markdown")
                else:
                    await update.message.reply_text(f"❌ *Failed*\n\n{result.get('error', 'Unknown error')}", parse_mode="Markdown")
            finally:
                await agent.stop()
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    await update.message.reply_text(f"Unknown action: {action}. Use 'create', 'import', or 'batch'.")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(token).build()
    
    # Callback handler for inline buttons (must be added before command handlers)
    app.add_handler(CallbackQueryHandler(button_callback))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("usage", usage_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("tail", tail))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("export", export))
    
    # Knowledge & Research
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("cortex", cortex_status))
    app.add_handler(CommandHandler("cortex_build", cortex_build))
    app.add_handler(CommandHandler("learning", learning_status))
    app.add_handler(CommandHandler("learn", learn_now))
    app.add_handler(CommandHandler("news", news_digest))
    
    # Subscriptions & Briefing
    app.add_handler(CommandHandler("subs", subscriptions))
    app.add_handler(CommandHandler("sub_add", subscription_add))
    app.add_handler(CommandHandler("briefing", briefing))
    app.add_handler(CommandHandler("morning", morning_check))
    app.add_handler(CommandHandler("claude", claude_command))
    app.add_handler(CommandHandler("website", website_check))
    
    # Investment commands
    app.add_handler(CommandHandler("invest", invest_research))
    app.add_handler(CommandHandler("portfolio", portfolio_status))
    app.add_handler(CommandHandler("polymarket", polymarket_scan))
    
    # Notes commands
    app.add_handler(CommandHandler("notes_folders", notes_folders))
    app.add_handler(CommandHandler("notes_list", notes_list))
    app.add_handler(CommandHandler("notes_search", notes_search))
    app.add_handler(CommandHandler("notes_project", notes_project))
    app.add_handler(CommandHandler("notes_read", notes_read))
    
    # Knowledge commands
    app.add_handler(CommandHandler("protocol", protocol))
    
    # Learning and ideas commands
    app.add_handler(CommandHandler("learning", learning))
    app.add_handler(CommandHandler("ideas", ideas))
    app.add_handler(CommandHandler("sync_notes", sync_notes))
    
    # Notes watcher commands
    app.add_handler(CommandHandler("watch_notes", watch_notes))
    app.add_handler(CommandHandler("watch_status", watch_status))
    
    # Troubleshooting commands
    app.add_handler(CommandHandler("troubleshoot", troubleshoot))
    
    # Task board commands
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("task_add", task_add))
    app.add_handler(CommandHandler("task_status", task_status))
    app.add_handler(CommandHandler("task_report", task_report))
    
    # Notes analysis/approval commands
    app.add_handler(CommandHandler("notes_review", notes_review))
    app.add_handler(CommandHandler("approve", notes_approve))
    app.add_handler(CommandHandler("defer", notes_defer))
    app.add_handler(CommandHandler("notes_status", notes_analysis_status))
    
    # Proposal generator
    app.add_handler(CommandHandler("proposal", proposal))
    
    # Incoming task processor
    app.add_handler(CommandHandler("incoming", incoming_check))
    app.add_handler(CommandHandler("incoming_status", incoming_status))
    
    # Polymarket commands
    app.add_handler(CommandHandler("poly", poly_trending))
    app.add_handler(CommandHandler("poly_search", poly_search))
    app.add_handler(CommandHandler("poly_arb", poly_arb))
    app.add_handler(CommandHandler("poly_signals", poly_signals))
    app.add_handler(CommandHandler("poly_expiring", poly_expiring))
    
    # Stock trading commands
    app.add_handler(CommandHandler("trading", trading_status))
    app.add_handler(CommandHandler("positions", trading_positions))
    app.add_handler(CommandHandler("dash", trading_dashboard))
    app.add_handler(CommandHandler("opps", trading_opportunities))
    app.add_handler(CommandHandler("recommend", trading_recommend))
    app.add_handler(CommandHandler("risk", trading_risk))
    app.add_handler(CommandHandler("size", trading_size))
    app.add_handler(CommandHandler("backtest", trading_backtest))
    
    # Proposal commands
    app.add_handler(CommandHandler("proposals", proposal_list))
    app.add_handler(CommandHandler("proposal_gen", proposal_generate))
    app.add_handler(CommandHandler("proposal_batch", proposal_batch))
    
    # D-Tools Cloud commands
    app.add_handler(CommandHandler("dtools_upload", dtools_upload))
    app.add_handler(CommandHandler("dtools_search", dtools_search))
    
    # Symphony Proposals commands
    app.add_handler(CommandHandler("quote", sym_quick))
    app.add_handler(CommandHandler("quotes", sym_proposals))
    app.add_handler(CommandHandler("quote_show", sym_proposal_show))
    app.add_handler(CommandHandler("quote_stats", sym_stats))
    app.add_handler(CommandHandler("invoices", sym_invoices))
    app.add_handler(CommandHandler("invoice_from", sym_invoice_create))
    app.add_handler(CommandHandler("payment", sym_payment))
    app.add_handler(CommandHandler("clients", sym_clients))
    app.add_handler(CommandHandler("add_item", sym_add_item))
    app.add_handler(CommandHandler("generate", sym_generate))
    
    # Email / BuildingConnected commands
    app.add_handler(CommandHandler("inbox", email_inbox))
    app.add_handler(CommandHandler("bids", email_bids))
    app.add_handler(CommandHandler("bid_list", email_bid_list))
    app.add_handler(CommandHandler("bid_create", email_bid_create))
    app.add_handler(CommandHandler("email_search", email_search))
    
    # Browser automation commands
    app.add_handler(CommandHandler("browse", browser_task))
    app.add_handler(CommandHandler("dtools_auto", dtools_auto))
    
    # Dealer application commands
    app.add_handler(CommandHandler("dealers", dealer_list))
    app.add_handler(CommandHandler("dealer_apply", dealer_apply))
    app.add_handler(CommandHandler("dealer_preview", dealer_preview))

    _log("Bob Remote polling started")
    app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
