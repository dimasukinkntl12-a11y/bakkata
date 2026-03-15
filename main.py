import os
import random
import asyncio
import pyromod.listen
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_user_log, add_group_log, update_point, users, groups

# --- CONFIG ---
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

app = Client("bakkata_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

active_games = {}

# --- LOGIC PEMBACA FILE KBBI ---
def load_kbbi():
    file_path = "list_10.0.0.txt"
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return [line.strip().lower() for line in f.readlines() if line.strip()]
    return []

ALL_WORDS = load_kbbi()

def generate_pattern_question(length):
    possible_words = [w for w in ALL_WORDS if len(w) == length and " " not in w]
    if not possible_words:
        for fallback_len in range(length-1, 3, -1):
            possible_words = [w for w in ALL_WORDS if len(w) == fallback_len and " " not in w]
            if possible_words: break
        if not possible_words: possible_words = ["buku", "bola", "padi", "mata"]
    
    target_word = random.choice(possible_words)
    first, last = target_word[0].upper(), target_word[-1].upper()
    underscores = " _ " * (len(target_word) - 2)
    return {
        "pattern": f"{first}{underscores}{last}",
        "length": len(target_word),
        "prefix": first.lower(),
        "suffix": last.lower()
    }

# --- HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user = message.from_user
    await add_user_log(user.id, user.first_name, user.username)
    
    # Ambil data dari DB
    text = await get_setting("start", "🎮 **Bot Bakkata**\n\nGame tebak kata seru!")
    dev_url = await get_setting("dev", "https://t.me/username_lu")
    supp_url = await get_setting("supp", "https://t.me/grup_support")
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true")],
        [InlineKeyboardButton("🛠 Dev", url=dev_url), InlineKeyboardButton("🎧 Support", url=supp_url)],
        [InlineKeyboardButton("📖 Bantuan", callback_data="show_help")]
    ])
    await message.reply(text, reply_markup=buttons)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = await get_setting("help", "📖 **CARA MAIN BAKKATA**\n\nKetik /mulai di grup.")
    await message.reply(help_text)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = (
        "📖 **CARA MAIN BAKKATA**\n\n"
        "1. Tambahin bot ke grup.\n"
        "2. Ketik `/mulai` buat buka lobby.\n"
        "3. Klik **Join** atau ketik `/gabung`.\n"
        "4. Host klik **Mulai**.\n"
        "5. Jawab dengan cara **REPLY** pesan soal dari bot.\n\n"
        "💰 **SISTEM POIN:**\n"
        "- Benar: +10 poin\n"
        "- Salah: -5 poin\n"
        "- Salah 3x berturut-turut: Kick dari match!"
    )
    await message.reply(help_text)

@app.on_callback_query(filters.regex("show_help"))
async def help_callback(client, callback_query):
    await callback_query.edit_message_text("📖 Silahkan cek menu bantuan dengan perintah /help di grup atau di sini.")
    
@app.on_message(filters.group, group=-1)
async def auto_log_group(client, message):
    chat, user = message.chat, message.from_user
    if user: await add_group_log(chat.id, chat.title, user.id, user.first_name)

@app.on_message(filters.command("mulai") & filters.group)
async def mulai_handler(client, message):
    chat_id = message.chat.id
    if chat_id in active_games: return await message.reply("Lobby masih terbuka atau game sedang jalan!")
    
    active_games[chat_id] = {"host": message.from_user.id, "players": [message.from_user.id], "status": "lobby"}
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Join", callback_data="join_game")],[InlineKeyboardButton("Mulai", callback_data="start_match")]])
    await message.reply(f"🎮 **Lobby Bakkata Dibuka!**\n\nHost: {message.from_user.first_name}\nTotal Player: 1", reply_markup=buttons)

# --- GAME ENGINE ---
@app.on_message(filters.group & ~filters.command(["mulai", "help", "start", "ganti", "top", "keluar", "gabung", "admin", "stop"]))
@app.on_message(filters.group & ~filters.command(["mulai", "help", "start", "ganti", "top", "keluar", "gabung", "admin", "stop"]))
async def bakkata_engine(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or chat_id not in active_games or active_games[chat_id].get("status") != "playing": return
    
    game = active_games[chat_id]
    is_airdrop = game.get("is_airdrop", False)

    # Kalau BUKAN airdrop, wajib reply ke bot
    if not is_airdrop:
        if not message.reply_to_message: return
        me = await client.get_me()
        if message.reply_to_message.from_user.id != me.id: return
        if user_id not in game["players"]: return

    input_word = message.text.lower().strip()
    if (len(input_word) == game["length"] and input_word.startswith(game["prefix"]) and input_word.endswith(game["suffix"]) and input_word in ALL_WORDS):
        poin = game.get("airdrop_points", 10)
        await update_point(user_id, poin)
        
        u_data = await users.find_one({"_id": user_id})
        pts = u_data.get("point", 0) if u_data else poin
        new_level = (pts // 100) + 1
        soal = generate_pattern_question(min(3 + new_level, 15))
        
        game.update({"prefix": soal["prefix"], "suffix": soal["suffix"], "length": soal["length"], "swapped": False})
        if "wrong" in game: game["wrong"][user_id] = 0

        await message.reply(f"✅ **BENAR!** ({input_word.upper()})\n👤 {message.from_user.mention}\n📈 Level: {new_level} ({pts} pts)\n\n**NEXT:** `{soal['pattern']}` ({soal['length']} Huruf)\n👉 _Reply buat jawab!_")
    else:
        if not is_airdrop:
            await update_point(user_id, -5)
            if "wrong" not in game: game["wrong"] = {}
            game["wrong"][user_id] = game["wrong"].get(user_id, 0) + 1
            if game["wrong"][user_id] >= 3:
                if user_id in game["players"]: game["players"].remove(user_id)
                await message.reply(f"❌ {message.from_user.mention} **KALAH!** (Salah 3x)")
            else:
                await message.reply(f"⚠️ {message.from_user.mention} **SALAH!** (-5 pts)")

# --- COMMANDS ---
@app.on_message(filters.command("gabung") & filters.group)
async def gabung_cmd(client, message):
    cid, uid = message.chat.id, message.from_user.id
    if cid not in active_games: return await message.reply("Gak ada game aktif.")
    if uid in active_games[cid]["players"]: return await message.reply("Udah gabung.")
    active_games[cid]["players"].append(uid)
    await message.reply(f"✅ {message.from_user.first_name} bergabung! Total: {len(active_games[cid]['players'])}")

@app.on_message(filters.command("keluar") & filters.group)
async def keluar_cmd(client, message):
    cid, uid = message.chat.id, message.from_user.id
    if cid in active_games and uid in active_games[cid]["players"]:
        active_games[cid]["players"].remove(uid)
        await message.reply("👋 Lu keluar.")

@app.on_message(filters.command("ganti") & filters.group)
async def ganti_cmd(client, message):
    cid = message.chat.id
    if cid not in active_games or active_games[cid].get("status") != "playing": return
    if active_games[cid].get("swapped"): return await message.reply("Cuma bisa ganti 1x!")
    soal = generate_pattern_question(active_games[cid]["length"])
    active_games[cid].update({"prefix": soal["prefix"], "suffix": soal["suffix"], "swapped": True})
    await message.reply(f"🔄 **Soal Diganti!**\n\nBaru: `{soal['pattern']}`")

@app.on_message(filters.command("top"))
async def top_cmd(client, message):
    top_10 = await users.find().sort("point", -1).limit(10).to_list(10)
    text = "🏆 **TOP SCORE BAKKATA**\n\n"
    for i, u in enumerate(top_10, 1):
        text += f"{i}. {u.get('name', 'User')} — `{u.get('point', 0)} pts`\n"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("📊 Cek Score Saya", callback_data="my_score")]])
    await message.reply(text, reply_markup=buttons)

@app.on_message(filters.command("stop") & filters.group)
async def stop_game(client, message):
    if message.chat.id in active_games:
        del active_games[message.chat.id]
        await message.reply("🛑 Game dihentikan.")

@app.on_message(filters.group, group=-1)
async def auto_log_group(client, message):
    chat, user = message.chat, message.from_user
    if user:
        await add_group_log(chat.id, chat.title, user.id, user.first_name)
        
        # Kirim ke grup log jika ID sudah diset
        log_id = await get_setting("log")
        if log_id:
            try:
                await client.send_message(log_id, f"📢 **Log Grup**\n📍 {chat.title}\n👤 {user.first_name} ({user.id})")
            except: pass

@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_panel(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast User", callback_data="bc_user"), InlineKeyboardButton("👥 Broadcast Grup", callback_data="bc_group")],
        [InlineKeyboardButton("🎁 Airdrop", callback_data="setup_airdrop"), InlineKeyboardButton("⚙️ Settings", callback_data="bot_settings")]
    ])
    await message.reply("🛠 **Admin Panel Bakkata**", reply_markup=buttons)

# --- CALLBACKS ---
@app.on_callback_query(filters.regex("my_score"))
async def my_score_callback(client, callback_query):
    u = await users.find_one({"_id": callback_query.from_user.id})
    score = u.get("point", 0) if u else 0
    await callback_query.answer(f"Skor lu: {score} pts", show_alert=True)

@app.on_callback_query(filters.regex("join_game"))
async def join_callback(client, callback_query):
    cid, uid = callback_query.message.chat.id, callback_query.from_user.id
    if cid not in active_games: return
    if uid in active_games[cid]["players"]: return await callback_query.answer("Udah join!")
    active_games[cid]["players"].append(uid)
    await callback_query.message.edit_text(f"🎮 **Lobby Bakkata Dibuka!**\n\nTotal Player: {len(active_games[cid]['players'])}", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Join", callback_data="join_game")],[InlineKeyboardButton("Mulai", callback_data="start_match")]]))

@app.on_callback_query(filters.regex("start_match"))
async def start_match_cb(client, callback_query):
    cid = callback_query.message.chat.id
    if callback_query.from_user.id != active_games[cid]["host"]: return await callback_query.answer("Cuma host!")
    soal = generate_pattern_question(4)
    active_games[cid].update({"status": "playing", "prefix": soal["prefix"], "suffix": soal["suffix"], "length": soal["length"]})
    await callback_query.message.edit_text(f"🚀 **Game Dimulai!**\n\nSoal: `{soal['pattern']}`\nReply buat jawab!")

@app.on_callback_query(filters.regex("setup_airdrop") & filters.user(ADMIN_ID))
async def airdrop_callback(client, callback_query):
    soal = generate_pattern_question(random.randint(6, 8))
    all_g = await groups.find().to_list(1000)
    for g in all_g:
        try:
            active_games[g["_id"]] = {"status": "playing", "is_airdrop": True, "airdrop_points": 50, "prefix": soal["prefix"], "suffix": soal["suffix"], "length": soal["length"]}
            await client.send_message(g["_id"], f"🎁 **AIRDROP 50 POIN!**\n\nSoal: `{soal['pattern']}`\nReply buat ambil!")
        except: continue
    await callback_query.answer("Airdrop disebar!")

@app.on_callback_query(filters.regex(r"^bc_(user|group)") & filters.user(ADMIN_ID))
async def broadcast_handler(client, callback_query):
    mode = callback_query.data.split("_")[1]
    msg = await client.ask(callback_query.message.chat.id, f"Silahkan kirim pesan/media yang mau di broadcast ke {mode}:")
    
    count = 0
    targets = await users.find().to_list(1000) if mode == "user" else await groups.find().to_list(1000)
    
    for t in targets:
        try:
            await msg.copy(t["_id"])
            count += 1
            await asyncio.sleep(0.3) # Biar gak kena flood
        except: continue
    
    await callback_query.message.reply(f"✅ Berhasil broadcast ke {count} {mode}.")

@app.on_callback_query(filters.regex("bot_settings") & filters.user(ADMIN_ID))
async def settings_menu(client, callback_query):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Set Log Grup", callback_data="set_log"), InlineKeyboardButton("👨‍💻 Set Dev Link", callback_data="set_dev")],
        [InlineKeyboardButton("🎧 Set Supp Link", callback_data="set_supp")],
        [InlineKeyboardButton("🏠 Set Start Text", callback_data="set_start"), InlineKeyboardButton("📖 Set Help Text", callback_data="set_help")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_admin")]
    ])
    await callback_query.message.edit_text("⚙️ **Bot Settings**\nSilakan pilih yang mau diubah:", reply_markup=buttons)

@app.on_callback_query(filters.regex(r"^set_") & filters.user(ADMIN_ID))
async def handle_set_settings(client, callback_query):
    key = callback_query.data.split("_")[1]
    chat_id = callback_query.message.chat.id
    
    # Prompt buat user
    prompt = {
        "log": "Kirimkan ID Grup Log (Contoh: -100123456):",
        "dev": "Kirimkan link Telegram Dev:",
        "supp": "Kirimkan link Grup Support:",
        "start": "Kirimkan teks baru untuk /start:",
        "help": "Kirimkan teks baru untuk /help:"
    }
    
    ask = await client.ask(chat_id, prompt.get(key, "Kirimkan data baru:"))
    val = ask.text
    
    if key == "log":
        try: val = int(val)
        except: return await ask.reply("❌ ID Grup harus angka!")
        
    await set_setting(key, val)
    await ask.reply(f"✅ Berhasil update setting: **{key}**!")

if __name__ == "__main__":
    app.run()
