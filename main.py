# Telegram Auto Join + Welcome Bot with Deep Linking & Admin Panel
# Python 3.10+ | python-telegram-bot 22.x

import logging
import os
import sqlite3
import time
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application, ChatJoinRequestHandler, ChatMemberHandler,
    CommandHandler, CallbackQueryHandler, ContextTypes,
)
from telegram.request import HTTPXRequest

BOT_TOKEN = "9085444422:AAFZtyBKErXiHt7er9jqowfZp_pI2Zyav2Q"
OWNER_IDS = {5635425261}  # Global Owner User ID

# ডাটাবেজ ফাইলের পাথ নিশ্চিত করার জন্য এটি ব্যবহার করা হয়েছে
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "join_manager.db")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("telegram-auto-join")


def db():
    con = sqlite3.connect(DB_FILE)
    con.execute("""CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY, title TEXT, username TEXT, chat_type TEXT,
        mode TEXT DEFAULT 'auto', status TEXT DEFAULT 'active', added_by INTEGER, added_at INTEGER
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS join_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
        user_id INTEGER, action TEXT, created_at INTEGER
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS chat_settings (
        chat_id INTEGER PRIMARY KEY, welcome_text TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY, banned_at INTEGER
    )""")
    
    cols = {row[1] for row in con.execute("PRAGMA table_info(chats)")}
    if "status" not in cols:
        con.execute("ALTER TABLE chats ADD COLUMN status TEXT DEFAULT 'active'")
    if "username" not in cols:
        con.execute("ALTER TABLE chats ADD COLUMN username TEXT DEFAULT ''")
    con.commit()
    return con


def save_chat(chat, added_by_user_id=0):
    con = db()
    row = con.execute("SELECT added_by FROM chats WHERE chat_id=?", (chat.id,)).fetchone()
    current_added_by = row[0] if row and row[0] else added_by_user_id
    chat_username = chat.username or ""
    
    con.execute(
        "INSERT INTO chats(chat_id,title,username,chat_type,mode,status,added_by,added_at) VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username, chat_type=excluded.chat_type, added_by=?",
        (chat.id, chat.title or str(chat.id), chat_username, chat.type, "auto", "active", current_added_by, int(time.time()), current_added_by),
    )
    con.commit()
    con.close()


def log_action(chat_id, user_id, action):
    con = db()
    con.execute(
        "INSERT INTO join_logs(chat_id,user_id,action,created_at) VALUES(?,?,?,?)",
        (chat_id, user_id, action, int(time.time())),
    )
    con.commit()
    con.close()


def welcome_template(chat_id):
    con = db()
    row = con.execute("SELECT welcome_text FROM chat_settings WHERE chat_id=?", (chat_id,)).fetchone()
    con.close()
    return row[0] if row and row[0] else "🎉 Welcome {mention}!\n\nWelcome to <b>{group}</b> ❤️"


def is_owner(user_id):
    return user_id in OWNER_IDS


def is_user_banned(user_id):
    con = db()
    row = con.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot_username = context.bot.username

    if is_user_banned(user.id):
        await update.effective_message.reply_text("🚫 Apnake bot theke ban kora hoyeche!")
        return

    # Group ba supergroup-e command dile private start korar link dibe
    if chat.type in ("group", "supergroup"):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Request to Join Group", url=f"https://t.me/{bot_username}?start=start")]
        ])
        await update.effective_message.reply_text(
            f"Hello {user.full_name}!\nGroup-e continue korte niche click korun:",
            reply_markup=keyboard
        )
        return

    # Private chat-e asle (Deep link er maddhome ba direct)
    args = context.args
    if args and args[0].startswith("join_"):
        await update.effective_message.reply_text(
            "👋 Welcome!\n\nApnar group ba channel request successful-bhabe approve o bot start kora hoyeche! 🎉"
        )
        return

    username = f"@{user.username}" if user.username else user.full_name
    await update.effective_message.reply_text(
        f"Hello {username} welcome to auto join request accept bot!\n\n"
        "Commands:\n"
        "/admin - Admin Panel (Manage Groups & Users)\n"
        "/chats - Connected chats\n"
        "/stats - Bot statistics\n"
        "/broadcast [message] - Broadcast message"
    )


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.my_chat_member
    chat = change.chat
    status = change.new_chat_member.status
    added_by = change.from_user.id

    if status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER):
        save_chat(chat, added_by_user_id=added_by)
        if status == ChatMemberStatus.ADMINISTRATOR:
            for owner_id in OWNER_IDS:
                try:
                    chat_link = f"https://t.me/{chat.username}" if chat.username else f"ID: {chat.id}"
                    await context.bot.send_message(
                        owner_id,
                        f"✅ Bot notun chat-e Admin hoyeche\nChat: {chat.title}\nLink: {chat_link}\nType: {chat.type}",
                    )
                except TelegramError:
                    pass
    elif status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        con = db()
        con.execute("DELETE FROM chats WHERE chat_id=?", (chat.id,))
        con.commit()
        con.close()


async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    chat, user = req.chat, req.from_user

    if is_user_banned(user.id):
        return

    con = db()
    chat_row = con.execute("SELECT status FROM chats WHERE chat_id=?", (chat.id,)).fetchone()
    con.close()
    
    if chat_row and chat_row[0] == 'banned':
        return

    save_chat(chat)

    try:
        await context.bot.approve_chat_join_request(chat.id, user.id)
        log_action(chat.id, user.id, "auto-approved")
    except TelegramError as exc:
        log.exception("Could not approve join request")
        log_action(chat.id, user.id, "approval-failed")
        return

    bot_username = context.bot.username
    deep_link = f"https://t.me/{bot_username}?start=join_{chat.id}"
    chat_display = f"https://t.me/{chat.username}" if chat.username else chat.title

    try:
        await context.bot.send_message(
            user.id,
            f"👋 Hello {escape(user.full_name)},\n\nApnake <b><a href='{chat_display}'>{escape(chat.title or 'Group')}</a></b>-e join request approve kora hoyeche! 🎉",
            parse_mode=ParseMode.HTML
        )
    except TelegramError:
        pass

    if chat.type in ("group", "supergroup"):
        mention = f'<a href="tg://user?id={user.id}">{escape(user.full_name)}</a>'
        template = welcome_template(chat.id)
        
        btn_text = "Request to Join Group" if chat.type in ("group", "supergroup") else "Request to Join Channel"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, url=deep_link)]
        ])
        
        try:
            welcome = template.format(
                mention=mention,
                group=escape(chat.title or "our group"),
                username=escape(user.username or user.full_name),
                user_id=user.id,
            )
            await context.bot.send_message(chat.id, welcome, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except (TelegramError, KeyError, ValueError) as exc:
            log.warning("Welcome message failed: %s", exc)

    con = db()
    row = con.execute("SELECT added_by, username, title FROM chats WHERE chat_id=?", (chat.id,)).fetchone()
    con.close()
    
    recipients = set(OWNER_IDS)
    if row and row[0]:
        recipients.add(row[0])

    c_link = f"https://t.me/{row[1]}" if row and row[1] else (chat.title or str(chat.id))
    notify_msg = (
        f"🔔 <b>JOIN REQUEST APPROVED</b>\n\n"
        f"👤 User: {escape(user.full_name)} (@{user.username if user.username else 'none'})\n"
        f"🆔 User ID: <code>{user.id}</code>\n"
        f"📢 Chat Link: <a href='{c_link}'>{escape(row[2] if row else chat.title)}</a>"
    )

    for target_id in recipients:
        try:
            await context.bot.send_message(target_id, notify_msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except TelegramError:
            pass


# --- ADMIN PANEL ---
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Manage Groups/Channels", callback_data="adm_chats")],
        [InlineKeyboardButton("🚫 Manage Banned Users", callback_data="adm_banned")],
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="adm_stats")]
    ])
    await update.effective_message.reply_text("👑 <b>Admin Control Panel</b>", reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "adm_chats":
        con = db()
        rows = con.execute("SELECT chat_id, title, username, status FROM chats").fetchall()
        con.close()
        
        if not rows:
            await query.edit_message_text("Kono chat paowa jayni.")
            return
            
        keyboard = []
        for chat_id, title, username, status in rows:
            link = f"https://t.me/{username}" if username else str(chat_id)
            icon = "🟢" if status == "active" else "🔴"
            action_btn = "Ban" if status == "active" else "Unban"
            cb_action = f"chat_ban_{chat_id}" if status == "active" else f"chat_unban_{chat_id}"
            
            keyboard.append([
                InlineKeyboardButton(f"{icon} {title[:15]}", url=link),
                InlineKeyboardButton(action_btn, callback_data=cb_action)
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="adm_home")])
        await query.edit_message_text("📋 <b>Connected Groups & Channels:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data.startswith("chat_ban_") or data.startswith("chat_unban_"):
        parts = data.split("_")
        action, chat_id = parts[1], int(parts[2])
        new_status = "banned" if action == "ban" else "active"
        
        con = db()
        con.execute("UPDATE chats SET status=? WHERE chat_id=?", (new_status, chat_id))
        con.commit()
        con.close()
        
        await query.edit_message_text(f"✅ Chat status successfully updated to <b>{new_status}</b>!", parse_mode=ParseMode.HTML)

    elif data == "adm_banned":
        con = db()
        rows = con.execute("SELECT user_id FROM banned_users").fetchall()
        con.close()
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="adm_home")]]
        text = "🚫 <b>Banned Users List:</b>\n\n"
        if rows:
            for (uid,) in rows:
                text += f"• <code>{uid}</code>\n"
        else:
            text += "Kono user ban kora nei."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data == "adm_stats":
        con = db()
        chats = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        approved = con.execute("SELECT COUNT(*) FROM join_logs WHERE action='auto-approved'").fetchone()[0]
        banned_chats = con.execute("SELECT COUNT(*) FROM chats WHERE status='banned'").fetchone()[0]
        con.close()
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="adm_home")]]
        stats_text = (
            f"📊 <b>Bot Statistics:</b>\n\n"
            f"• Connected chats: <code>{chats}</code>\n"
            f"• Banned chats: <code>{banned_chats}</code>\n"
            f"• Total approved: <code>{approved}</code>"
        )
        await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    elif data == "adm_home":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Manage Groups/Channels", callback_data="adm_chats")],
            [InlineKeyboardButton("🚫 Manage Banned Users", callback_data="adm_banned")],
            [InlineKeyboardButton("📊 Bot Statistics", callback_data="adm_stats")]
        ])
        await query.edit_message_text("👑 <b>Admin Control Panel</b>", reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def chats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    con = db()
    rows = con.execute("SELECT chat_id,title,username,chat_type FROM chats").fetchall()
    con.close()
    if not rows:
        await update.effective_message.reply_text("Kono chat nei.")
        return
    lines = ["Connected Groups/Channels:"]
    for cid, title, uname, ctype in rows:
        link = f"https://t.me/{uname}" if uname else f"ID: {cid}"
        lines.append(f"• <a href='{link}'>{escape(title)}</a> ({ctype})")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("Bebohar: /broadcast [message]")
        return
    
    con = db()
    rows = con.execute("SELECT chat_id FROM chats WHERE status='active'").fetchall()
    con.close()
    
    success = 0
    failed = 0
    for (chat_id,) in rows:
        try:
            await context.bot.send_message(chat_id, f"📢 <b>Announcement:</b>\n\n{text}", parse_mode=ParseMode.HTML)
            success += 1
        except TelegramError:
            failed += 1
            
    await update.effective_message.reply_text(f"Broadcast complete!\n✅ Success: {success}\n❌ Failed: {failed}")


async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    raw = update.effective_message.text.partition(" ")[2].strip()
    if "|" not in raw:
        await update.effective_message.reply_text("Bebohar: /setwelcome CHAT_ID | Welcome message")
        return
    chat_part, message = raw.split("|", 1)
    try:
        chat_id = int(chat_part.strip())
    except ValueError:
        await update.effective_message.reply_text("Sothik CHAT_ID দিন।")
        return
    con = db()
    con.execute("INSERT INTO chat_settings(chat_id,welcome_text) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET welcome_text=excluded.welcome_text", (chat_id, message.strip()))
    con.commit()
    con.close()
    await update.effective_message.reply_text("Welcome message updated!")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not is_owner(update.effective_user.id):
        return
    con = db()
    chats = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    approved = con.execute("SELECT COUNT(*) FROM join_logs WHERE action='auto-approved'").fetchone()[0]
    banned_chats = con.execute("SELECT COUNT(*) FROM chats WHERE status='banned'").fetchone()[0]
    con.close()
    await update.effective_message.reply_text(
        f"📊 Bot Statistics:\n- Connected chats: {chats}\n- Banned chats: {banned_chats}\n- Total approved: {approved}"
    )


def main():
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("chats", chats_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(ChatJoinRequestHandler(join_request))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    
    print("Auto Join Bot cholche...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
