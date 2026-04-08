# ===============================
# ZEDOX VIP BOT - PART 1
# Core setup + MongoDB + User creation + Referral
# ===============================

import telebot
from telebot import types
from pymongo import MongoClient

# ===============================
# CONFIGURATION
# ===============================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
MONGO_URI = "YOUR_MONGODB_URI_HERE"
REFERRAL_REWARD = 10
START_VIP = False
START_POINTS = 0

bot = telebot.TeleBot(BOT_TOKEN)

# ===============================
# DATABASE SETUP
# ===============================
client = MongoClient(MONGO_URI)
db = client["zedox_vip_bot"]

users_collection = db["users"]
folders_collection = db["folders"]
codes_collection = db["codes"]
config_collection = db["config"]
forcejoin_collection = db["forcejoin"]

# ===============================
# HELPER FUNCTIONS
# ===============================
def create_user(user_id, username=None, ref_id=None):
    if users_collection.find_one({"user_id": user_id}):
        return False

    user_data = {
        "user_id": user_id,
        "username": username,
        "points": START_POINTS,
        "vip": START_VIP,
        "ref_id": ref_id,
        "referrals": [],
        "joined_channels": [],
    }

    users_collection.insert_one(user_data)

    if ref_id:
        referrer = users_collection.find_one({"user_id": int(ref_id)})
        if referrer:
            users_collection.update_one(
                {"user_id": int(ref_id)},
                {"$inc": {"points": REFERRAL_REWARD}, "$push": {"referrals": user_id}}
            )
    return True

def get_user(user_id):
    return users_collection.find_one({"user_id": user_id})

# ===============================
# START COMMAND
# ===============================
@bot.message_handler(commands=["start"])
def start(message):
    args = message.text.split()
    ref_id = args[1] if len(args) > 1 else None

    created = create_user(message.from_user.id, message.from_user.username, ref_id)
    
    user = get_user(message.from_user.id)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📂 FREE METHODS", "💎 VIP METHODS")
    markup.row("📦 PREMIUM APPS", "💰 POINTS")
    markup.row("⭐ BUY VIP", "🎁 REFERRAL")
    markup.row("👤 ACCOUNT", "🆔 CHAT ID")
    markup.row("🏆 COUPON REDEEM")

    welcome_text = f"👋 Welcome {message.from_user.first_name}!\n"
    if created:
        welcome_text += f"✅ You have been registered.\nPoints: {user['points']}\nVIP: {user['vip']}"
    else:
        welcome_text += f"🔹 You are already registered.\nPoints: {user['points']}\nVIP: {user['vip']}"

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# ===============================
# RUN BOT
# ===============================
print("Bot is running...")
bot.infinity_polling()
# ===============================
# ZEDOX VIP BOT - PART 2
# Force Join System + "I Joined" Button
# ===============================

from telebot import types

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def get_forcejoin_channels():
    # Returns list of channel IDs that users must join
    channels = forcejoin_collection.find()
    return [ch["channel_id"] for ch in channels]

def user_joined_all(user_id):
    user = get_user(user_id)
    joined = user.get("joined_channels", [])
    required = get_forcejoin_channels()
    return all(ch in joined for ch in required)

# -------------------------------
# FORCE JOIN CHECK
# -------------------------------

def forcejoin_check(message):
    required_channels = get_forcejoin_channels()
    if not required_channels:
        return True  # No channels required

    if user_joined_all(message.from_user.id):
        return True

    markup = types.InlineKeyboardMarkup()
    for ch_id in required_channels:
        markup.add(types.InlineKeyboardButton(text=f"Join {ch_id}", url=f"https://t.me/{ch_id}"))

    markup.add(types.InlineKeyboardButton(text="🔄 I Joined", callback_data="check_join"))
    bot.send_message(message.chat.id, "🚫 ACCESS DENIED! Join all channels to continue.", reply_markup=markup)
    return False

# -------------------------------
# CALLBACK HANDLER - I Joined
# -------------------------------
@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    user_id = call.from_user.id
    required_channels = get_forcejoin_channels()
    updated = False

    for ch_id in required_channels:
        try:
            member = bot.get_chat_member(f"@{ch_id}", user_id)
            if member.status in ["member", "creator", "administrator"]:
                user = get_user(user_id)
                if ch_id not in user.get("joined_channels", []):
                    users_collection.update_one(
                        {"user_id": user_id},
                        {"$push": {"joined_channels": ch_id}}
                    )
                    updated = True
        except Exception as e:
            print(f"Error checking {ch_id} for {user_id}: {e}")

    if user_joined_all(user_id):
        bot.answer_callback_query(call.id, "✅ You joined all channels! You can access the bot now.")
        bot.send_message(user_id, "🎉 Access granted! Use the menu below.")
    else:
        bot.answer_callback_query(call.id, "❌ You still need to join all channels.")
# ===============================
# ZEDOX VIP BOT - PART 3
# Points System + VIP System + Admin VIP Management
# ===============================

from telebot import types

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def set_points(user_id, points):
    users_collection.update_one({"user_id": user_id}, {"$set": {"points": points}})

def add_points(user_id, points):
    users_collection.update_one({"user_id": user_id}, {"$inc": {"points": points}})

def is_vip(user_id):
    user = get_user(user_id)
    return user.get("vip", False)

def set_vip(user_id, status=True):
    users_collection.update_one({"user_id": user_id}, {"$set": {"vip": status}})

def get_vip_join_message():
    config = config_collection.find_one({"key": "vip_join_message"})
    if config:
        return config["value"]
    return "❌ This content is VIP only. Get VIP to access."

def set_vip_join_message(message_text):
    config_collection.update_one(
        {"key": "vip_join_message"},
        {"$set": {"value": message_text}},
        upsert=True
    )

# -------------------------------
# USER COMMANDS
# -------------------------------

@bot.message_handler(commands=["points"])
def check_points(message):
    user = get_user(message.from_user.id)
    bot.send_message(message.chat.id, f"💰 You have {user['points']} points.")

# VIP-only decorator
def vip_required(func):
    def wrapper(message, *args, **kwargs):
        if not is_vip(message.from_user.id):
            bot.send_message(message.chat.id, get_vip_join_message())
            return
        return func(message, *args, **kwargs)
    return wrapper

# Example VIP-only command
@bot.message_handler(commands=["vip_method"])
@vip_required
def vip_method(message):
    bot.send_message(message.chat.id, "✅ You accessed a VIP method!")

# -------------------------------
# ADMIN SETTINGS
# -------------------------------

ADMIN_IDS = [123456789]  # Replace with your Telegram ID(s)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# /add_vip <chat_id>
@bot.message_handler(commands=["add_vip"])
def admin_add_vip(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /add_vip <chat_id>")
        return
    target_id = int(args[1])
    set_vip(target_id, True)
    bot.reply_to(message, f"✅ User {target_id} is now VIP.")

# /remove_vip <chat_id>
@bot.message_handler(commands=["remove_vip"])
def admin_remove_vip(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /remove_vip <chat_id>")
        return
    target_id = int(args[1])
    set_vip(target_id, False)
    bot.reply_to(message, f"❌ VIP removed for user {target_id}.")

# /set_vip_message <text>
@bot.message_handler(commands=["set_vip_message"])
def admin_set_vip_message(message):
    if not is_admin(message.from_user.id):
        return
    msg = message.text.split(" ", 1)
    if len(msg) < 2:
        bot.reply_to(message, "Usage: /set_vip_message <message_text>")
        return
    set_vip_join_message(msg[1])
    bot.reply_to(message, "✅ VIP join message updated.")

# -------------------------------
# ADMIN POINTS COMMANDS
# -------------------------------

# /give_points <chat_id> <points>
@bot.message_handler(commands=["give_points"])
def admin_give_points(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /give_points <chat_id> <points>")
        return
    target_id = int(args[1])
    points = int(args[2])
    add_points(target_id, points)
    bot.reply_to(message, f"✅ Given {points} points to {target_id}.")

# /set_points <chat_id> <points>
@bot.message_handler(commands=["set_points"])
def admin_set_points(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "Usage: /set_points <chat_id> <points>")
        return
    target_id = int(args[1])
    points = int(args[2])
    set_points(target_id, points)
    bot.reply_to(message, f"✅ Set {points} points for {target_id}.")
# ===============================
# ZEDOX VIP BOT - PART 4
# Content System: Free / VIP / Premium Apps + Folders + File Sending
# ===============================

from telebot import types

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def get_category_folders(category):
    # category: "free", "vip", "apps"
    return list(folders_collection.find({"category": category}))

def get_folder_files(folder_id):
    folder = folders_collection.find_one({"_id": folder_id})
    if folder:
        return folder.get("files", [])
    return []

def send_folder_files(user_id, folder_id):
    files = get_folder_files(folder_id)
    for f in files:
        try:
            bot.copy_message(user_id, f["chat_id"], f["message_id"])
        except Exception as e:
            print(f"Error sending file {f}: {e}")

# -------------------------------
# ACCESS LOGIC
# -------------------------------

def can_access(user_id, category):
    user = get_user(user_id)
    vip = user.get("vip", False)
    if category == "vip" and not vip:
        return False
    if category == "apps" and not vip and user.get("points", 0) <= 0:
        return False
    return True

# -------------------------------
# MENU HANDLERS
# -------------------------------

@bot.message_handler(func=lambda m: m.text == "📂 FREE METHODS")
def free_methods_menu(message):
    folders = get_category_folders("free")
    markup = types.InlineKeyboardMarkup()
    for folder in folders:
        markup.add(types.InlineKeyboardButton(text=folder["name"], callback_data=f"free_{folder['_id']}"))
    bot.send_message(message.chat.id, "📂 Free Methods:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 VIP METHODS")
def vip_methods_menu(message):
    folders = get_category_folders("vip")
    markup = types.InlineKeyboardMarkup()
    for folder in folders:
        markup.add(types.InlineKeyboardButton(text=folder["name"], callback_data=f"vip_{folder['_id']}"))
    bot.send_message(message.chat.id, "💎 VIP Methods:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "📦 PREMIUM APPS")
def apps_menu(message):
    folders = get_category_folders("apps")
    markup = types.InlineKeyboardMarkup()
    for folder in folders:
        markup.add(types.InlineKeyboardButton(text=folder["name"], callback_data=f"apps_{folder['_id']}"))
    bot.send_message(message.chat.id, "📦 Premium Apps:", reply_markup=markup)

# -------------------------------
# CALLBACK HANDLER FOR FOLDERS
# -------------------------------

@bot.callback_query_handler(func=lambda call: True)
def folder_callback(call):
    data = call.data
    category, folder_id = data.split("_")
    user_id = call.from_user.id

    if not can_access(user_id, category):
        if category == "vip":
            bot.send_message(user_id, get_vip_join_message())
        else:
            bot.send_message(user_id, "❌ You don't have enough points to access this content.")
        return

    folder_files = get_folder_files(ObjectId(folder_id))

    if not folder_files:
        bot.send_message(user_id, "❌ Folder is empty.")
        return

    # Deduct points if needed
    if category == "apps" and not is_vip(user_id):
        price = folders_collection.find_one({"_id": ObjectId(folder_id)}).get("price", 0)
        user = get_user(user_id)
        if user["points"] >= price:
            set_points(user_id, user["points"] - price)
            bot.send_message(user_id, f"💰 {price} points deducted for accessing this folder.")
        else:
            bot.send_message(user_id, "❌ Not enough points to access this folder.")
            return

    # Send all files
    for f in folder_files:
        try:
            bot.copy_message(user_id, f["chat_id"], f["message_id"])
        except Exception as e:
            print(f"Error sending file {f}: {e}")
# ===============================
# ZEDOX VIP BOT - PART 5
# Admin Panel: Upload, Edit, Delete, Broadcast, VIP Management
# ===============================

from telebot import types
from bson.objectid import ObjectId

# -------------------------------
# ADMIN CHECK
# -------------------------------
ADMIN_IDS = [123456789]  # Replace with your Telegram ID(s)

def is_admin(user_id):
    return user_id in ADMIN_IDS

# -------------------------------
# ADMIN PANEL MENU
# -------------------------------
@bot.message_handler(func=lambda m: m.text == "⚙️ ADMIN PANEL")
def admin_panel(message):
    if not is_admin(message.from_user.id):
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("✅ Add VIP", "❌ Remove VIP")
    markup.row("💰 Give Points", "🔧 Set Points")
    markup.row("📂 Upload Free", "💎 Upload VIP", "📦 Upload Apps")
    markup.row("✏️ Edit Folder", "🗑 Delete Folder")
    markup.row("📢 Broadcast", "🔔 Toggle Notifications")
    bot.send_message(message.chat.id, "⚙️ Admin Panel", reply_markup=markup)

# -------------------------------
# UPLOAD CONTENT HANDLER
# -------------------------------

@bot.message_handler(content_types=["document", "photo", "video"])
def upload_content(message):
    if not is_admin(message.from_user.id):
        return

    category = config_collection.find_one({"key": "upload_category"})
    if not category:
        bot.reply_to(message, "❌ Set upload category first using /set_upload_category <free/vip/apps>")
        return

    folder_name_doc = config_collection.find_one({"key": "upload_folder"})
    if not folder_name_doc:
        bot.reply_to(message, "❌ Set folder name first using /set_upload_folder <folder_name>")
        return

    folder_name = folder_name_doc["value"]
    category = category["value"]

    folder = folders_collection.find_one({"category": category, "name": folder_name})
    file_entry = {
        "chat_id": message.chat.id,
        "message_id": message.message_id
    }

    if folder:
        folders_collection.update_one(
            {"_id": folder["_id"]},
            {"$push": {"files": file_entry}}
        )
    else:
        folders_collection.insert_one({
            "category": category,
            "name": folder_name,
            "files": [file_entry],
            "price": 0
        })

    bot.reply_to(message, f"✅ Uploaded to {category.upper()} folder: {folder_name}")

# -------------------------------
# BROADCAST SYSTEM
# -------------------------------
@bot.message_handler(commands=["broadcast"])
def admin_broadcast(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(" ", 1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: /broadcast <message_text>")
        return
    text = args[1]
    all_users = users_collection.find()
    for user in all_users:
        try:
            bot.send_message(user["user_id"], text)
        except Exception as e:
            print(f"Failed to send to {user['user_id']}: {e}")
    bot.reply_to(message, "✅ Broadcast completed.")

# -------------------------------
# EDIT FOLDER
# -------------------------------
@bot.message_handler(commands=["edit_folder_name"])
def edit_folder_name(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(" ", 2)
    if len(args) < 3:
        bot.reply_to(message, "Usage: /edit_folder_name <folder_id> <new_name>")
        return
    folder_id = args[1]
    new_name = args[2]
    folders_collection.update_one({"_id": ObjectId(folder_id)}, {"$set": {"name": new_name}})
    bot.reply_to(message, f"✅ Folder name updated to {new_name}")

# -------------------------------
# DELETE FOLDER
# -------------------------------
@bot.message_handler(commands=["delete_folder"])
def delete_folder(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(" ", 1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: /delete_folder <folder_id>")
        return
    folder_id = args[1]
    folders_collection.delete_one({"_id": ObjectId(folder_id)})
    bot.reply_to(message, "✅ Folder deleted")

# -------------------------------
# ADD / REMOVE VIP
# -------------------------------
@bot.message_handler(commands=["add_vip"])
def admin_add_vip(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /add_vip <chat_id>")
        return
    target_id = int(args[1])
    set_vip(target_id, True)
    bot.reply_to(message, f"✅ User {target_id} is now VIP.")

@bot.message_handler(commands=["remove_vip"])
def admin_remove_vip(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /remove_vip <chat_id>")
        return
    target_id = int(args[1])
    set_vip(target_id, False)
    bot.reply_to(message, f"❌ VIP removed for user {target_id}")
# ===============================
# ZEDOX VIP BOT - PART 6
# Redeem Codes, VIP Expiry, Notifications, Error Handling
# ===============================

from datetime import datetime, timedelta

# -------------------------------
# NOTIFICATION SYSTEM
# -------------------------------
def notify_user(user_id, text, silent=False):
    try:
        bot.send_message(user_id, text, disable_notification=silent)
    except Exception as e:
        print(f"Notification failed for {user_id}: {e}")

# -------------------------------
# REDEEM CODE SYSTEM
# -------------------------------

def create_redeem_code(code, points=0, vip_days=0, max_use=1):
    codes_collection.insert_one({
        "code": code,
        "points": points,
        "vip_days": vip_days,
        "max_use": max_use,
        "used_by": []
    })

@bot.message_handler(commands=["redeem"])
def redeem_code(message):
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /redeem <code>")
        return
    code_input = args[1]
    code = codes_collection.find_one({"code": code_input})
    if not code:
        bot.reply_to(message, "❌ Invalid code.")
        return

    if message.from_user.id in code.get("used_by", []):
        bot.reply_to(message, "❌ You already used this code.")
        return

    if len(code.get("used_by", [])) >= code.get("max_use", 1):
        bot.reply_to(message, "❌ This code has expired.")
        return

    # Apply rewards
    if code["points"]:
        add_points(message.from_user.id, code["points"])
        bot.reply_to(message, f"💰 You received {code['points']} points!")
    if code["vip_days"]:
        user = get_user(message.from_user.id)
        expiry = datetime.now() + timedelta(days=code["vip_days"])
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"vip": True, "vip_expiry": expiry}}
        )
        bot.reply_to(message, f"💎 VIP granted for {code['vip_days']} days!")

    # Mark as used
    codes_collection.update_one(
        {"_id": code["_id"]},
        {"$push": {"used_by": message.from_user.id}}
    )

# -------------------------------
# VIP EXPIRY CHECK
# -------------------------------
def check_vip_expiry(user_id):
    user = get_user(user_id)
    expiry = user.get("vip_expiry")
    if expiry:
        if datetime.now() > expiry:
            set_vip(user_id, False)
            users_collection.update_one({"user_id": user_id}, {"$unset": {"vip_expiry": ""}})
            notify_user(user_id, "❌ Your VIP has expired.")

# Call this periodically or before VIP content access
def vip_access_check(user_id):
    check_vip_expiry(user_id)
    return is_vip(user_id)

# -------------------------------
# ERROR HANDLING
# -------------------------------
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    try:
        # Force join check
        if not forcejoin_check(message):
            return
        # Here other generic commands can be handled
    except Exception as e:
        print(f"Error handling message {message.text} from {message.from_user.id}: {e}")
        bot.send_message(message.chat.id, "❌ An error occurred. Please try again later.")
# ===============================
# ZEDOX VIP BOT - PART 7
# Nested Folders, Method Expiry, Advanced Buttons
# ===============================

from bson.objectid import ObjectId
from datetime import datetime

# -------------------------------
# NESTED FOLDERS SYSTEM
# -------------------------------
def create_folder(category, name, parent_id=None, price=0):
    folder = {
        "category": category,
        "name": name,
        "parent_id": parent_id,  # None if top-level
        "files": [],
        "price": price,
        "expire": None
    }
    folders_collection.insert_one(folder)

def get_subfolders(parent_id):
    return list(folders_collection.find({"parent_id": parent_id}))

@bot.message_handler(func=lambda m: m.text.startswith("📂"))
def handle_folder_navigation(message):
    # Example: handle nested folder navigation
    # You can extend this to dynamically create buttons for subfolders
    pass

# -------------------------------
# METHOD EXPIRY SYSTEM
# -------------------------------
def set_folder_expiry(folder_id, expiry_datetime):
    folders_collection.update_one(
        {"_id": ObjectId(folder_id)},
        {"$set": {"expire": expiry_datetime}}
    )

def check_folder_expiry(user_id, folder_id):
    folder = folders_collection.find_one({"_id": ObjectId(folder_id)})
    if not folder:
        return False
    expiry = folder.get("expire")
    if expiry and datetime.now() > expiry:
        # Refund points if it was purchased
        user = get_user(user_id)
        price = folder.get("price", 0)
        if price > 0:
            add_points(user_id, price)
            bot.send_message(user_id, f"💰 Method expired. {price} points refunded.")
        return False
    return True

# -------------------------------
# ADVANCED BUTTON SYSTEM
# -------------------------------
def create_custom_button(text, url=None, callback=None):
    if url:
        return types.InlineKeyboardButton(text=text, url=url)
    elif callback:
        return types.InlineKeyboardButton(text=text, callback_data=callback)
    else:
        return types.InlineKeyboardButton(text=text, callback_data="noop")

# Example: Force Join button + Custom Links
def send_custom_buttons(user_id):
    markup = types.InlineKeyboardMarkup()
    # Force Join example
    markup.add(create_custom_button("🔗 Join Channel", url="https://t.me/example_channel"))
    # Custom link
    markup.add(create_custom_button("💬 WhatsApp Group", url="https://chat.whatsapp.com/example"))
    bot.send_message(user_id, "Choose an option:", reply_markup=markup)

# -------------------------------
# USAGE EXAMPLES
# -------------------------------
# Create a folder inside another
# create_folder("free", "Subfolder 1", parent_id="PARENT_FOLDER_ID", price=10)
# Set folder expiry
# set_folder_expiry("FOLDER_ID", datetime(2026, 5, 1, 0, 0))
# ===============================
# ZEDOX VIP BOT - PART 8
# Main Menu Customization, Dynamic Buttons, Infinite Polling
# ===============================

from telebot import types

# -------------------------------
# MAIN MENU BUTTONS CONFIG
# -------------------------------
def get_main_menu_buttons():
    buttons_doc = config_collection.find_one({"key": "main_menu_buttons"})
    if buttons_doc:
        return buttons_doc["value"]
    # Default buttons if none exist
    return [
        ["📂 FREE METHODS", "💎 VIP METHODS"],
        ["📦 PREMIUM APPS", "💰 POINTS"],
        ["⭐ BUY VIP", "🎁 REFERRAL"],
        ["👤 ACCOUNT", "🆔 CHAT ID", "🏆 COUPON REDEEM"],
        ["⚙️ ADMIN PANEL"]
    ]

def build_main_menu():
    menu = get_main_menu_buttons()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for row in menu:
        markup.row(*row)
    return markup

# -------------------------------
# SEND MAIN MENU
# -------------------------------
@bot.message_handler(commands=["start", "menu"])
def send_main_menu(message):
    # Force join check
    if not forcejoin_check(message):
        return
    bot.send_message(message.chat.id, "🏠 Main Menu:", reply_markup=build_main_menu())

# -------------------------------
# ADMIN ADD/REMOVE MAIN BUTTON
# -------------------------------
@bot.message_handler(commands=["add_main_button"])
def add_main_button(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(" ", 2)
    if len(args) < 3:
        bot.reply_to(message, "Usage: /add_main_button <row_index> <button_text>")
        return
    row_index = int(args[1])
    button_text = args[2]
    buttons_doc = config_collection.find_one({"key": "main_menu_buttons"})
    buttons = buttons_doc["value"] if buttons_doc else get_main_menu_buttons()

    # Add new row if index out of range
    while len(buttons) <= row_index:
        buttons.append([])

    buttons[row_index].append(button_text)
    config_collection.update_one({"key": "main_menu_buttons"}, {"$set": {"value": buttons}}, upsert=True)
    bot.reply_to(message, f"✅ Button '{button_text}' added to row {row_index}.")

@bot.message_handler(commands=["remove_main_button"])
def remove_main_button(message):
    if not is_admin(message.from_user.id):
        return
    args = message.text.split(" ", 2)
    if len(args) < 3:
        bot.reply_to(message, "Usage: /remove_main_button <row_index> <button_text>")
        return
    row_index = int(args[1])
    button_text = args[2]
    buttons_doc = config_collection.find_one({"key": "main_menu_buttons"})
    buttons = buttons_doc["value"] if buttons_doc else get_main_menu_buttons()
    if len(buttons) > row_index and button_text in buttons[row_index]:
        buttons[row_index].remove(button_text)
        config_collection.update_one({"key": "main_menu_buttons"}, {"$set": {"value": buttons}})
        bot.reply_to(message, f"✅ Button '{button_text}' removed from row {row_index}.")
    else:
        bot.reply_to(message, "❌ Button not found.")

# -------------------------------
# FINAL CLEANUP & INFINITE POLLING
# -------------------------------
if __name__ == "__main__":
    import time
    print("🤖 ZEDOX VIP BOT is running...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=5)
        except Exception as e:
            print(f"❌ Error in polling: {e}")
            time.sleep(5)
