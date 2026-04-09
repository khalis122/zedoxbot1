import telebot
import os
from pymongo import MongoClient

# =========================
# ENV VARIABLES
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(BOT_TOKEN)

# =========================
# DATABASE
# =========================
client = MongoClient(MONGO_URI)
db = client["zedox_test_bot"]
users_col = db["users"]

# =========================
# START COMMAND
# =========================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id

    # save user
    users_col.update_one(
        {"_id": uid},
        {"$set": {"joined": True}},
        upsert=True
    )

    bot.send_message(uid, "✅ Bot working with MongoDB!")

# =========================
# CHECK USERS COUNT (ADMIN)
# =========================
@bot.message_handler(commands=['users'])
def users_count(msg):
    if msg.from_user.id != ADMIN_ID:
        bot.send_message(msg.chat.id, "❌ You are not admin")
        return

    count = users_col.count_documents({})
    bot.send_message(msg.chat.id, f"👤 Total users: {count}")

# =========================
# BROADCAST (ADMIN)
# =========================
@bot.message_handler(commands=['broadcast'])
def broadcast(msg):
    if msg.from_user.id != ADMIN_ID:
        return

    bot.send_message(msg.chat.id, "Send message to broadcast:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(msg):
    users = users_col.find()
    sent = 0

    for u in users:
        try:
            bot.send_message(u["_id"], msg.text)
            sent += 1
        except:
            continue

    bot.send_message(msg.chat.id, f"✅ Sent to {sent} users")

# =========================
# TEST COMMAND
# =========================
@bot.message_handler(commands=['ping'])
def ping(msg):
    bot.send_message(msg.chat.id, "🏓 Pong! Bot alive.")

print("Bot started...")

bot.infinity_polling()
