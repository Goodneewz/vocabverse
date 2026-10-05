import os
import json
import random
import logging
import requests
from pathlib import Path
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --- Config ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DICT_API = "https://api.dictionaryapi.dev/api/v2/entries/en"
DATA_FILE = Path("user_words.json")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Storage (tiny JSON file, fine for one user; switch to a DB if multi-user) ---
def load_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"users": {}}

def save_data(data: dict):
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

# --- Dictionary lookup ---
def fetch_word(word: str):
    try:
        r = requests.get(f"{DICT_API}/{word.lower()}", timeout=10)
        if r.status_code != 200:
            return None
        return r.json()[0]
    except Exception as e:
        log.error(f"dict error: {e}")
        return None

def format_definition(word_data: dict) -> str:
    word = word_data.get("word", "?").upper()
    phonetics = word_data.get("phonetic") or ""
    lines = [f"📖 *{word}*  _{phonetics}_", ""]

    meanings = word_data.get("meanings", [])
    for m in meanings[:2]:  # cap at 2 meanings to keep message readable
        pos = m.get("partOfSpeech", "")
        defs = m.get("definitions", [])
        if not defs:
            continue
        lines.append(f"_{pos}_")
        for i, d in enumerate(defs[:2], 1):
            lines.append(f"{i}. {d.get('definition', '')}")
            ex = d.get("example")
            if ex:
                lines.append(f"   _e.g._ \"{ex}\"")
        syns = m.get("synonyms", [])
        if syns:
            lines.append(f"   syn: {', '.join(syns[:5])}")
        lines.append("")

    return "\n".join(lines).strip()

# --- Commands ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Vocab bot here.*\n\n"
        "Commands:\n"
        "/define <word> — definition, example, synonyms\n"
        "/example <word> — usage in a sentence\n"
        "/save <word> — add to your word list\n"
        "/list — show your saved words\n"
        "/quiz — test yourself on saved words\n"
        "/remove <word> — drop a word from your list\n\n"
        "Just type a word without / to get a quick definition."
    )

async def define_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /define <word>")
        return
    word = " ".join(ctx.args)
    data = fetch_word(word)
    if not data:
        await update.message.reply_text(f"❌ No entry for \"{word}\".")
        return
    await update.message.reply_text(format_definition(data), parse_mode="Markdown")

async def example_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /example <word>")
        return
    word = " ".join(ctx.args)
    data = fetch_word(word)
    if not data:
        await update.message.reply_text(f"❌ No entry for \"{word}\".")
        return
    for m in data.get("meanings", []):
        for d in m.get("definitions", []):
            if d.get("example"):
                await update.message.reply_text(
                    f"📝 *{word}* in a sentence:\n\n\"{d['example']}\""
                )
                return
    await update.message.reply_text(f"No example available for \"{word}\".")

async def save_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /save <word>")
        return
    word = " ".join(ctx.args).lower().strip()
    user_id = str(update.effective_user.id)
    data = load_data()
    data["users"].setdefault(user_id, {"words": []})
    if word in data["users"][user_id]["words"]:
        await update.message.reply_text(f"\"{word}\" is already in your list.")
        return
    data["users"][user_id]["words"].append(word)
    save_data(data)
    await update.message.reply_text(f"✅ Saved \"{word}\". Total: {len(data['users'][user_id]['words'])} words.")

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    words = data["users"].get(user_id, {}).get("words", [])
    if not words:
        await update.message.reply_text("Your list is empty. Use /save <word> to add some.")
        return
    msg = "📚 *Your words:*\n\n" + "\n".join(f"{i+1}. {w}" for i, w in enumerate(words))
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /remove <word>")
        return
    word = " ".join(ctx.args).lower().strip()
    user_id = str(update.effective_user.id)
    data = load_data()
    words = data["users"].get(user_id, {}).get("words", [])
    if word not in words:
        await update.message.reply_text(f"\"{word}\" is not in your list.")
        return
    words.remove(word)
    save_data(data)
    await update.message.reply_text(f"🗑 Removed \"{word}\".")

async def quiz_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    words = data["users"].get(user_id, {}).get("words", [])
    if len(words) < 1:
        await update.message.reply_text("Add some words with /save first.")
        return
    word = random.choice(words)
    entry = fetch_word(word)
    if not entry:
        await update.message.reply_text(f"Couldn't fetch \"{word}\" right now. Try another.")
        return
    meanings = entry.get("meanings", [])
    definition = ""
    for m in meanings:
        defs = m.get("definitions", [])
        if defs:
            definition = defs[0].get("definition", "")
            break
    if not definition:
        await update.message.reply_text(f"No definition found for \"{word}\".")
        return
    await update.message.reply_text(
        f"🧠 *Quiz:*\n\nWhat does *{word}* mean?\n\nReply with your guess. I'll check the next message."
    )
    ctx.user_data["quiz_word"] = word
    ctx.user_data["quiz_def"] = definition

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Quiz check
    if "quiz_word" in ctx.user_data:
        target = ctx.user_data.pop("quiz_word")
        target_def = ctx.user_data.pop("quiz_def")
        guess = update.message.text.strip()
        if guess.lower() == target.lower():
            await update.message.reply_text("🎉 Correct!")
        else:
            await update.message.reply_text(
                f"❌ The word was *{target}*.\n\n{target_def}", parse_mode="Markdown"
            )
        return

    # Default: treat bare text as a define lookup
    word = update.message.text.strip()
    if not word or word.startswith("/"):
        return
    data = fetch_word(word)
    if not data:
        await update.message.reply_text(f"❌ No entry for \"{word}\".")
        return
    await update.message.reply_text(format_definition(data), parse_mode="Markdown")

# --- Main ---
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env var is not set")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("define", define_cmd))
    app.add_handler(CommandHandler("example", example_cmd))
    app.add_handler(CommandHandler("save", save_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot starting…")
    app.run_polling()

if __name__ == "__main__":
    main()
