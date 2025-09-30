
import os
import io
import asyncio
import logging
import signal
from urllib.parse import quote_plus

import aiohttp
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import UserNotParticipant, RPCError
from pymongo import MongoClient

# ---------------- CONFIG ----------------
API_ID = int(os.getenv("API_ID", "14050586"))
API_HASH = os.getenv("API_HASH", "42a60d9c657b106370c79bb0a8ac560c")
BOT_TOKEN = os.getenv("BOT_TOKEN", "6956731651:AAESOyS-FwtDjl04BBM8hGU1QPZ1HSLd7E4")

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://Krishna:pss968048@cluster0.4rfuzro.mongodb.net/?retryWrites=true&w=majority"
)

ADMIN_ID = int(os.getenv("ADMIN_ID", "6258915779"))
INITIAL_CREDITS = int(os.getenv("INITIAL_CREDITS", "5"))
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "10"))
LOOKUP_COST = int(os.getenv("LOOKUP_COST", "1"))

# Force join channels (defaults - replace with your channels or set env vars)
FORCE_JOIN1 = os.getenv("FORCE_JOIN1", "@Ur_rishu_143")
FORCE_JOIN2 = os.getenv("FORCE_JOIN2", "@Vip_robotz")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- BOT SETUP ----------------
app = Client("mobile_info_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------- DATABASE ----------------
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    db = mongo_client.mobile_info_bot
    users_collection = db.users
    logger.info("✅ Connected to MongoDB")
except Exception as e:
    logger.exception(f"❌ MongoDB connection failed: {e}")
    raise SystemExit(1)

# in-memory user states for multi-step flows
user_states = {}

# ---------------- HELPERS ----------------
def add_user(user_id: int, first_name: str, referred_by: int = None):
    """Create user if not exists and credit referrer if provided."""
    if users_collection.find_one({"user_id": user_id}):
        return
    users_collection.insert_one({
        "user_id": user_id,
        "first_name": first_name,
        "credits": INITIAL_CREDITS,
        "referred_by": referred_by,
        "referrals": 0,
        "lookups_done": 0,
        "is_banned": False,
        "is_premium": False
    })
    if referred_by:
        users_collection.update_one(
            {"user_id": referred_by},
            {"$inc": {"credits": REFERRAL_BONUS, "referrals": 1}}
        )

def get_user(user_id: int):
    return users_collection.find_one({"user_id": user_id})

def use_credit(user_id: int):
    user = get_user(user_id)
    if not user:
        return
    if user.get("is_premium"):
        users_collection.update_one({"user_id": user_id}, {"$inc": {"lookups_done": 1}})
    else:
        users_collection.update_one({"user_id": user_id},
                                    {"$inc": {"credits": -LOOKUP_COST, "lookups_done": 1}})

# ---------------- API (INTEGRATED) ----------------
async def fetch_mobile_info(number: str, credits_left):
    """
    Async fetch using aiohttp. Returns a formatted markdown string.
    """
    try:
        url = f"https://privateaadhar.anshppt19.workers.dev/?query={number}"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("API returned non-200: %s", resp.status)
                    return "⚠️ Could not fetch info right now."
                data = await resp.json(content_type=None)  # forgiving

        data_list = data.get("List", {}).get("HiTeckGroop.in", {}).get("Data", [])
        if not data_list:
            return "❌ कोई डिटेल्स नहीं मिली।"

        result = data_list[0]

        # safe getters with fallback
        phone = result.get("Phone") or "-"
        fullname = result.get("FullName") or "-"
        father = result.get("FatherName") or "-"
        docno = result.get("DocNumber") or "-"
        address = result.get("Address") or "-"
        region = result.get("Region") or "-"
        phone2 = result.get("Phone2") or "-"
        phone3 = result.get("Phone3") or "-"
        phone4 = result.get("Phone4") or "-"
        phone5 = result.get("Phone5") or "-"

        message = (
            "━━━━━━━━━━━━━━━\n"
            "*🔍 Lookup Result*\n"
            "━━━━━━━━━━━━━━━\n\n"
            f"📞 *Phone:* `{phone}`\n"
            f"👤 *Name:* {fullname}\n"
            f"👨‍👩‍👦 *Father:* {father}\n"
            f"🆔 *Doc No:* `{docno}`\n\n"
            f"🏠 *Address:*\n`{address}`\n\n"
            f"🌐 *Region:*\n{region}\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📱 *Other Numbers:*\n"
            f"▫️ {phone2}\n"
            f"▫️ {phone3}\n"
            f"▫️ {phone4}\n"
            f"▫️ {phone5}\n"
            "━━━━━━━━━━━━━━━\n"
            f"💳 *Credits Left:* {credits_left}\n"
            f"👨‍💻 *Developer:* Ansh\n"
            "━━━━━━━━━━━━━━━"
        )

        return message

    except Exception as e:
        logger.exception("API Error: %s", e)
        return "⚠️ Could not fetch info right now."

# ---------------- MENU ----------------
async def send_main_menu(message_or_query):
    """
    Accepts Message or CallbackQuery and displays the main menu.
    """
    user = getattr(message_or_query, "from_user", None)
    if user is None:
        logger.warning("send_main_menu called without from_user")
        return

    text = f"👋 Hello {user.first_name}!\nWelcome to *Mobile Info Bot* 📱"
    keyboard = [
        [InlineKeyboardButton("🔍 Mobile Lookup", callback_data="lookup")],
        [InlineKeyboardButton("👥 Referral System", callback_data="referral"),
         InlineKeyboardButton("💰 My Credits", callback_data="credits")],
        [InlineKeyboardButton("📊 My Stats", callback_data="stats"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
    markup = InlineKeyboardMarkup(keyboard)

    if isinstance(message_or_query, Message):
        await message_or_query.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        try:
            await message_or_query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except Exception as e:
            logger.exception("Failed to edit message for menu: %s", e)

# ---------------- UTILS: force join check ----------------
async def is_member_of(chat_username: str, user_id: int, client: Client) -> bool:
    """
    Returns True if user_id is a member of chat_username. Otherwise False.
    """
    try:
        await client.get_chat_member(chat_username, user_id)
        return True
    except UserNotParticipant:
        return False
    except RPCError:
        return False
    except Exception as e:
        logger.exception("is_member_of error: %s", e)
        return False

# ---------------- COMMANDS ----------------
@app.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    referred_by = None
    try:
        if len(message.command) > 1 and message.command[1].isdigit():
            referred_by = int(message.command[1])
    except Exception:
        referred_by = None

    add_user(user.id, user.first_name, referred_by)
    await send_main_menu(message)

@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_text(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    # ---------------- USER LOOKUP ---------------- #
    if state == "awaiting_number":
        user_states.pop(user_id, None)
        user = get_user(user_id)
        if not user:
            return
        if user.get("is_banned"):
            return await message.reply_text("🚫 You are banned.")
        if not user.get("is_premium") and user.get("credits", 0) < LOOKUP_COST:
            return await message.reply_text("❌ Out of credits! Refer friends.")

        number = message.text.strip()
        if not number.isdigit() or len(number) < 6:  # basic validation
            return await message.reply_text("❌ कृपया सही नंबर भेजो।")

        msg = await message.reply_text(f"🔍 Searching `{number}`...")

        # deduct credit & increment lookup
        use_credit(user_id)
        user = get_user(user_id)
        credits_left = "Unlimited" if user.get("is_premium") else user.get("credits", 0)

        # fetch details (async)
        details = await fetch_mobile_info(number, credits_left)

        # send formatted result (markdown preferred)
        try:
            await msg.edit_text(details, parse_mode="Markdown")
        except Exception:
            await msg.edit_text(details)

        # prepare and send txt file (with developer + credits)
        file_content = details + f"\n\nDeveloper: Ansh\n\n"
        file_data = io.BytesIO(file_content.encode("utf-8"))
        file_data.name = f"IndianOsint_{number}.txt"
        try:
            await message.reply_document(file_data, caption="📂 Lookup Data Exported")
        except Exception as e:
            logger.exception("Failed to send document: %s", e)

        return

    # ---------------- ADMIN ACTIONS ---------------- #
    if user_id == ADMIN_ID and state:
        user_states.pop(user_id, None)

        if state == "ban_user":
            try:
                target = int(message.text)
                users_collection.update_one({"user_id": target}, {"$set": {"is_banned": True}})
                return await message.reply_text(f"🚫 User {target} banned.")
            except:
                return await message.reply_text("❌ Invalid user id.")

        elif state == "unban_user":
            try:
                target = int(message.text)
                users_collection.update_one({"user_id": target}, {"$set": {"is_banned": False}})
                return await message.reply_text(f"✅ User {target} unbanned.")
            except:
                return await message.reply_text("❌ Invalid user id.")

        elif state == "premium_user":
            try:
                target = int(message.text)
                users_collection.update_one({"user_id": target}, {"$set": {"is_premium": True}})
                return await message.reply_text(f"💎 User {target} is now PREMIUM.")
            except:
                return await message.reply_text("❌ Invalid user id.")

        elif state == "unpremium_user":
            try:
                target = int(message.text)
                users_collection.update_one({"user_id": target}, {"$set": {"is_premium": False}})
                return await message.reply_text(f"💠 User {target} is no longer premium.")
            except:
                return await message.reply_text("❌ Invalid user id.")

        elif state == "addcredit":
            try:
                target, amount = message.text.split()
                users_collection.update_one({"user_id": int(target)}, {"$inc": {"credits": int(amount)}})
                return await message.reply_text(f"➕ Added {amount} credits to {target}.")
            except:
                return await message.reply_text("❌ Format: `<user_id> <amount>`")

        elif state == "broadcast":
            text = message.text
            sent = 0
            cursor = users_collection.find({}, {"user_id": 1})
            for u in cursor:
                try:
                    await app.send_message(u["user_id"], text)
                    sent += 1
                except Exception:
                    # ignore send errors (blocked, deactivated, etc.)
                    continue
            return await message.reply_text(f"📢 Broadcast sent to {sent} users.")

# ---------------- CALLBACKS ----------------
@app.on_callback_query()
async def callback(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    user = get_user(uid)
    if not user:
        add_user(uid, query.from_user.first_name)
        user = get_user(uid)
    back_btn = InlineKeyboardButton("⬅️ Back", callback_data="back")

    try:
        # --- lookup: first enforce force-join ---
        if query.data == "lookup":
            member1 = await is_member_of(FORCE_JOIN1, uid, client)
            member2 = await is_member_of(FORCE_JOIN2, uid, client)
            if not (member1 and member2):
                kb = [
                    [InlineKeyboardButton(f"Join {FORCE_JOIN1}", url=f"https://t.me/{FORCE_JOIN1.lstrip('@')}"),
                     InlineKeyboardButton(f"Join {FORCE_JOIN2}", url=f"https://t.me/{FORCE_JOIN2.lstrip('@')}")],
                    [InlineKeyboardButton("✅ I Joined", callback_data="check_join")],
                    [back_btn]
                ]
                await query.message.edit_text(
                    "🔒 You must join our required channels before using lookups.\n\n"
                    "➡️ Please join both channels and then press *✅ I Joined*.",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
                await query.answer()
                return

            await query.message.edit_text("📲 Send a mobile number to lookup:", reply_markup=InlineKeyboardMarkup([[back_btn]]))
            user_states[uid] = "awaiting_number"
            await query.answer()
            return

        elif query.data == "check_join":
            member1 = await is_member_of(FORCE_JOIN1, uid, client)
            member2 = await is_member_of(FORCE_JOIN2, uid, client)
            if member1 and member2:
                await query.message.edit_text("✅ Thanks — you joined both channels.\n\nNow send the mobile number to lookup:", reply_markup=InlineKeyboardMarkup([[back_btn]]))
                user_states[uid] = "awaiting_number"
            else:
                missing = []
                if not member1:
                    missing.append(FORCE_JOIN1)
                if not member2:
                    missing.append(FORCE_JOIN2)
                kb = [[InlineKeyboardButton(f"Join {m.lstrip('@')}", url=f"https://t.me/{m.lstrip('@')}")] for m in missing]
                kb.append([InlineKeyboardButton("✅ I Joined", callback_data="check_join")])
                kb.append([back_btn])
                await query.message.edit_text(
                    "❌ You're still not a member of these channels:\n" + "\n".join(missing) + "\n\nPlease join and press ✅ I Joined again.",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            await query.answer()
            return

        elif query.data == "referral":
            me = await client.get_me()
            link = f"https://t.me/{me.username}?start={uid}"
            await query.message.edit_text(
                f"👥 Invite friends & earn {REFERRAL_BONUS} credits!\n\nYour referral link:\n`{link}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Share", url=f"https://t.me/share/url?url={quote_plus(link)}")],
                    [back_btn]
                ]),
                parse_mode="Markdown"
            )

        elif query.data == "credits":
            credits = "Unlimited" if user.get("is_premium") else user.get("credits", 0)
            await query.message.edit_text(f"💰 You have {credits} credits.", reply_markup=InlineKeyboardMarkup([[back_btn]]))

        elif query.data == "stats":
            await query.message.edit_text(
                f"📊 Stats:\nReferrals: {user.get('referrals', 0)}\nLookups: {user.get('lookups_done', 0)}",
                reply_markup=InlineKeyboardMarkup([[back_btn]])
            )

        elif query.data == "help":
            await query.message.edit_text("ℹ️ Send a mobile number or use buttons.", reply_markup=InlineKeyboardMarkup([[back_btn]]))

        elif query.data == "back":
            await send_main_menu(query)

        elif query.data == "admin_panel" and uid == ADMIN_ID:
            stats = {
                "Total Users": users_collection.count_documents({}),
                "Banned Users": users_collection.count_documents({"is_banned": True}),
                "Premium Users": users_collection.count_documents({"is_premium": True}),
                "Total Lookups": sum(u.get("lookups_done", 0) for u in users_collection.find({}))
            }
            keyboard = [
                [InlineKeyboardButton("🚫 Ban User", callback_data="ban_user"),
                 InlineKeyboardButton("✅ Unban User", callback_data="unban_user")],
                [InlineKeyboardButton("💎 Make Premium", callback_data="premium_user"),
                 InlineKeyboardButton("💠 Remove Premium", callback_data="unpremium_user")],
                [InlineKeyboardButton("➕ Add Credits", callback_data="addcredit"),
                 InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")],
                [back_btn]
            ]
            await query.message.edit_text(
                "👑 Admin Panel 👑\n\n📈 Stats:\n" + "\n".join([f"{k}: {v}" for k, v in stats.items()]),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif uid == ADMIN_ID and query.data in ["ban_user", "unban_user", "premium_user", "unpremium_user", "addcredit", "broadcast"]:
            user_states[uid] = query.data
            prompt = {
                "ban_user": "Enter user ID to BAN:",
                "unban_user": "Enter user ID to UNBAN:",
                "premium_user": "Enter user ID to make PREMIUM:",
                "unpremium_user": "Enter user ID to remove PREMIUM:",
                "addcredit": "Enter <user_id> <amount> to add credits:",
                "broadcast": "Send the message to broadcast:"
            }
            await query.message.edit_text(prompt[query.data])
    except Exception as e:
        logger.exception("Callback error: %s", e)
    finally:
        try:
            await query.answer()
        except Exception:
            pass

# ---------------- Web server for Render (health & keepalive) ----------------
async def handle_root(request):
    return web.Response(text="OK")

async def start_web_app():
    port = int(os.getenv("PORT", "8080"))
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")
    return runner

# ---------------- RUN BOT (async) ----------------
async def main():
    # start pyrogram client
    await app.start()
    logger.info("Pyrogram client started")

    # start web server
    runner = await start_web_app()

    # graceful shutdown: use an event and signal handlers
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # register signal handlers (works on Unix hosts like Render)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # some platforms don't support loop.add_signal_handler
            pass

    logger.info("Bot is up — waiting for stop signal (SIGINT / SIGTERM).")
    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down...")
        try:
            await app.stop()
        except Exception as e:
            logger.exception("Error stopping pyrogram client: %s", e)
        try:
            await runner.cleanup()
        except Exception as e:
            logger.exception("Error cleaning up web runner: %s", e)
        logger.info("Clean shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception:
        logger.exception("Bot crashed.")