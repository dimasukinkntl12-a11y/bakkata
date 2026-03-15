import os
import random
import asyncio
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
    # Load semua kata dari file lu buat validasi jawaban
    file_path = "list_10.0.0.txt" # Pastiin file ini di root atau sesuaikan pathnya
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return [line.strip().lower() for line in f.readlines() if line.strip()]
    return []

ALL_WORDS = load_kbbi()

def generate_pattern_question(length):
    # Filter kata berdasarkan panjang (Level 1=4, Level 2=5, dst)
    possible_words = [w for w in ALL_WORDS if len(w) == length and " " not in w]
    
    if not possible_words:
        # Cari panjang kata terdekat (kebawah) kalau level yang diminta gak ada
        for fallback_len in range(length-1, 3, -1):
            possible_words = [w for w in ALL_WORDS if len(w) == fallback_len and " " not in w]
            if possible_words: 
                break
        
        # Kalau tetap gak ketemu di file, baru pake cadangan manual
        if not possible_words: 
            possible_words = ["buku", "bola", "padi", "mata"] 
    
    target_word = random.choice(possible_words)
    # Bikin pola: Huruf pertama + underscore + Huruf terakhir
    first, last = target_word[0].upper(), target_word[-1].upper()
    underscores = " _ " * (len(target_word) - 2)
    pattern = f"{first}{underscores}{last}"
    
    return {
        "pattern": pattern,
        "length": len(target_word),
        "prefix": first.lower(),
        "suffix": last.lower()
    }

# --- HANDLERS ---

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user = message.from_user
    is_new = await add_user_log(user.id, user.first_name, user.username)
    if is_new:
        log_text = f"🆕 **User Baru!**\n👤 {user.first_name}\n🆔 {user.id}"
        await client.send_message(ADMIN_ID, log_text)

    text = "Selamat datang di Bot Bakkata! Tebak kata berdasarkan pola awalan dan akhiran."
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true")],
        [InlineKeyboardButton("Bantuan", callback_data="show_help")]
    ])
    await message.reply(text, reply_markup=buttons)

@app.on_message(filters.group, group=-1) # group=-1 biar jalan duluan sebelum filter lain
async def auto_log_group(client, message):
    chat = message.chat
    user = message.from_user
    if user:
        await add_group_log(chat.id, chat.title, user.id, user.first_name)

@app.on_message(filters.command("mulai") & filters.group)
async def mulai_handler(client, message):
    chat_id = message.chat.id
    if chat_id in active_games:
        return await message.reply("Lobby masih terbuka atau game sedang jalan!")

    active_games[chat_id] = {
        "host": message.from_user.id,
        "players": [message.from_user.id],
        "status": "lobby"
    }
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join", callback_data="join_game")],
        [InlineKeyboardButton("Mulai", callback_data="start_match")]
    ])
    await message.reply(f"🎮 **Lobby Bakkata Dibuka!**\n\nHost: {message.from_user.first_name}", reply_markup=buttons)

# --- GAME ENGINE (ANSWER CHECKER) ---
@app.on_message(filters.group & ~filters.command(["mulai", "help", "start", "ganti", "top", "keluar", "gabung", "admin"]))
async def bakkata_engine(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in active_games or active_games[chat_id].get("status") != "playing":
        return
    game = active_games[chat_id]
    
    if not message.reply_to_message: return
    if message.reply_to_message.from_user.id != (await client.get_me()).id: return

    is_airdrop = game.get("is_airdrop", False)
    if not is_airdrop and user_id not in game["players"]: return

    input_word = message.text.lower().strip()
    
    # LOGIKA BENAR
    if (len(input_word) == game["length"] and 
        input_word.startswith(game["prefix"]) and 
        input_word.endswith(game["suffix"]) and 
        input_word in ALL_WORDS):
        
        poin = game.get("airdrop_points", 10)
        await update_point(user_id, poin)
        
        if is_airdrop:
            del active_games[chat_id]
            return await message.reply(f"🎉 **AIRDROP DIAMBIL!**\n{message.from_user.mention} menjawab `{input_word.upper()}` (+{poin} pts)")

        # AMBIL DATA BARU BUAT LEVELING
        u_data = await users.find_one({"_id": user_id})
        pts = u_data.get("point", 0)
        new_level = (pts // 100) + 1
        
        # Leveling: Max level dibatasi panjang kata di KBBI (misal max 15 huruf)
        next_len = min(3 + new_level, 15) 
        soal = generate_pattern_question(next_len)
        
        game.update({
            "prefix": soal["prefix"], "suffix": soal["suffix"], 
            "length": soal["length"], "swapped": False
        })
        if "wrong" in game: game["wrong"][user_id] = 0 # Reset salah pas bener

        await message.reply(
            f"✅ **BENAR!** ({input_word.upper()})\n"
            f"👤 Player: {message.from_user.mention}\n"
            f"📈 Level: {new_level} ({pts} pts)\n\n"
            f"**NEXT SOAL:**\n`{soal['pattern']}` ({soal['length']} Huruf)"
        )
    
    # LOGIKA SALAH
    else:
        if not is_airdrop:
            await update_point(user_id, -5) # Potong poin
            if "wrong" not in game: game["wrong"] = {}
            game["wrong"][user_id] = game["wrong"].get(user_id, 0) + 1
            
            salah_count = game["wrong"][user_id]
            
            if salah_count >= 3:
                game["players"].remove(user_id)
                game["wrong"][user_id] = 0
                await message.reply(f"❌ {message.from_user.mention} **KALAH!**\nSalah 3x berturut-turut. Lu dikick dari match!")
            else:
                await message.reply(f"⚠️ {message.from_user.mention} **SALAH!**\nKata tidak valid atau pola salah. (-5 pts)\nKesempatan: {salah_count}/3")
# --- CALLBACKS ---
@app.on_callback_query(filters.regex("join_game"))
async def join_callback(client, callback_query):
    cid = callback_query.message.chat.id
    uid = callback_query.from_user.id
    if cid not in active_games: return
    if uid in active_games[cid]["players"]:
        return await callback_query.answer("Udah join!", show_alert=True)
    active_games[cid]["players"].append(uid)
    await callback_query.answer("Berhasil join!")

@app.on_callback_query(filters.regex("start_match"))
async def start_match_callback(client, callback_query):
    cid = callback_query.message.chat.id
    if cid not in active_games: return
    if callback_query.from_user.id != active_games[cid]["host"]:
        return await callback_query.answer("Cuma host yang bisa!", show_alert=True)
    
    soal = generate_pattern_question(4) # Start level easy (4 huruf)
    active_games[cid].update({
        "status": "playing",
        "prefix": soal["prefix"],
        "suffix": soal["suffix"],
        "length": soal["length"],
        "swapped": False
    })
    await callback_query.message.edit_text(f"🚀 **Game Dimulai!**\n\nSoal: `{soal['pattern']}`\nJumlah: {soal['length']} Huruf\n\n**Wajib REPLY pesan ini!**")

# --- COMMANDS ---
@app.on_message(filters.command("ganti") & filters.group)
async def ganti_cmd(client, message):
    cid = message.chat.id
    if cid not in active_games or active_games[cid].get("status") != "playing": return
    if active_games[cid].get("swapped"):
        return await message.reply("Hanya bisa ganti 1x!")
    
    soal = generate_pattern_question(active_games[cid]["length"])
    active_games[cid].update({
        "prefix": soal["prefix"], "suffix": soal["suffix"], "swapped": True
    })
    await message.reply(f"🔄 **Soal Diganti!**\n\nBaru: `{soal['pattern']}`")

@app.on_message(filters.command("top"))
async def top_cmd(client, message):
    top_10 = await users.find().sort("point", -1).limit(10).to_list(10)
    text = "🏆 **TOP SCORE**\n\n"
    for i, u in enumerate(top_10, 1):
        text += f"{i}. {u.get('name')} — `{u.get('point')} pts`\n"
    await message.reply(text)

@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_panel(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Broadcast User", callback_data="bc_user"), InlineKeyboardButton("Broadcast Grup", callback_data="bc_group")],
        [InlineKeyboardButton("🎁 Airdrop Poin", callback_data="setup_airdrop")]
    ])
    await message.reply("🛠 **Admin Panel**", reply_markup=buttons)

@app.on_callback_query(filters.regex("setup_airdrop") & filters.user(ADMIN_ID))
async def airdrop_callback(client, callback_query):
    soal = generate_pattern_question(random.randint(6, 8))
    all_g = await groups.find().to_list(1000)
    for g in all_g:
        try:
            cid = g["_id"]
            active_games[cid] = {
                "status": "playing", "is_airdrop": True, "airdrop_points": 50,
                "prefix": soal["prefix"], "suffix": soal["suffix"], "length": soal["length"]
            }
            await client.send_message(cid, f"🎁 **AIRDROP 50 POIN!**\n\nSoal: `{soal['pattern']}`\nReply buat ambil!")
        except: continue
    await callback_query.answer("Airdrop disebar!")

if __name__ == "__main__":
    print("Bot Bakkata Running...")
    app.run()
