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

# --- DATABASE SETTINGS HELPERS --
async def get_setting(key, default=None):
    # Langsung panggil db dari database.py
    from database import db
    res = await db.settings.find_one({"_id": key})
    return res["value"] if res else default

async def set_setting(key, value):
    from database import db
    await db.settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)
    
# Inisialisasi akses database ke client (tambahkan ini agar app punya akses db)
async def init_db(client):
    from database import db # Pastikan variabel 'db' di database.py bisa diakses
    client.db = db

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
    # Cek user baru buat notif log
    is_new = await users.find_one({"_id": user.id}) is None
    await add_user_log(user.id, user.first_name, user.username)
    
    if is_new:
        res = await get_setting("log")
        if res:
            try:
                log_id = int(res) # Pastikan jadi Integer
                await client.send_message(log_id, f"🆕 **USER BARU**\n👤 {user.first_name}\n🆔 `{user.id}`\n🔗 @{user.username or '-'}")
            except: pass
    
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

@app.on_message(filters.command("bantuan"))
async def help_cmd(client, message):
    help_text = await get_setting("help", "📖 **CARA MAIN BAKKATA**\n\nKetik /mulai di grup.")
    await message.reply(help_text)

@app.on_callback_query(filters.regex("show_help"))
async def help_callback(client, callback_query):
    await callback_query.edit_message_text("📖 Silahkan cek menu bantuan dengan perintah /help di grup atau di sini.")

@app.on_message(filters.command("main") & filters.group)
async def mulai_handler(client, message):
    chat_id = message.chat.id
    if chat_id in active_games: return await message.reply("Lobby masih terbuka atau game sedang jalan!")
    
    # Tambahin swapped_users biar jatah ganti 1x per orang
    active_games[chat_id] = {
        "host": message.from_user.id, 
        "players": [message.from_user.id], 
        "status": "lobby",
        "swapped_users": [] 
    }
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Join", callback_data="join_game")],[InlineKeyboardButton("Mulai", callback_data="start_match")]])
    await message.reply(f"🎮 **Lobby Bakkata Dibuka!**\n\nHost: {message.from_user.first_name}\nTotal Player: 1", reply_markup=buttons)

@app.on_message(filters.command("suit") & filters.group)
async def suit_handler(client, message):
    chat_id = message.chat.id
    if chat_id in active_games: 
        return await message.reply("Lobby game lain masih aktif di grup ini!")
    
    active_games[chat_id] = {
        "type": "suit",
        "host": message.from_user.id,
        "players": [message.from_user.id],
        "status": "lobby",
        "choices": {} # Buat nyimpen pilihan: {user_id: "batu"}
    }
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("Join Suit 🤝", callback_data="join_suit")]
    ])
    
    await message.reply(
        f"🎮 **Lobby Suit Dibuka!**\n\n"
        f"Host: {message.from_user.first_name}\n"
        f"Slot: 1/2\n\n"
        "Klik join buat adu mekanik!", 
        reply_markup=buttons
    )

@app.on_message(filters.command("gacha") & filters.group)
async def gacha_group_notif(client, message):
    await message.reply("❌ **Gacha dilarang di grup!**\nSilahkan ke private chat @bot buat main biar gak berisik.")

@app.on_message(filters.command("gacha") & filters.private)
async def gacha_cmd(client, message):
    uid = message.from_user.id
    u_data = await users.find_one({"_id": uid})
    
    # Ambil poin & saldo (kasih default 0 kalau gak ada)
    point = u_data.get("point", 0) if u_data else 0
    balance = u_data.get("balance", 0) if u_data else 0

    text = (
        f"🎰 MENU GACHA BAKKATA\n\n"
        f"💰 Saldo: `Rp{balance:,}`\n"
        f"💎 Poin: `{point} pts`\n\n"
        f"🎫 Biaya: `1.000 pts` / Spin\n"
        f"🎁 Hadiah: `Rp100` - `Rp100.000`"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 SPIN SEKARANG (1000 pts)", callback_data="spin_gacha")],
        [InlineKeyboardButton("💳 Withdraw", callback_data="ask_wd"), InlineKeyboardButton("📊 Cek Saldo", callback_data="cek_saldo")]
    ])
    await message.reply(text, reply_markup=buttons)

# --- GAME ENGINE ---
@app.on_message(filters.group & ~filters.command(["main", "bantuan", "start", "ganti", "top", "keluar", "masuk", "admin", "stop"]))
async def bakkata_engine(client, message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id or chat_id not in active_games or active_games[chat_id].get("status") != "playing": return
    
    game = active_games[chat_id]
    is_airdrop = game.get("is_airdrop", False)

    # Validasi jawaban
    input_word = message.text.lower().strip()
    
    # Syarat jawab: 
    # 1. Kalau game biasa: Wajib reply bot DAN sudah join/masuk.
    # 2. Kalau airdrop: Bebas siapa aja asal bener.
    if not is_airdrop:
        if not message.reply_to_message: return
        me = await client.get_me()
        if message.reply_to_message.from_user.id != me.id: return
        if user_id not in game["players"]: return

    if (len(input_word) == game["length"] and input_word.startswith(game["prefix"]) and input_word.endswith(game["suffix"]) and input_word in ALL_WORDS):
        poin = game.get("airdrop_points", 10)
        await update_point(user_id, poin)
        
        if is_airdrop:
            del active_games[chat_id]
            return await message.reply(f"🎁 **AIRDROP DIAMBIL!**\n👤 {message.from_user.mention} dapet {poin} pts!\n\nGame selesai. Ketik /main buat main bareng lagi.")
        # --------------------------------------------------
        
        u_data = await users.find_one({"_id": user_id})
        pts = u_data.get("point", 0) if u_data else poin
        new_level = (pts // 100) + 1
        soal = generate_pattern_question(min(3 + new_level, 15))
        
        game.update({"prefix": soal["prefix"], "suffix": soal["suffix"], "length": soal["length"], "swapped": False})
        if "wrong" in game: game["wrong"][user_id] = 0

        # Tambah info jumlah huruf di sini
        await message.reply(f"✅ **BENAR!** ({input_word.upper()})\n👤 {message.from_user.mention}\n📈 Level: {new_level} ({pts} pts)\n\n**NEXT ({soal['length']} Huruf):** `{soal['pattern']}`\n👉 Reply buat jawab!")
    else:
        # Pinalti cuma buat game biasa, airdrop jangan (biar gak spam poin minus)
        if not is_airdrop:
            await update_point(user_id, -5)
            if "wrong" not in game: game["wrong"] = {}
            game["wrong"][user_id] = game["wrong"].get(user_id, 0) + 1
            if game["wrong"][user_id] >= 3:
                if user_id in game["players"]: game["players"].remove(user_id)
                await message.reply(f"💀 {message.from_user.mention} DIKICK! (Salah 3x)\nJangan baper ya, main lagi nanti! ketik /masuk")
                
                if not game["players"]:
                    del active_games[chat_id]
                    await message.reply("💀 **GAME OVER!** Semua pemain telah gugur. Ketik /main lagi buat mulai baru.")
            else:
                await message.reply(f"⚠️ {message.from_user.mention} **SALAH!** (-5 pts)")
                
# --- COMMANDS ---
@app.on_message(filters.command("masuk") & filters.group)
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
@app.on_message(filters.command("ganti") & filters.group)
async def ganti_cmd(client, message):
    cid, uid = message.chat.id, message.from_user.id
    if cid not in active_games or active_games[cid].get("status") != "playing": return
    
    game = active_games[cid]
    if uid not in game["players"]: return await message.reply("❌ Lu gak ikut main!")
    
    # Cek list swapped_users
    if uid in game.get("swapped_users", []):
        return await message.reply(f"❌ {message.from_user.mention}, jatah ganti lu udah abis!")
    
    soal = generate_pattern_question(game["length"])
    game.update({"prefix": soal["prefix"], "suffix": soal["suffix"]})
    
    # Masukin ID user ke daftar yang udah pake jatah ganti
    game.setdefault("swapped_users", []).append(uid)
    
    await message.reply(f"🔄 **SOAL DIGANTI!**\nOleh: {message.from_user.mention}\n\nBaru: `{soal['pattern']}`")
    
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
    cid, uid = message.chat.id, message.from_user.id
    if cid in active_games:
        # Cek apakah yang stop adalah Host atau salah satu Player
        if uid == active_games[cid].get("host") or uid in active_games[cid].get("players", []):
            del active_games[cid]
            await message.reply("🛑 Game dihentikan oleh peserta.")
        else:
            await message.reply("❌ Lu nggak ikut main, jangan stop sembarangan!")

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
        [InlineKeyboardButton("📊 Stats", callback_data="bot_stats"), InlineKeyboardButton("⚙️ Settings", callback_data="bot_settings")],
        [InlineKeyboardButton("📢 BC User", callback_data="bc_user"), InlineKeyboardButton("👥 BC Grup", callback_data="bc_group")],
        [InlineKeyboardButton("🎰 Gacha Chance", callback_data="set_gacha_btn"), InlineKeyboardButton("🎁 Airdrop", callback_data="setup_airdrop")],
        [InlineKeyboardButton("💰 Manage User", callback_data="manage_user")]
    ])
    await message.reply("🛠 **Admin Panel Bakkata**", reply_markup=buttons)
# --- CALLBACKS ---
# Tambahin ini di bawah fungsi admin_panel lu
@app.on_callback_query(filters.regex("manage_user") & filters.user(ADMIN_ID))
async def manage_user_cb(client, callback_query):
    chat_id = callback_query.message.chat.id
    # Pakai pyromod.listen buat nanya
    ask_id = await client.ask(chat_id, "🔢 **SET POIN/SALDO**\nMasukkan ID User:")
    target_id = int(ask_id.text)
    
    ask_type = await client.ask(chat_id, "Mau set apa? (ketik: **poin** atau **saldo**):")
    tipe = "point" if "poin" in ask_type.text.lower() else "balance"
    
    ask_val = await client.ask(chat_id, f"Masukkan jumlah {tipe} baru:")
    val = int(ask_val.text)
    
    # Update ke database
    await users.update_one({"_id": target_id}, {"$set": {tipe: val}})
    await ask_val.reply(f"✅ Berhasil! User `{target_id}` sekarang punya {val} {tipe}.")

@app.on_callback_query(filters.regex("my_score"))
async def my_score_callback(client, callback_query):
    u = await users.find_one({"_id": callback_query.from_user.id})
    score = u.get("point", 0) if u else 0
    await callback_query.answer(f"Skor lu: {score} pts", show_alert=True)

@app.on_callback_query(filters.regex(r"^(join_suit|pilih_suit_)"))
async def suit_callback(client, callback_query):
    data = callback_query.data
    cid = callback_query.message.chat.id
    uid = callback_query.from_user.id
    
    if cid not in active_games or active_games[cid].get("type") != "suit":
        return await callback_query.answer("Game udah gak aktif.", show_alert=True)

    game = active_games[cid]

    # --- LOGIC JOIN ---
    if data == "join_suit":
        if uid in game["players"]:
            return await callback_query.answer("Lu udah di dalem lobby!", show_alert=True)
        if len(game["players"]) >= 2:
            return await callback_query.answer("Lobby penuh!", show_alert=True)
        
        game["players"].append(uid)
        game["status"] = "playing"
        
        # Langsung ganti tampilan jadi menu pilih
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✊ Batu", callback_data="pilih_suit_batu"),
                InlineKeyboardButton("🖐 Kertas", callback_data="pilih_suit_kertas"),
                InlineKeyboardButton("✌️ Gunting", callback_data="pilih_suit_gunting")
            ]
        ])
        await callback_query.message.edit_text(
            f"🚀 Game Dimulai!\n\n"
            f"Pemain: {len(game['players'])}/2\n"
            "Silahkan pilih di bawah ini!",
            reply_markup=buttons
        )

    # --- LOGIC PILIH ---
    elif data.startswith("pilih_suit_"):
        if uid not in game["players"]:
            return await callback_query.answer("Lu bukan pemain!", show_alert=True)
        
        if uid in game["choices"]:
            return await callback_query.answer("Lu udah milih, tunggu lawan!", show_alert=True)
        
        pilihan = data.split("_")[2]
        game["choices"][uid] = pilihan
        await callback_query.answer(f"Lu milih {pilihan.upper()}!", show_alert=True)

        # Kalau dua-duanya udah milih, tentukan pemenang
        if len(game["choices"]) == 2:
            p1_id, p2_id = game["players"]
            p1_choice = game["choices"][p1_id]
            p2_choice = game["choices"][p2_id]
            
            # Ambil mention nama
            p1_name = (await client.get_users(p1_id)).first_name
            p2_name = (await client.get_users(p2_id)).first_name

            # Aturan Suit
            rules = {"batu": "gunting", "kertas": "batu", "gunting": "kertas"}
            
            result_text = f"🏁 HASIL SUIT\n\n👤 {p1_name}: {p1_choice.upper()}\n👤 {p2_name}: {p2_choice.upper()}\n\n"
            
            if p1_choice == p2_choice:
                result_text += "⚖️ HASILNYA SERI!"
            elif rules[p1_choice] == p2_choice:
                result_text += f"🏆 {p1_name.upper()} MENANG!"
            else:
                result_text += f"🏆 {p2_name.upper()} MENANG!"
            
            del active_games[cid] # Hapus game setelah selesai
            await callback_query.message.edit_text(result_text)

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
    await callback_query.message.edit_text(f"🚀 Game Dimulai!\n\nSoal ({soal['length']} Huruf): `{soal['pattern']}`\nReply buat jawab!")

@app.on_callback_query(filters.regex("setup_airdrop") & filters.user(ADMIN_ID))
async def airdrop_callback(client, callback_query):
    soal = generate_pattern_question(random.randint(6, 8))
    all_g = await groups.find().to_list(1000)
    for g in all_g:
        try:
            active_games[g["_id"]] = {
                "status": "playing", 
                "is_airdrop": True, 
                "airdrop_points": 50, 
                "prefix": soal["prefix"], 
                "suffix": soal["suffix"], 
                "length": soal["length"],
                "pattern": soal["pattern"] # Tambahkan ini biar konsisten
            }
            await client.send_message(g["_id"], f"🎁 **AIRDROP 50 POIN!**\n\nSoal ({soal['length']} Huruf): `{soal['pattern']}`\n👉 Langsung jawab (tanpa masuk lobby)!")
            await asyncio.sleep(0.3)
        except: continue
    await callback_query.answer("Airdrop disebar!")
    
@app.on_callback_query(filters.regex("bot_stats") & filters.user(ADMIN_ID))
async def stats_callback(client, callback_query):
    total_users = await users.count_documents({})
    total_groups = await groups.count_documents({})
    
    stat_text = (
        f"📊 **STATISTIK BOT**\n\n"
        f"👤 Total User: `{total_users}`\n"
        f"👥 Total Grup: `{total_groups}`"
    )
    await callback_query.message.edit_text(
        stat_text, 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_admin")]])
    )

@app.on_callback_query(filters.regex("back_to_admin") & filters.user(ADMIN_ID))
async def back_to_admin(client, callback_query):
    # Panggil lagi fungsi admin_panel biar balik ke menu awal
    await admin_panel(client, callback_query.message)

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

@app.on_callback_query(filters.regex(r"^wd_done_") & filters.user(ADMIN_ID))
async def wd_done_callback(client, callback_query):
    # Format data: wd_done_{user_id}_{nominal}
    data = callback_query.data.split("_")
    target_uid = int(data[2])
    nominal = int(data[3])
    
    try:
        # 1. Kirim notif ke User kalau duit sudah cair
        notif_text = (
            f"💰 WITHDRAW CAIR!\n\n"
            f"Halo, penarikan saldo lu sebesar **Rp{nominal:,}** udah ditransfer sama Admin ya.\n"
            f"Silahkan cek rekening/e-wallet lu. Makasih udah main!"
        )
        await client.send_message(target_uid, notif_text)
        
        # 2. Update pesan di admin biar gak bingung mana yang udah dikerjain
        await callback_query.edit_message_text(
            f"{callback_query.message.text}\n\n✅ **STATUS: SELESAI DITRANSFER**"
        )
        await callback_query.answer("Notif berhasil dikirim ke user!", show_alert=True)
        
    except Exception as e:
        await callback_query.answer(f"Gagal kirim notif: {e}", show_alert=True)

@app.on_callback_query(filters.regex(r"^(spin_gacha|cek_saldo|ask_wd)"))
async def gacha_system_callback(client, callback_query):
    uid = callback_query.from_user.id
    cid = callback_query.message.chat.id
    data = callback_query.data
    
    # Tarik data user terbaru dari DB biar gak bisa manipulasi saldo
    u_data = await users.find_one({"_id": uid})
    if not u_data:
        return await callback_query.answer("Data lu belum kedaftar, chat /start dulu!", show_alert=True)

    # --- 1. LOGIC SPIN GACHA ---
    if data == "spin_gacha":
        if u_data.get("point", 0) < 1000:
            return await callback_query.answer("Poin lu kurang (Min 1000 pts)!", show_alert=True)

        # Potong poin dulu biar gak bisa double klik (spam)
        await users.update_one({"_id": uid}, {"$inc": {"point": -1000}})
        
        # Animasi Gacha
        msg = callback_query.message
        anim = ["🎰 | 🎰 | 🎰", "🍎 | 🎰 | 🎰", "🍎 | 💎 | 🎰", "🍎 | 💎 | 💰"]
        for a in anim:
            await msg.edit_text(f"SPIN BERLANGSUNG...\n\n`{a}`")
            await asyncio.sleep(0.5)

        # Ambil chance dari setting admin (kalau belum ada, pake default)
        weights = await get_setting("gacha_chance", [70, 20, 8, 1.5, 0.5])
        hadiah_list = [100, 1000, 10000, 50000, 100000]
        hasil = random.choices(hadiah_list, weights=weights)[0]
        
        # Update saldo hasil menang
        await users.update_one({"_id": uid}, {"$inc": {"balance": hasil}})
        
        await msg.edit_text(
            f"🎉 JACKPOT!\n\nLu dapet: **Rp{hasil:,}**\nSaldo sekarang: `Rp{u_data.get('balance', 0) + hasil:,}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Lagi 🎰", callback_data="spin_gacha")]])
        )

    # --- 2. CEK SALDO ---
    elif data == "cek_saldo":
        await callback_query.answer(f"Saldo lu: Rp{u_data.get('balance', 0):,}", show_alert=True)

    # --- 3. SISTEM WITHDRAW (WD) ---
    elif data == "ask_wd":
        balance = u_data.get("balance", 0)
        if balance < 50000:
            return await callback_query.answer("Minimal Withdraw Rp50.000!", show_alert=True)
            
        # Tutup notif loading di tombol
        await callback_query.answer()

        try:
            # Pake pyromod buat nanya detail
            ask_bank = await client.ask(cid, "🏦 FORM WITHDRAW\n\nKetik: Nama Bank/E-Wallet & Nomor Rekening\nContoh: `DANA - 08123456789`", filters=filters.text)
            rekening = ask_bank.text
            
            ask_nominal = await client.ask(cid, f"💰 SALDO LU: `Rp{balance:,}`\n\nMau tarik berapa? (Ketik angkanya aja):", filters=filters.text)
            
            # Cek input angka atau bukan
            if not ask_nominal.text.isdigit():
                return await client.send_message(cid, "❌ Input harus angka!")
            
            nominal = int(ask_nominal.text)
            
            if nominal < 50000:
                return await client.send_message(cid, "❌ Minimal tarik Rp50.000!")
            if nominal > balance:
                return await client.send_message(cid, "❌ Saldo lu gak cukup buat narik segitu!")

            # POTONG SALDO DULU (Biar user gak bisa WD berkali-kali sebelum admin proses)
            await users.update_one({"_id": uid}, {"$inc": {"balance": -nominal}})
    
            # Lapor ke Admin dengan Tombol Done
            log_text = (
                f"🚨 **ADA YANG WD NIH!**\n\n"
                f"👤 User: {callback_query.from_user.mention} (`{uid}`)\n"
                f"🏦 Bank: `{rekening}`\n"
                f"💵 Nominal: `Rp{nominal:,}`\n"
                f"💎 Sisa Saldo: `Rp{balance - nominal:,}`"
            )
            
            # Tambahin tombol buat admin klik kalau sudah transfer
            btn_admin = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ DONE (SUDAH TF)", callback_data=f"wd_done_{uid}_{nominal}")]
            ])
            
            await client.send_message(ADMIN_ID, log_text, reply_markup=btn_admin)
            
            # Notif ke User
            await client.send_message(cid, "✅ WD BERHASIL DIAJUKAN!\nPermintaan lu udah masuk ke admin. Tunggu dana cair ya!")
            
        except Exception as e:
            # Kalau user kelamaan gak jawab atau error lain
            await client.send_message(cid, "❌ Gagal memproses WD. Pastikan lu jawab pesan bot dengan bener.")

@app.on_callback_query(filters.regex("set_gacha_btn") & filters.user(ADMIN_ID))
async def set_gacha_chance_cb(client, callback_query):
    cid = callback_query.message.chat.id
    
    # Ambil settingan sekarang biar lu tau sebelumnya berapa
    current = await get_setting("gacha_chance", [70, 20, 8, 1.5, 0.5])
    
    guide_text = (
        "⚙️ **SETTING PERSENTASE GACHA**\n\n"
        f"Persentase saat ini:\n"
        f"▫️ Rp100: `{current[0]}%` (Ampas)\n"
        f"▫️ Rp1.000: `{current[1]}%` (Biasa)\n"
        f"▫️ Rp10.000: `{current[2]}%` (Lumayan)\n"
        f"▫️ Rp50.000: `{current[3]}%` (Jackpot 1)\n"
        f"▫️ Rp100.000: `{current[4]}%` (Jackpot 2)\n\n"
        "**Format Input:**\n"
        "Kirim 5 angka dipisah spasi. Total harus 100.\n"
        "Contoh: `80 15 4 0.9 0.1`"
    )
    
    await callback_query.answer() # Biar loading tombol ilang
    ask = await client.ask(cid, guide_text, filters=filters.text)
    
    try:
        # Pecah input jadi list angka
        new_val = [float(x) for x in ask.text.split()]
        
        if len(new_val) != 5:
            return await ask.reply("❌ Harus 5 angka, Yan! Ulangi.")
            
        # Update ke database
        await set_setting("gacha_chance", new_val)
        await ask.reply(f"✅ **BERHASIL!** Peluang gacha udah diupdate.")
        
    except:
        await ask.reply("❌ Format salah! Pastikan cuma angka dan spasi.")
            
@app.on_message(filters.new_chat_members)
async def new_group_log(client, message):
    me = await client.get_me() # Ganti bagian ini
    for member in message.new_chat_members:
        if member.id == me.id:
            chat = message.chat
            await add_group_log(chat.id, chat.title, message.from_user.id, message.from_user.first_name)
            log_id = await get_setting("log")
            if log_id:
                try: 
                    await client.send_message(log_id, f"➕ **BOT MASUK GRUP BARU**\n📍 {chat.title}\n🆔 `{chat.id}`\n👤 Oleh: {message.from_user.mention}")
                except Exception as e: 
                    print(f"Log Error: {e}")

async def main():
    await app.start()
    from database import db
    app.db = db 

if __name__ == "__main__":
    # app.run() otomatis handle start, idle, dan stop
    print(">>> BOT BAKKATA BERHASIL NYALA! <<<")
    app.run()
