#!/usr/bin/env python3
import os
import subprocess
import shlex
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

AI_SERVER_DIR = Path(os.environ.get("AI_SERVER_DIR", "/AI-Server"))
ORCHESTRATOR = AI_SERVER_DIR / "orchestrator" / "core" / "bob_orchestrator.py"
RUN_BOB = AI_SERVER_DIR / "RUN_BOB.command"  # for status only
LOG_FILE = AI_SERVER_DIR / "orchestrator" / "logs" / "bob_orchestrator.log"

STATE_DIR = AI_SERVER_DIR / "telegram-bob-remote" / "state"
STATE_FILE = STATE_DIR / "allowed_ids.txt"

ALLOWED_IDS_RAW = os.environ.get("ALLOWED_CHAT_ID", "").strip()


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def _get_ids(update: Update) -> tuple[str, str]:
    chat_id = ""
    user_id = ""
    try:
        if update.effective_chat is not None:
            chat_id = str(update.effective_chat.id)
    except Exception:
        chat_id = ""
    try:
        if update.effective_user is not None:
            user_id = str(update.effective_user.id)
    except Exception:
        user_id = ""
    return chat_id, user_id


def _load_allowed_ids() -> set[str]:
    ids = {s.strip() for s in ALLOWED_IDS_RAW.split(",") if s.strip()}
    try:
        if STATE_FILE.exists():
            txt = STATE_FILE.read_text(encoding="utf-8", errors="ignore")
            for line in txt.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.add(line)
    except Exception:
        pass
    return ids


def _save_allowed_ids(ids: set[str]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("\n".join(sorted(ids)) + "\n", encoding="utf-8")
    except Exception as e:
        _log(f"[state] failed to save allowed ids: {e}")


def _chat_allowed(update: Update) -> bool:
    allowed = _load_allowed_ids()
    if not allowed:
        return True
    chat_id, user_id = _get_ids(update)
    return (chat_id in allowed) or (user_id in allowed)


def _unauthorized_message(update: Update) -> str:
    chat_id, user_id = _get_ids(update)
    return (
        "Unauthorized.\n"
        f"chat_id={chat_id or '(unknown)'}\n"
        f"user_id={user_id or '(unknown)'}\n\n"
        "To auto-lock: keep ALLOWED_CHAT_ID blank and send /start from the correct chat.\n"
        f"State file: {STATE_FILE}"
    )


def _tail(path: Path, n: int = 40) -> str:
    if not path.exists():
        return f"(no log file at {path})"
    try:
        out = subprocess.check_output(
            ["/bin/sh", "-lc", f"tail -n {int(n)} {shlex.quote(str(path))}"],
            text=True,
        )
        return out.strip() or "(log empty)"
    except Exception as e:
        return f"(tail failed: {e})"


def _run_bob(args: str) -> tuple[int, str]:
    # Run orchestrator directly with container python (no venv dependency)
    cmd = ["python3", str(ORCHESTRATOR)] + shlex.split(args)
    env = os.environ.copy()
    env["AI_SERVER_DIR"] = str(AI_SERVER_DIR)
    p = subprocess.run(cmd, text=True, capture_output=True, env=env)
    combined = (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")
    return p.returncode, combined.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, user_id = _get_ids(update)
    allowed = _load_allowed_ids()

    _log(f"/start from chat_id={chat_id} user_id={user_id} allowed_count={len(allowed)}")

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
        "Bob Remote is online.\n"
        "Commands:\n"
        "/status\n"
        "/tail\n"
        "/refresh\n"
        "/analyze <project>\n"
        "/export <project>\n"
        "/whoami"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, user_id = _get_ids(update)
    await update.message.reply_text(f"chat_id={chat_id}\nuser_id={user_id}")


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


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("tail", tail))
    app.add_handler(CommandHandler("refresh", refresh))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("export", export))

    _log("Bob Remote polling started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
