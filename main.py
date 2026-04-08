import telebot
import pymongo
import os
import logging
from telebot import types
from datetime import datetime, timedelta
import threading
import time
import schedule

# ===================== RAILWAY ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# MongoDB Connection
client = pymongo.MongoClient(MONGO_URI)
db = client["zedox"]
users_col = db["users"]
content_col = db["content"]
config_col = db["config"]
codes_col = db["codes"]

bot = telebot.TeleBot(BOT_TOKEN)
logger = logging.getLogger(__name__)

# Global cache
config_cache = None
force_channels = []

print("🚀 ZEDOX VIP BOT - Railway + MongoDB")
print(f"✅ MongoDB: {MONGO_URI[:30]}...")
print(f"✅ Bot: {BOT_TOKEN[:10]}...")

# ===================== DATABASE LAYER =====================
def get_user(user_id):
    """Get or create user"""
    user = users_col.find_one({"_id": str(user_id)})
    if not user:
        user = {
            "_id": str(user_id),
            "points": 0,
            "vip": False,
            "vip_expiry": None,
            "referrals": [],
            "referred_by": None,
            "join_date": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat()
        }
        users_col.insert_one(user)
        print(f"✅ New user: {user_id}")
    return user

def update_user(user_id, update_data):
    """Update user data"""
    update_data["last_active"] = datetime.now().isoformat()
    users_col.update_one({"_id": str(user_id)}, {"$set": update_data})

def get_content():
    """Get all content"""
    content_doc = content_col.find_one({"_id": "content"})
    if content_doc:
        return content_doc["data"]
    return {"free": {}, "vip": {}, "apps": {}}

def update_content(content_data):
    """Update content database"""
    content_col.replace_one(
        {"_id": "content"}, 
        {"_id": "content", "data": content_data}, 
        upsert=True
    )

def get_config():
    """Get bot config"""
    global config_cache
    if config_cache is None:
        config_doc = config_col.find_one({"_id": "config"})
        config_cache = config_doc or {
            "force_channels": [],
            "force_channels_data": [],
            "notification": True,
            "vip_message": "🔥 *VIP REQUIRED*\n\n💎 Become VIP for premium access!",
            "welcome_message": "🎉 Welcome to ZEDOX VIP BOT!\n\n🚀 Premium methods & apps await!",
            "ref_reward": 50,
            "main_buttons": []
        }
    return config_cache

def update_config(config_data):
    """Update config"""
    global config_cache
    config_col.replace_one({"_id": "config"}, config_data, upsert=True)
    config_cache = config_data

def get_codes():
    """Get redeem codes"""
    codes_doc = codes_col.find_one({"_id": "codes"})
    return codes_doc["data"] if codes_doc else {}

def update_codes(codes_data):
    """Update codes"""
    codes_col.replace_one({"_id": "codes"}, {"_id": "codes", "data": codes_data}, upsert=True)

# ===================== CORE LOGIC =====================
def is_vip(user_id):
    user = get_user(user_id)
    if user.get("vip") and user.get("vip_expiry"):
        try:
            expiry = datetime.fromisoformat(user["vip_expiry"])
            return datetime.now() < expiry
        except:
            return False
    return user.get("vip", False)

def is_member(user_id):
    config = get_config()
    for i, channel in enumerate(config["force_channels"]):
        if channel == 0:  # Custom WhatsApp link
            continue
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True

def safe_copy_message(chat_id, from_chat_id, message_id):
    """Safely copy message"""
    try:
        bot.copy_message(chat_id, from_chat_id, message_id)
        return True
    except Exception as e:
        logger.error(f"Copy failed: {e}")
        return False

# ===================== KEYBOARDS =====================
def main_menu_keyboard(is_admin=False):
    content = get_content()
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    # Row 1
    keyboard.row(
        types.InlineKeyboardButton(f"📂 FREE ({len(content.get('free', {}))})", callback_data="free_methods"),
        types.InlineKeyboardButton(f"💎 VIP ({len(content.get('vip', {}))})", callback_data="vip_methods")
    )
    
    # Row 2
    keyboard.row(
        types.InlineKeyboardButton(f"📦 APPS ({len(content.get('apps', {}))})", callback_data="apps"),
        types.InlineKeyboardButton("💰 POINTS", callback_data="points")
    )
    
    # Row 3
    keyboard.row(
        types.InlineKeyboardButton("⭐ BUY VIP", callback_data="buy_vip"),
        types.InlineKeyboardButton("🎁 REFERRAL", callback_data="referral")
    )
    
    # Row 4
    keyboard.row(
        types.InlineKeyboardButton("👤 ACCOUNT", callback_data="account"),
        types.InlineKeyboardButton("🆔 CHAT ID", callback_data="chat_id")
    )
    keyboard.row(types.InlineKeyboardButton("🏆 COUPON", callback_data="redeem"))
    
    # Custom buttons
    config = get_config()
    for btn in config.get("main_buttons", [])[:4]:
        keyboard.add(types.InlineKeyboardButton(btn["text"], url=btn["url"]))
    
    if is_admin:
        keyboard.add(types.InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin_panel"))
    
    return keyboard

def get_force_join_keyboard():
    config = get_config()
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for channel, data in zip(config["force_channels"], config["force_channels_data"]):
        btn_text = data.get("name", "📢 Join Channel")
        btn_url = data.get("url", f"https://t.me/c/{str(channel)[4:]}/1")
        keyboard.add(types.InlineKeyboardButton(btn_text, url=btn_url))
    keyboard.add(types.InlineKeyboardButton("🔄 I Joined ✅", callback_data="check_join"))
    return keyboard

def category_keyboard(category):
    content = get_content()
    data = content.get(category, {})
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    for i, folder_name in enumerate(sorted(data.keys()), 1):
        folder_data = data[folder_name]
        price = folder_data.get("price", 0)
        price_text = f"💰 {price} pts" if price > 0 else "🆓 FREE"
        callback = f"folder_{category}_{folder_name}"
        keyboard.add(types.InlineKeyboardButton(f"#{i} {folder_name}\n{price_text}", callback_data=callback))
    
    keyboard.add(types.InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu"))
    return keyboard

# ===================== ADMIN STATES =====================
admin_states = {}

print("✅ Database layer ready")
print("✅ Keyboards ready")
# ===================== USER SYSTEM =====================
def get_referral_stats(user_id):
    """Get user referral statistics"""
    user = get_user(user_id)
    total_refs = len(user.get("referrals", []))
    config = get_config()
    ref_points = total_refs * config["ref_reward"]
    return total_refs, ref_points

def send_folder(user_id, category, folder_name):
    """Send folder files with points check"""
    content = get_content()
    folder_data = content.get(category, {}).get(folder_name, {})
    
    if not folder_data or "files" not in folder_data:
        bot.send_message(user_id, "❌ Folder not found!")
        return False
    
    price = folder_data.get("price", 0)
    user = get_user(user_id)
    isvip = is_vip(user_id)
    
    # Points deduction
    if price > 0 and not isvip:
        if user["points"] < price:
            bot.send_message(user_id, f"❌ Insufficient points!\n💰 Need: {price}\n💳 Have: {user['points']}")
            return False
        update_user(user_id, {"points": user["points"] - price})
    
    # Send files
    files = folder_data["files"]
    sent_count = 0
    for file_info in files:
        if safe_copy_message(user_id, file_info["chat"], file_info["msg"]):
            sent_count += 1
    
    config = get_config()
    if config["notification"] and sent_count > 0:
        bot.send_message(user_id, f"✅ Delivered {sent_count} files!")
    
    return True

# ===================== START COMMAND =====================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    args = message.text.split()
    
    # 🔥 REFERRAL SYSTEM
    if len(args) > 1:
        try:
            ref_id = int(args[1])
            if ref_id != user_id:
                user = get_user(user_id)
                referrer = get_user(ref_id)
                
                if not user.get("referred_by"):
                    # First time referral
                    user["referred_by"] = ref_id
                    referrer["referrals"].append(str(user_id))
                    
                    config = get_config()
                    reward = config["ref_reward"]
                    update_user(ref_id, {"points": referrer["points"] + reward})
                    
                    # Notify referrer
                    try:
                        bot.send_message(ref_id, 
                            f"🎉 *NEW REFERRAL!*\n"
                            f"+{reward} points!\n"
                            f"👥 Total: {len(referrer['referrals'])} referrals",
                            parse_mode='Markdown')
                    except:
                        pass
                    print(f"✅ Referral: {user_id} <- {ref_id}")
        except ValueError:
            pass
    
    # Force join check
    if not is_member(user_id):
        config = get_config()
        bot.send_message(
            user_id,
            "🚫 *ACCESS DENIED!*\n\n"
            "📢 Join all channels to use the bot!",
            reply_markup=get_force_join_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Welcome message
    user = get_user(user_id)
    status = "👑 VIP" if is_vip(user_id) else "👤 FREE"
    config = get_config()
    
    text = f"{config['welcome_message']}\n\n"
    text += f"*{status} USER*\n"
    text += f"💰 Points: `{user['points']}`\n"
    
    refs, _ = get_referral_stats(user_id)
    if refs > 0:
        text += f"👥 Referrals: `{refs}`"
    
    bot.send_message(
        user_id, 
        text, 
        reply_markup=main_menu_keyboard(user_id == ADMIN_ID),
        parse_mode='Markdown'
    )

# ===================== CALLBACK: FORCE JOIN =====================
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join(call):
    user_id = call.from_user.id
    if is_member(user_id):
        user = get_user(user_id)
        config = get_config()
        text = f"{config['welcome_message']}\n\n💰 `{user['points']}` pts"
        bot.edit_message_text(
            text,
            user_id,
            call.message.message_id,
            reply_markup=main_menu_keyboard(user_id == ADMIN_ID),
            parse_mode='Markdown'
        )
    else:
        bot.answer_callback_query(call.id, "❌ Still need to join all channels!", show_alert=True)

# ===================== CHAT ID =====================
@bot.callback_query_handler(func=lambda call: call.data == "chat_id")
def show_chat_id(call):
    bot.answer_callback_query(
        call.id, 
        f"🆔 Your Chat ID: `{call.from_user.id}`", 
        show_alert=True,
        parse_mode='Markdown'
    )

# ===================== ACCOUNT SYSTEM =====================
@bot.callback_query_handler(func=lambda call: call.data == "account")
def account_menu(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    refs, ref_pts = get_referral_stats(user_id)
    join_date = datetime.fromisoformat(user["join_date"]).strftime("%d/%m/%Y")
    
    vip_status = "👑 LIFETIME VIP" if is_vip(user_id) and not user.get("vip_expiry") else "👤 FREE"
    if is_vip(user_id) and user.get("vip_expiry"):
        expiry = datetime.fromisoformat(user["vip_expiry"]).strftime("%d/%m/%Y")
        vip_status = f"👑 VIP (Expires: {expiry})"
    
    text = f"""👤 *YOUR ACCOUNT*

🆔 ID: `{user_id}`
{vip_status}
💰 Balance: `{user['points']}` pts
👥 Referrals: `{refs}` (+{ref_pts} earned)
📅 Joined: `{join_date}`

🔗 *Referral Link:*
`https://t.me/{bot.get_me().username}?start={user_id}`"""
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("💳 Points", callback_data="points"),
        types.InlineKeyboardButton("🎁 Referrals", callback_data="referral")
    )
    keyboard.row(
        types.InlineKeyboardButton("⭐ Buy VIP", callback_data="buy_vip"),
        types.InlineKeyboardButton("🏆 Coupon", callback_data="redeem")
    )
    keyboard.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))
    
    bot.edit_message_text(text, user_id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')

# ===================== REFERRAL MENU =====================
@bot.callback_query_handler(func=lambda call: call.data == "referral")
def referral_menu(call):
    user_id = call.from_user.id
    refs, ref_pts = get_referral_stats(user_id)
    config = get_config()
    
    ref_link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    
    text = f"""🎁 *REFERRAL DASHBOARD*

💎 *Your Stats:*
👥 Total Referrals: `{refs}`
💰 Earnings: `{ref_pts}` pts
💳 Reward per ref: `{config['ref_reward']}` pts

🔗 *Share this link:*
`{ref_link}`

⚡ *Invite friends = Earn points!*"""
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("📤 Share Link", url=ref_link),
        types.InlineKeyboardButton("👥 My Referrals", callback_data="my_refs")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="account"))
    
    bot.edit_message_text(text, user_id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "my_refs")
def my_referrals(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    referrals = user.get("referrals", [])
    
    if not referrals:
        text = "👥 No referrals yet!\n\nShare your link to earn points!"
    else:
        text = f"👥 *YOUR REFERRALS* ({len(referrals)})\n\n"
        for i, ref_id in enumerate(referrals[:10], 1):
            ref_user = get_user(ref_id)
            text += f"{i}. `{ref_id}` - {ref_user.get('points', 0)} pts\n"
        if len(referrals) > 10:
            text += f"\n... +{len(referrals)-10} more"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔗 Get Link", callback_data="referral"))
    
    bot.edit_message_text(text, user_id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')

print("✅ User system ready")
print("✅ Referral system ready")
print("✅ Force join ready")
# ===================== CONTENT SYSTEM =====================
def category_menu_keyboard(category):
    """Generate category keyboard with numbers"""
    content = get_content()
    data = content.get(category, {})
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    sorted_folders = sorted(data.keys())
    for i, folder_name in enumerate(sorted_folders, 1):
        folder_data = data[folder_name]
        price = folder_data.get("price", 0)
        price_text = f"💰 {price} pts" if price > 0 else "🆓 FREE"
        
        callback = f"folder_{category}_{folder_name}"
        btn_text = f"#{i} {folder_name.split('/')[-1]}\n{price_text}"
        keyboard.add(types.InlineKeyboardButton(btn_text, callback_data=callback))
    
    keyboard.add(types.InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu"))
    return keyboard

# ===================== CATEGORY CALLBACKS =====================
@bot.callback_query_handler(func=lambda call: call.data in ["free_methods", "vip_methods", "apps"])
def category_callback(call):
    user_id = call.from_user.id
    category = {
        "free_methods": "free",
        "vip_methods": "vip", 
        "apps": "apps"
    }[call.data]
    
    if call.data == "vip_methods" and not is_vip(user_id):
        config = get_config()
        bot.edit_message_text(
            config["vip_message"], 
            user_id, 
            call.message.message_id, 
            parse_mode='Markdown'
        )
        return
    
    title = {
        "free": "📂 FREE METHODS",
        "vip": "💎 VIP METHODS", 
        "apps": "📦 PREMIUM APPS"
    }[category]
    
    keyboard = category_menu_keyboard(category)
    bot.edit_message_text(title, user_id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')

# ===================== FOLDER ACCESS =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("folder_"))
def folder_access(call):
    user_id = call.from_user.id
    parts = call.data.split("_", 2)
    category, folder_name = parts[1], parts[2]
    
    if send_folder(user_id, category, folder_name):
        bot.answer_callback_query(call.id, f"✅ Files sent from {folder_name}!")
    else:
        bot.answer_callback_query(call.id, "❌ Access denied!")

# ===================== POINTS SYSTEM =====================
@bot.callback_query_handler(func=lambda call: call.data == "points")
def points_menu(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    refs, ref_pts = get_referral_stats(user_id)
    
    text = f"""💰 *POINTS DASHBOARD*

💳 *Balance:* `{user['points']}` pts
👥 *Referrals:* `{refs}` (+{ref_pts} earned)

🔥 *Earn Points:*
- 🎁 Refer friends ({get_config()['ref_reward']} pts each)
- 🏆 Redeem coupons
- ⭐ Buy VIP with points"""
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("🎁 Referral", callback_data="referral"),
        types.InlineKeyboardButton("🏆 Redeem", callback_data="redeem")
    )
    keyboard.row(
        types.InlineKeyboardButton("⭐ Buy VIP", callback_data="buy_vip"),
        types.InlineKeyboardButton("👤 Account", callback_data="account")
    )
    keyboard.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))
    
    bot.edit_message_text(text, user_id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')

# ===================== REDEEM SYSTEM =====================
def generate_codes(amount, points_per_code, max_uses=1):
    """Admin generates redeem codes"""
    codes = get_codes()
    new_codes = {}
    
    for i in range(amount):
        code = f"ZEDOX-{int(time.time()*1000)%1000000:06d}".upper()
        new_codes[code] = {
            "points": points_per_code,
            "max_uses": max_uses,
            "uses_left": max_uses,
            "created": datetime.now().isoformat()
        }
    
    codes.update(new_codes)
    update_codes(codes)
    return list(new_codes.keys())

@bot.callback_query_handler(func=lambda call: call.data == "redeem")
def redeem_menu(call):
    user_id = call.from_user.id
    bot.send_message(user_id, "🏆 Send your coupon code:")
    admin_states[user_id] = {"action": "user_redeem"}

@bot.message_handler(func=lambda m: admin_states.get(m.from_user.id, {}).get("action") == "user_redeem")
def handle_redeem(message):
    user_id = message.from_user.id
    code = message.text.strip().upper()
    
    codes = get_codes()
    if code in codes:
        code_data = codes[code]
        if code_data["uses_left"] > 0:
            points = code_data["points"]
            user = get_user(user_id)
            update_user(user_id, {"points": user["points"] + points})
            
            code_data["uses_left"] -= 1
            update_codes(codes)
            
            bot.reply_to(message, f"✅ *REDEEMED!*\n💰 +{points} points!\n💳 New balance: `{get_user(user_id)['points']}`", parse_mode='Markdown')
        else:
            bot.reply_to(message, "❌ Code used up!")
    else:
        bot.reply_to(message, "❌ Invalid code!")
    
    del admin_states[user_id]

# ===================== MAIN MENU NAVIGATION =====================
@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def main_menu_nav(call):
    user_id = call.from_user.id
    bot.edit_message_text(
        "🏠 *MAIN MENU*\n\nChoose your category:",
        user_id,
        call.message.message_id,
        reply_markup=main_menu_keyboard(user_id == ADMIN_ID),
        parse_mode='Markdown'
    )

print("✅ Content system ready")
print("✅ Points system ready")
print("✅ Categories ready")
print("✅ Redeem system ready")
# ===================== ADMIN PANEL =====================
def admin_panel_keyboard():
    """Full admin panel"""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    
    # VIP & Points
    keyboard.row(
        types.InlineKeyboardButton("👑 VIP MGMT", callback_data="admin_vip"),
        types.InlineKeyboardButton("💰 POINTS", callback_data="admin_points")
    )
    
    # Content & Broadcast
    keyboard.row(
        types.InlineKeyboardButton("📁 UPLOAD", callback_data="admin_upload"),
        types.InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")
    )
    
    # Channels & Settings
    keyboard.row(
        types.InlineKeyboardButton("🔗 FORCE JOIN", callback_data="admin_forcejoin"),
        types.InlineKeyboardButton("⚙️ SETTINGS", callback_data="admin_settings")
    )
    
    # Stats
    keyboard.row(
        types.InlineKeyboardButton("📊 STATS", callback_data="admin_stats"),
        types.InlineKeyboardButton("🗑️ DELETE", callback_data="admin_delete")
    )
    
    keyboard.add(types.InlineKeyboardButton("🏠 MAIN MENU", callback_data="main_menu"))
    return keyboard

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_panel")
def admin_panel(call):
    bot.edit_message_text(
        "⚙️ *ADMIN PANEL*\n\n"
        "👑 VIP Management\n"
        "💰 Points System\n"
        "📁 Content Upload\n"
        "📢 Mass Broadcast\n"
        "🔗 Force Join\n"
        "📊 Statistics",
        call.from_user.id,
        call.message.message_id,
        reply_markup=admin_panel_keyboard(),
        parse_mode='Markdown'
    )

# ===================== VIP MANAGEMENT =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_vip")
def admin_vip_menu(call):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("➕ Add VIP", callback_data="admin_add_vip"),
        types.InlineKeyboardButton("➖ Remove VIP", callback_data="admin_remove_vip")
    )
    keyboard.row(
        types.InlineKeyboardButton("⏰ Set Expiry", callback_data="admin_vip_expiry"),
        types.InlineKeyboardButton("📝 VIP Message", callback_data="admin_vip_msg")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
    
    bot.edit_message_text("👑 *VIP MANAGEMENT*", call.from_user.id, call.message.message_id, 
                         reply_markup=keyboard, parse_mode='Markdown')

# ===================== CONTENT UPLOAD =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_upload")
def admin_upload(call):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("📂 FREE", callback_data="upload_free"),
        types.InlineKeyboardButton("💎 VIP", callback_data="upload_vip")
    )
    keyboard.row(
        types.InlineKeyboardButton("📦 APPS", callback_data="upload_apps"),
        types.InlineKeyboardButton("➕ Add Files", callback_data="admin_add_files")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
    
    bot.edit_message_text(
        "📁 *UPLOAD CONTENT*\n\n"
        "1️⃣ Forward files from PRIVATE CHANNEL\n"
        "2️⃣ Bot auto-captures\n"
        "3️⃣ Set folder name & price",
        call.from_user.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data.startswith("upload_"))
def upload_category(call):
    category_map = {
        "upload_free": "free",
        "upload_vip": "vip", 
        "upload_apps": "apps"
    }
    category = category_map[call.data]
    
    admin_states[call.from_user.id] = {
        "action": "upload_wait",
        "category": category
    }
    
    bot.edit_message_text(
        f"📤 *{call.data.upper()}*\n\n"
        "✅ Forward files from your PRIVATE channel now!\n"
        "Bot will ask for folder name next.",
        call.from_user.id,
        call.message.message_id,
        parse_mode='Markdown'
    )

# ===================== ADMIN MESSAGE HANDLER =====================
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID)
def admin_message_handler(message):
    user_id = message.from_user.id
    state = admin_states.get(user_id, {})
    
    # VIP Management
    if state.get("action") == "add_vip":
        try:
            target_id = int(message.text)
            update_user(target_id, {"vip": True, "vip_expiry": None})
            bot.reply_to(message, f"✅ `{target_id}` is now LIFETIME VIP!", parse_mode='Markdown')
        except:
            bot.reply_to(message, "❌ Invalid Chat ID!")
        del admin_states[user_id]
        return
    
    if state.get("action") == "remove_vip":
        try:
            target_id = int(message.text)
            update_user(target_id, {"vip": False, "vip_expiry": None})
            bot.reply_to(message, f"✅ VIP removed from `{target_id}`!", parse_mode='Markdown')
        except:
            bot.reply_to(message, "❌ Invalid Chat ID!")
        del admin_states[user_id]
        return
    
    # Points management
    if state.get("action") == "give_points":
        try:
            parts = message.text.split()
            target_id, amount = int(parts[0]), int(parts[1])
            user = get_user(target_id)
            update_user(target_id, {"points": user["points"] + amount})
            bot.reply_to(message, f"✅ +{amount} points to `{target_id}`!\nNew: `{get_user(target_id)["points"]}`", parse_mode='Markdown')
        except:
            bot.reply_to(message, "❌ Format: `ID AMOUNT`")
        del admin_states[user_id]
        return
    
    # Content upload
    if state.get("action") == "upload_folder_name":
        folder_name = message.text.strip()
        admin_states[user_id]["folder_name"] = folder_name
        admin_states[user_id]["action"] = "upload_price"
        bot.reply_to(message, f"📁 `{folder_name}`\n\n💰 Enter price (0 = FREE):", parse_mode='Markdown')
        return
    
    if state.get("action") == "upload_price":
        try:
            price = int(message.text)
            category = admin_states[user_id]["category"]
            folder_name = admin_states[user_id]["folder_name"]
            forwarded_msg = admin_states[user_id]["forwarded_msg"]
            
            content = get_content()
            if category not in content:
                content[category] = {}
            
            file_info = {
                "chat": forwarded_msg.forward_from_chat.id if forwarded_msg.forward_from_chat else forwarded_msg.chat.id,
                "msg": forwarded_msg.message_id
            }
            
            content[category][folder_name] = {
                "files": [file_info],
                "price": price,
                "expiry": None
            }
            update_content(content)
            
            bot.reply_to(message, 
                f"✅ *FOLDER CREATED!*\n\n"
                f"📁 `{folder_name}`\n"
                f"💰 `{price}` points\n"
                f"📂 `{category.upper()}`\n\n"
                f"Users can now access!",
                parse_mode='Markdown')
            
        except:
            bot.reply_to(message, "❌ Invalid price!")
        
        del admin_states[user_id]
        return

# ===================== FORWARDED MESSAGE HANDLER =====================
@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(m.from_user.id, {}).get("action") == "upload_wait")
def handle_forwarded_content(message):
    user_id = message.from_user.id
    state = admin_states[user_id]
    
    # Capture forwarded message
    admin_states[user_id]["forwarded_msg"] = message
    admin_states[user_id]["action"] = "upload_folder_name"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("✅ Use This File", callback_data="confirm_upload"))
    
    bot.reply_to(
        message,
        f"📁 *FILE CAPTURED!*\n\n"
        f"Category: `{state['category']}`\n\n"
        "Send folder name:",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "confirm_upload")
def confirm_upload(call):
    bot.answer_callback_query(call.id, "✅ Ready for folder name!")

print("✅ Admin panel ready")
print("✅ VIP management ready")
print("✅ Content upload ready")
# ===================== BROADCAST SYSTEM =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_broadcast")
def broadcast_menu(call):
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("📢 ALL USERS", callback_data="bc_all"),
        types.InlineKeyboardButton("👑 VIP ONLY", callback_data="bc_vip")
    )
    keyboard.row(
        types.InlineKeyboardButton("👤 FREE ONLY", callback_data="bc_free"),
        types.InlineKeyboardButton("📊 STATS FIRST", callback_data="admin_stats")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
    
    bot.edit_message_text(
        "📢 *BROADCAST*\n\n"
        "Send TEXT/PHOTO/VIDEO after selecting target.\n"
        "Works with any media!",
        call.from_user.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

def broadcast_message(target_type, content):
    """Broadcast to users"""
    users_cursor = users_col.find()
    success = 0
    
    for user_doc in users_cursor:
        user_id = int(user_doc["_id"])
        try:
            # Filter by target
            if target_type == "vip" and not is_vip(user_id):
                continue
            if target_type == "free" and is_vip(user_id):
                continue
            
            # Send content
            if hasattr(content, 'photo'):
                bot.send_photo(user_id, content.photo[-1].file_id, caption=content.caption)
            elif hasattr(content, 'video'):
                bot.send_video(user_id, content.video.file_id, caption=content.caption)
            elif hasattr(content, 'document'):
                bot.send_document(user_id, content.document.file_id, caption=content.caption)
            else:
                bot.send_message(user_id, content.text)
            
            success += 1
            time.sleep(0.05)  # Rate limit
        except:
            pass
    
    return success

@bot.message_handler(content_types=['text', 'photo', 'video', 'document'], func=lambda m: m.from_user.id == ADMIN_ID)
def handle_broadcast(message):
    user_id = message.from_user.id
    state = admin_states.get(user_id, {})
    
    if state.get("action", "").startswith("bc_"):
        target_type = state["action"].split("_")[1]
        success = broadcast_message(target_type, message)
        
        target_name = {"all": "ALL", "vip": "VIP", "free": "FREE"}[target_type]
        bot.reply_to(message, f"✅ *BROADCAST COMPLETE*\n📢 Sent to {success} {target_name} users!", parse_mode='Markdown')
        del admin_states[user_id]

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data.startswith("bc_"))
def select_broadcast_target(call):
    target_type = call.data.split("_")[1]
    admin_states[call.from_user.id] = {"action": f"bc_{target_type}"}
    bot.edit_message_text(
        f"📢 *BROADCAST TO {target_type.upper()}*\n\n"
        "Send your TEXT/PHOTO/VIDEO now:",
        call.from_user.id,
        call.message.message_id,
        parse_mode='Markdown'
    )

# ===================== FORCE JOIN MANAGEMENT =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_forcejoin")
def forcejoin_menu(call):
    config = get_config()
    channels_text = "\n".join([
        f"{i+1}. {data.get('name', str(ch))}" 
        for i, (ch, data) in enumerate(zip(config["force_channels"], config["force_channels_data"]))
    ]) or "No channels"
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton("➕ ADD CHANNEL", callback_data="force_add"),
        types.InlineKeyboardButton("➖ REMOVE", callback_data="force_remove")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
    
    bot.edit_message_text(
        f"🔗 *FORCE JOIN* ({len(config['force_channels'])})\n\n{channels_text}",
        call.from_user.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "force_add")
def force_add(call):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("📱 WhatsApp/Custom", callback_data="force_custom"),
        types.InlineKeyboardButton("📢 Telegram Channel", callback_data="force_telegram")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Cancel", callback_data="admin_forcejoin"))
    
    bot.edit_message_text(
        "🔗 *ADD CHANNEL*\n\n"
        "• Telegram: @channel or -100123456\n"
        "• WhatsApp: Full URL",
        call.from_user.id,
        call.message.message_id,
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(m.from_user.id, {}).get("action") == "force_add_telegram")
def add_telegram_channel(message):
    user_id = message.from_user.id
    channel_input = message.text.strip().lstrip("@")
    
    try:
        if channel_input.startswith("-100"):
            channel_id = int(channel_input)
        else:
            chat = bot.get_chat(channel_input)
            channel_id = chat.id
        
        config = get_config()
        config["force_channels"].append(channel_id)
        config["force_channels_data"].append({
            "name": f"📢 {chat.title}",
            "url": f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(channel_id)[4:]}/1"
        })
        update_config(config)
        
        bot.reply_to(message, f"✅ Added `{channel_id}`!", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid channel!")
    
    del admin_states[user_id]

# ===================== REDEEM CODES - ADMIN =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_codes")
def admin_codes(call):
    admin_states[call.from_user.id] = {"action": "gen_codes"}
    bot.edit_message_text(
        "🎫 *GENERATE CODES*\n\n"
        "Format: `AMOUNT POINTS USES`\n"
        "Example: `10 100 1` (10 codes, 100pts, 1 use each)",
        call.from_user.id,
        call.message.message_id,
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(m.from_user.id, {}).get("action") == "gen_codes")
def generate_admin_codes(message):
    try:
        parts = message.text.split()
        amount, points, uses = int(parts[0]), int(parts[1]), int(parts[2])
        codes = generate_codes(amount, points, uses)
        
        text = f"✅ *{amount} CODES GENERATED!*\n\n"
        for code in codes:
            text += f"`{code}` → {points}pts ({uses} uses)\n"
        
        bot.reply_to(message, text, parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Format: `AMOUNT POINTS USES`")
    
    del admin_states[message.from_user.id]

# ===================== STATISTICS =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_stats")
def admin_stats(call):
    # Total users
    total_users = users_col.count_documents({})
    
    # VIP count
    vip_count = users_col.count_documents({"vip": True})
    free_count = total_users - vip_count
    
    # Content stats
    content = get_content()
    total_content = sum(len(cat) for cat in content.values())
    
    text = f"""📊 *STATISTICS*

👥 Total Users: `{total_users}`
👑 VIP Users: `{vip_count}`
👤 Free Users: `{free_count}`

📁 Content:
Free: `{len(content.get('free', {}))}`
VIP: `{len(content.get('vip', {}))}`
Apps: `{len(content.get('apps', {}))}`
Total: `{total_content}` folders"""
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel"))
    
    bot.edit_message_text(text, call.from_user.id, call.message.message_id, 
                         reply_markup=keyboard, parse_mode='Markdown')

print("✅ Broadcast system ready")
print("✅ Force join management ready")
print("✅ Admin codes ready")
print("✅ Statistics ready")
# ===================== SETTINGS =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_settings")
def admin_settings(call):
    config = get_config()
    notif_status = "✅ ON" if config["notification"] else "❌ OFF"
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        types.InlineKeyboardButton(f"🔔 Notifications {notif_status}", callback_data="toggle_notify"),
        types.InlineKeyboardButton("📝 Welcome Msg", callback_data="set_welcome")
    )
    keyboard.row(
        types.InlineKeyboardButton("💰 Ref Reward", callback_data="set_ref_reward"),
        types.InlineKeyboardButton("🔘 Main Buttons", callback_data="main_buttons")
    )
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
    
    text = f"""⚙️ *SETTINGS*

🔔 Notifications: {notif_status}
💰 Ref Reward: `{config['ref_reward']}` pts
🔗 Custom Buttons: `{len(config.get('main_buttons', []))}`"""
    
    bot.edit_message_text(text, call.from_user.id, call.message.message_id, 
                         reply_markup=keyboard, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "toggle_notify")
def toggle_notifications(call):
    config = get_config()
    config["notification"] = not config["notification"]
    update_config(config)
    status = "✅ ON" if config["notification"] else "❌ OFF"
    bot.answer_callback_query(call.id, f"🔔 Notifications: {status}")

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "set_welcome")
def set_welcome_msg(call):
    admin_states[call.from_user.id] = {"action": "set_welcome"}
    bot.send_message(call.from_user.id, "📝 Send new welcome message:")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(m.from_user.id, {}).get("action") == "set_welcome")
def handle_welcome_msg(message):
    config = get_config()
    config["welcome_message"] = message.text
    update_config(config)
    bot.reply_to(message, "✅ Welcome message updated!")
    del admin_states[message.from_user.id]

# ===================== CUSTOM MAIN BUTTONS =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "main_buttons")
def main_buttons_menu(call):
    config = get_config()
    buttons_text = "\n".join([f"{i+1}. {btn['text']}" for i, btn in enumerate(config.get("main_buttons", []))]) or "No buttons"
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("➕ Add Button", callback_data="add_main_btn"))
    if config.get("main_buttons"):
        keyboard.add(types.InlineKeyboardButton("🗑️ Clear All", callback_data="clear_main_btns"))
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_settings"))
    
    bot.edit_message_text(
        f"🔘 *MAIN PAGE BUTTONS* ({len(config.get('main_buttons', []))})\n\n{buttons_text}",
        call.from_user.id,
        call.message.message_id,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "add_main_btn")
def add_main_button(call):
    admin_states[call.from_user.id] = {"action": "add_main_btn"}
    bot.send_message(call.from_user.id, "🔘 Send: `BUTTON_TEXT URL`\nEx: `Join WhatsApp https://chat.whatsapp.com/ABC`")

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(m.from_user.id, {}).get("action") == "add_main_btn")
def handle_add_main_btn(message):
    try:
        parts = message.text.split(" ", 1)
        text, url = parts[0], parts[1]
        
        config = get_config()
        config["main_buttons"].append({"text": text, "url": url})
        update_config(config)
        
        bot.reply_to(message, f"✅ Added: `{text}` → {url}", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Format: `TEXT URL`")
    del admin_states[message.from_user.id]

# ===================== BACKGROUND WORKER =====================
def worker_cleanup():
    """Hourly cleanup tasks"""
    now = datetime.now()
    
    # Remove expired VIPs
    expired = users_col.update_many(
        {"vip": True, "vip_expiry": {"$lt": now.isoformat()}},
        {"$set": {"vip": False}}
    )
    
    # Check expired content (future feature)
    content = get_content()
    for category in content:
        for folder in list(content[category].keys()):
            folder_data = content[category][folder]
            if folder_data.get("expiry") and datetime.fromisoformat(folder_data["expiry"]) < now:
                del content[category][folder]
    
    update_content(content)
    
    logger.info(f"Worker: Cleaned {expired.modified_count} VIPs")
    print(f"🧹 Worker: {expired.modified_count} VIPs cleaned")

def run_scheduler():
    """Railway background worker"""
    schedule.every().hour.do(worker_cleanup)
    schedule.every().day.at("03:00").do(worker_cleanup)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# ===================== START WORKER =====================
def start_background_worker():
    worker_thread = threading.Thread(target=run_scheduler, daemon=True)
    worker_thread.start()
    print("✅ Background worker started")

# ===================== ERROR HANDLING =====================
@bot.message_handler(func=lambda message: True)
def fallback_handler(message):
    """Catch all other messages"""
    user_id = message.from_user.id
    
    # Block sharing
    if message.contact or message.location or message.poll:
        bot.reply_to(message, "🚫 Privacy protected!")
        return
    
    # Force join for non-commands
    if not is_member(user_id) and not message.text.startswith('/'):
        bot.reply_to(message, "🚫 Join channels first!", reply_markup=get_force_join_keyboard())
        return

# ===================== CALLBACK FALLBACK =====================
@bot.callback_query_handler(func=lambda call: True)
def callback_fallback(call):
    """Safe callback handler"""
    try:
        # Route to specific handlers (all previous ones)
        pass
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "⚠️ Try again!")

print("✅ Settings system ready")
print("✅ Background worker ready")
print("✅ Error handling ready")
# ===================== FINAL ADMIN FEATURES =====================
@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data.startswith("admin_"))
def final_admin_handlers(call):
    data = call.data
    
    if data == "admin_points":
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.row(
            types.InlineKeyboardButton("➕ Give Points", callback_data="give_points"),
            types.InlineKeyboardButton("🔢 Set Points", callback_data="set_points")
        )
        keyboard.row(
            types.InlineKeyboardButton("🎫 Generate Codes", callback_data="admin_codes"),
            types.InlineKeyboardButton("💰 Ref Reward", callback_data="set_ref_reward")
        )
        keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel"))
        bot.edit_message_text("💰 *POINTS MANAGEMENT*", call.from_user.id, call.message.message_id, reply_markup=keyboard, parse_mode='Markdown')
    
    elif data == "give_points":
        admin_states[call.from_user.id] = {"action": "give_points"}
        bot.send_message(call.from_user.id, "💰 Send: `CHAT_ID AMOUNT`\nEx: `123456 100`")
    
    elif data == "set_points":
        admin_states[call.from_user.id] = {"action": "set_points"}
        bot.send_message(call.from_user.id, "💰 Send: `CHAT_ID AMOUNT`\nEx: `123456 500`")

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_add_vip")
def admin_add_vip(call):
    admin_states[call.from_user.id] = {"action": "add_vip"}
    bot.send_message(call.from_user.id, "👑 Send Chat ID to make VIP:")

@bot.callback_query_handler(func=lambda call: call.from_user.id == ADMIN_ID and call.data == "admin_remove_vip")
def admin_remove_vip(call):
    admin_states[call.from_user.id] = {"action": "remove_vip"}
    bot.send_message(call.from_user.id, "👑 Send Chat ID to remove VIP:")

# ===================== MAIN STARTUP =====================
if __name__ == "__main__":
    print("🚀 ZEDOX VIP BOT v2.0 - Railway Production")
    print("📊 Initializing...")
    
    # Test database
    try:
        get_user(ADMIN_ID)
        print("✅ MongoDB connected")
    except Exception as e:
        print(f"❌ MongoDB Error: {e}")
        exit(1)
    
    # Start worker
    start_background_worker()
    
    # Initial cleanup
    worker_cleanup()
    
    print("✅ All systems ready")
    print("🎉 Starting polling...")
    print("🌐 Railway deployment LIVE!")
    
    # Production polling
    while True:
        try:
            bot.infinity_polling(none_stop=True, timeout=30, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            print(f"🔄 Restarting in 10s...")
            time.sleep(10)
