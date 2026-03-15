import os
import random
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_user_log, add_group_log, update_point # Pindahin ke sini

# Simpan state game
active_games = {}

# Setup Config
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

app = Client("bakkata_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_random_question(level):
    try:
        file_path = f"txt/{level}.txt"
        if not os.path.exists(file_path):
            file_path = "txt/1.txt"
            
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Pastiin format file txt lu: Soal|Jawaban
            data = random.choice(lines).strip().split("|")
            return {"question": data[0], "answer": data[1].lower()}
    except Exception as e:
        print(f"Error load soal: {e}")
        return None

# --- HANDLERS ---

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user = message.from_user
    # Simpan/Cek user di DB
    is_new = await add_user_log(user.id, user.first_name, user.username)
    
    if is_new:
        # Log tiap orang klik start pertama kali
        log_text = (
            f"🆕 **User Baru Terdeteksi!**\n"
            f"👤 Nama: {user.first_name}\n"
            f"🆔 ID: {user.id}\n"
            f"🔗 USN: @{user.username if user.username else 'Tidak Ada'}"
        )
        await client.send_message(ADMIN_ID, log_text)

    # Teks bisa lu ganti manual di sini atau nanti lewat database
    text = "Selamat datang di Bot Tebak Kata!\n\nGunakan tombol di bawah untuk bantuan atau grup support."
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Dev", url="https://t.me/username_lu")],
        [InlineKeyboardButton("Grup Support", url="https://t.me/group_lu")],
        [InlineKeyboardButton("Add to Group", url=f"https://t.me/{client.me.username}?startgroup=true")],
        [InlineKeyboardButton("Bantuan (/help)", callback_data="show_help")]
    ])
    await message.reply(text, reply_markup=buttons)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = (
        "📖 **Cara Main Bakkata:**\n\n"
        "1. Tambahkan bot ke grup.\n"
        "2. Ketik /mulai untuk buka lobby.\n"
        "3. Klik 'Join' lalu host klik 'Mulai'.\n"
        "4. Jawab soal yang muncul cepat-cepetan!\n\n"
        "💰 **Sistem Poin:**\n"
        "• Benar: +10 Poin\n"
        "• Salah: -5 Poin (Salah 3x kena kick!)\n"
        "• Hint: -15 Poin (/hint)\n"
        "• Ganti Soal: Cuma 1x per match (/ganti)"
    )
    await message.reply(help_text)

@app.on_message(filters.command("mulai") & filters.group)
async def mulai_handler(client, message):
    chat_id = message.chat.id
    if chat_id in active_games:
        return await message.reply("Masih ada game yang jalan atau lobby masih dibuka!")

    active_games[chat_id] = {
        "host": message.from_user.id,
        "players": [message.from_user.id],
        "status": "lobby"
    }
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join", callback_data="join_game")],
        [InlineKeyboardButton("Mulai", callback_data="start_match")]
    ])
    
    await message.reply(
        f"🎮 **Lobby Tebak Kata Dibuka!**\n\nHost: {message.from_user.first_name}\nKlik Join buat ikutan!",
        reply_markup=buttons
    )

@app.on_message(filters.group & ~filters.command(["mulai", "help", "start", "ganti", "hint", "top", "keluar", "gabung", "admin"]))
async def answer_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in active_games or active_games[chat_id].get("status") != "playing":
        return
    if user_id not in active_games[chat_id]["players"]:
        return 

    user_answer = message.text.lower().strip()
    game = active_games[chat_id]
    
    # Inisialisasi hitungan salah jika belum ada
    if "wrong_attempts" not in game: game["wrong_attempts"] = {}
    if user_id not in game["wrong_attempts"]: game["wrong_attempts"][user_id] = 0

    if user_answer == game["answer"]:
        # Kasih poin (cek jika airdrop)
        poin_plus = game.get("airdrop_points", 10)
        await update_point(user_id, poin_plus)
        
        # Cek Leveling (Naik level tiap kelipatan 100 poin misal)
        from database import users
        u_data = await users.find_one({"_id": user_id})
        current_level = (u_data.get("point", 0) // 100) + 1
        
        await message.reply(f"✅ **BENAR!** (+{poin_plus})\nLevel Lu: {current_level}")
        
        # Soal baru berdasarkan level user yang benar
        soal_baru = get_random_question(current_level)
        game.update({"answer": soal_baru["answer"], "question": soal_baru["question"], "swapped": False})
        await client.send_message(chat_id, f"Next Soal (Level {current_level}):\n`{soal_baru['question']}`")
    else:
        # Salah potong poin
        await update_point(user_id, -5)
        game["wrong_attempts"][user_id] += 1
        
        if game["wrong_attempts"][user_id] >= 3:
            game["players"].remove(user_id)
            game["wrong_attempts"][user_id] = 0
            await message.reply(f"❌ {message.from_user.first_name} salah 3x! Lu kena kick dari match. Ketik /gabung buat main lagi.")

# --- CALLBACKS ---

@app.on_callback_query(filters.regex("join_game"))
async def join_callback(client, callback_query):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    if chat_id not in active_games:
        return await callback_query.answer("Lobby udah tutup.", show_alert=True)
    if user_id in active_games[chat_id]["players"]:
        return await callback_query.answer("Lu udah join!", show_alert=True)
    active_games[chat_id]["players"].append(user_id)
    await callback_query.answer("Berhasil join!")

@app.on_callback_query(filters.regex("start_match"))
async def start_match_callback(client, callback_query):
    chat_id = callback_query.message.chat.id
    if chat_id not in active_games: return
    if callback_query.from_user.id != active_games[chat_id]["host"]:
        return await callback_query.answer("Cuma host yang bisa mulai!", show_alert=True)
    
    soal = get_random_question(1)
    active_games[chat_id].update({
        "status": "playing",
        "answer": soal["answer"],
        "question": soal["question"],
        "swapped": False
    })
    await callback_query.message.edit_text(
        f"🚀 **Game Dimulai!**\n\nSoal: `{soal['question']}`\n\nJawab dengan reply pesan ini atau ketik langsung!"
    )

# --- COMMAND HINT ---
@app.on_message(filters.command("hint") & filters.group)
async def hint_cmd(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in active_games or active_games[chat_id].get("status") != "playing":
        return

    # Ambil data poin user dulu buat ngecek cukup gak (potong 15)
    from database import users # Akses koleksi users
    user_data = await users.find_one({"_id": user_id})
    if not user_data or user_data.get("point", 0) < 15:
        return await message.reply("Poin lu gak cukup buat beli hint! (Butuh 15 poin)")

    await update_point(user_id, -15)
    
    answer = active_games[chat_id]["answer"]
    # Logika hint: Kasih 1 huruf random dari jawaban
    hint_char = random.choice(answer.upper())
    
    await message.reply(
        f"🔍 **HINT DIGUNAKAN!**\n"
        f"Poin {message.from_user.first_name} dipotong 15.\n"
        f"Salah satu hurufnya adalah: `{hint_char}`"
    )

# --- COMMAND GANTI ---
@app.on_message(filters.command("ganti") & filters.group)
async def ganti_cmd(client, message):
    chat_id = message.chat.id
    if chat_id not in active_games or active_games[chat_id].get("status") != "playing":
        return

    if active_games[chat_id].get("swapped"):
        return await message.reply("Batas ganti soal cuma 1 kali per match!")

    # Ganti soal
    soal_baru = get_random_question(1)
    active_games[chat_id].update({
        "answer": soal_baru["answer"],
        "question": soal_baru["question"],
        "swapped": True # Tandai sudah ganti
    })
    
    await message.reply(
        f"🔄 **SOAL DIGANTI!**\n\n"
        f"Soal Baru: `{soal_baru['question']}`"
    )

# --- COMMAND TOP SCORE ---
@app.on_message(filters.command("top"))
async def top_score_cmd(client, message):
    from database import users
    
    # Ambil Top 10 dari MongoDB
    top_10 = await users.find().sort("point", -1).limit(10).to_list(length=10)
    
    text = "🏆 **TOP 10 PEMAIN BAKKATA** 🏆\n\n"
    for i, user in enumerate(top_10, 1):
        name = user.get("name", "Unknown")
        points = user.get("point", 0)
        text += f"{i}. {name} — `{points} pts`\n"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Cek Skor Saya", callback_data="my_score")]
    ])
    
    await message.reply(text, reply_markup=buttons)

# --- CALLBACK CEK SKOR SAYA ---
@app.on_callback_query(filters.regex("my_score"))
async def my_score_callback(client, callback_query):
    from database import users
    user_id = callback_query.from_user.id
    
    user_data = await users.find_one({"_id": user_id})
    if not user_data:
        return await callback_query.answer("Lu belum terdaftar di database!", show_alert=True)
    
    points = user_data.get("point", 0)
    level = user_data.get("level", 1)
    
    # Kalkulasi kurang berapa (Misal target ke level selanjutnya butuh 100 poin)
    next_level_pts = level * 100 
    remaining = next_level_pts - points if next_level_pts > points else 0
    
    msg = (
        f"👤 **PROFIL LU**\n\n"
        f"Nama: {callback_query.from_user.first_name}\n"
        f"Poin: `{points}`\n"
        f"Level: `{level}`\n"
    )
    if remaining > 0:
        msg += f"\nKurang `{remaining}` poin lagi buat naik ke level berikutnya!"
    else:
        msg += "\nLu udah siap buat naik level!"

    await callback_query.answer(msg, show_alert=True)

@app.on_message(filters.command("gabung") & filters.group)
async def gabung_cmd(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id not in active_games:
        return await message.reply("Gak ada game yang lagi jalan.")
    if user_id in active_games[chat_id]["players"]:
        return await message.reply("Lu udah ada di dalem game.")
    
    active_games[chat_id]["players"].append(user_id)
    # Reset hitungan salah kalau dia gabung lagi
    if "wrong_attempts" in active_games[chat_id]:
        active_games[chat_id]["wrong_attempts"][user_id] = 0
    await message.reply(f"✅ {message.from_user.first_name} berhasil gabung ke match!")

@app.on_message(filters.command("keluar") & filters.group)
async def keluar_cmd(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id not in active_games or user_id not in active_games[chat_id]["players"]:
        return await message.reply("Lu lagi gak main.")
    
    active_games[chat_id]["players"].remove(user_id)
    await message.reply(f"🚪 {message.from_user.first_name} keluar dari match.")

@app.on_message(filters.new_chat_members)
async def log_group_add(client, message):
    for member in message.new_chat_members:
        if member.id == (await client.get_me()).id:
            adder = message.from_user
            log_msg = (
                f"🏘 **Bot Added to Group**\n"
                f"Nama Grup: {message.chat.title}\n"
                f"ID Grup: {message.chat.id}\n"
                f"Yang Add: {adder.first_name} (@{adder.username} | {adder.id})"
            )
            await client.send_message(ADMIN_ID, log_msg)
            # Simpan ke DB grup
            await add_group_log(message.chat.id, message.chat.title, adder.id, adder.first_name)

# --- ADMIN PANEL ---
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_panel(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast User", callback_data="bc_user"), 
         InlineKeyboardButton("🏘 Broadcast Grup", callback_data="bc_group")],
        [InlineKeyboardButton("🎁 Airdrop Poin", callback_data="setup_airdrop")],
        [InlineKeyboardButton("📊 Statistik Bot", callback_data="bot_stats")]
    ])
    await message.reply("🛠 **Admin Panel Bakkata**\nSilakan pilih menu di bawah:", reply_markup=buttons)

# --- LOGIKA AIRDROP ADMIN ---
@app.on_callback_query(filters.regex("setup_airdrop") & filters.user(ADMIN_ID))
async def airdrop_callback(client, callback_query):
    # Lu bisa kasih input manual, tapi ini gua set default sesuai request lu
    poin_air = 50 
    soal_air = get_random_question(random.randint(5, 10)) # Ambil level susah
    
    from database import groups
    all_groups = await groups.find().to_list(length=1000)
    
    await callback_query.answer("Mengirim Airdrop ke semua grup...", show_alert=False)
    
    for g in all_groups:
        try:
            chat_id = g["_id"]
            # Set state airdrop di tiap grup
            active_games[chat_id] = {
                "status": "playing",
                "answer": soal_air["answer"],
                "question": soal_air["question"],
                "airdrop_points": poin_air,
                "is_airdrop": True,
                "players": "all" # Flag supaya siapa aja bisa jawab
            }
            await client.send_message(chat_id, f"🎁 **AIRDROP {poin_air} POIN MUNCUL!**\n\nSoal: `{soal_air['question']}`\n\n⏱ Siapa cepat dia dapat! Waktu 5 menit.")
        except: continue

    # Timer 5 Menit otomatis hapus airdrop
    await asyncio.sleep(300)
    for g in all_groups:
        cid = g["_id"]
        if cid in active_games and active_games[cid].get("is_airdrop"):
            del active_games[cid]
            try: await client.send_message(cid, "⌛️ Waktu airdrop habis!")
            except: pass

# --- UPDATE ANSWER HANDLER ---
@app.on_message(filters.group & ~filters.command(["mulai", "help", "start", "ganti", "hint", "top", "keluar", "gabung", "admin"]))
async def answer_handler(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in active_games or active_games[chat_id].get("status") != "playing":
        return

    game = active_games[chat_id]
    
    # Cek apakah ini match biasa (harus join) atau airdrop (bebas)
    is_airdrop = game.get("is_airdrop", False)
    if not is_airdrop and user_id not in game["players"]:
        return 

    user_answer = message.text.lower().strip()
    
    if user_answer == game["answer"]:
        poin_plus = game.get("airdrop_points", 10)
        await update_point(user_id, poin_plus)
        
        # Logika Airdrop: kalo udah kejawab satu orang, airdrop di grup itu ilang
        if is_airdrop:
            del active_games[chat_id]
            return await message.reply(f"🎉 {message.from_user.first_name} dapet Airdrop **{poin_plus}** poin!")

        # Logika Game Biasa
        from database import users
        u_data = await users.find_one({"_id": user_id})
        new_level = (u_data.get("point", 0) // 100) + 1
        
        await message.reply(f"✅ **BENAR!** (+10)\nSekarang level lu: {new_level}")
        
        # Soal baru berdasarkan level
        soal_baru = get_random_question(new_level)
        game.update({"answer": soal_baru["answer"], "question": soal_baru["question"], "swapped": False})
        await client.send_message(chat_id, f"Next Soal (Level {new_level}):\n`{soal_baru['question']}`")
        
    else:
        if not is_airdrop: # Salah di airdrop gak ngurangin poin (biar seru)
            await update_point(user_id, -5)
            if "wrong_attempts" not in game: game["wrong_attempts"] = {}
            game["wrong_attempts"][user_id] = game["wrong_attempts"].get(user_id, 0) + 1
            
            if game["wrong_attempts"][user_id] >= 3:
                game["players"].remove(user_id)
                game["wrong_attempts"][user_id] = 0
                await message.reply(f"❌ {message.from_user.first_name} salah 3x! Kena kick dari match. Ketik /gabung buat main lagi.")


@app.on_callback_query(filters.regex(r"bc_(user|group)") & filters.user(ADMIN_ID))
async def broadcast_handler(client, callback_query):
    target = callback_query.data.split("_")[1]
    await callback_query.message.reply(f"Silakan reply pesan ini dengan teks yang mau di-broadcast ke {target}!")

@app.on_message(filters.reply & filters.user(ADMIN_ID))
async def execute_broadcast(client, message):
    from database import users, groups
    msg_to_copy = message.reply_to_message
    count = 0
    
    # Ambil target berdasarkan kata kunci di pesan admin
    if "user" in message.text.lower():
        targets = await users.find().to_list(length=10000)
    else:
        targets = await groups.find().to_list(length=5000)

    sent_msg = await message.reply("⏳ Memulai broadcast...")
    for t in targets:
        try:
            await msg_to_copy.copy(t["_id"])
            count += 1
            if count % 20 == 0: # Tiap 20 pesan, istirahat sebentar
                await asyncio.sleep(1)
        except Exception:
            continue
    
    await sent_msg.edit(f"✅ Selesai! Berhasil mengirim ke {count} target.")
    
if __name__ == "__main__":
    print("Bot Bakkata Running...")
    app.run()
