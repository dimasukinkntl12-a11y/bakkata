import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_user_log, add_group_log # Import dari file database tadi

# Setup Config (Gunakan os.getenv untuk Railway)
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

app = Client("bakkata_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- HANDLER START ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user = message.from_user
    # Log user pertama kali klik start
    is_new = await add_user_log(user.id, user.first_name, user.username)
    
    if is_new:
        # Kirim log ke admin jika user baru
        await client.send_message(
            ADMIN_ID, 
            f"👤 **Log Start Baru**\nNama: {user.first_name}\nID: {user.id}\nUSN: @{user.username}"
        )

    text = (
        "Selamat datang di Bot Tebak Kata!\n\n"
        "Gunakan tombol di bawah untuk bantuan atau grup support."
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Dev", url="https://t.me/username_lu")],
        [InlineKeyboardButton("Grup Support", url="https://t.me/group_lu")],
        [InlineKeyboardButton("Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true")]
    ])
    await message.reply(text, reply_markup=buttons)

# --- LOG ADDBOT KE GRUP ---
@app.on_message(filters.new_chat_members)
async def log_added_to_group(client, message):
    for member in message.new_chat_members:
        if member.id == (await client.get_me()).id:
            chat = message.chat
            adder = message.from_user
            
            # Simpan log grup ke database
            await add_group_log(chat.id, chat.title, adder.id, adder.first_name)
            
            # Kirim log ke admin
            await client.send_message(
                ADMIN_ID,
                f"🏘 **Bot Added to Group**\nNama Grup: {chat.title}\nID Grup: {chat.id}\nYang Add: {adder.first_name} ({adder.id})"
            )
            await message.reply(f"Halo semuanya! Bot Tebak Kata aktif di grup **{chat.title}**. Ketik /help untuk cara main.")

# --- HANDLER HELP ---
@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = (
        "📖 **Peraturan & Cara Main**\n\n"
        "1. Klik /mulai untuk buat lobby.\n"
        "2. Benar: +10 poin | Salah: -5 poin.\n"
        "3. /hint: Potong 15 poin.\n"
        "4. /ganti: Ganti soal (Limit 1x per match)."
    )
    await message.reply(help_text)

if __name__ == "__main__":
    print("Bot Bakkata Running...")
    app.run()
