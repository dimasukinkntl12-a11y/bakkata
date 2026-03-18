import os
from motor.motor_asyncio import AsyncIOMotorClient

# Ambil dari env (Railway)
MONGO_URI = os.getenv("MONGO_URI")
client = AsyncIOMotorClient(MONGO_URI)
db = client["bakkata_db"]

# Koleksi data
users = db["users"]
groups = db["groups"]
logs = db["logs"]
# Tambahin koleksi buat nyimpen settingan Admin
settings = db["settings"]

# --- SETTINGS HELPERS (PENTING BUAT FSUB & ADMIN) ---
async def get_setting(key, default=None):
    """Ambil settingan dari DB (seperti status fsub atau link dev)"""
    res = await settings.find_one({"_id": key})
    return res["value"] if res else default

async def set_setting(key, value):
    """Simpan settingan ke DB"""
    await settings.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

async def add_user_log(user_id, name, username):
    """Log tiap orang klik start pertama kali"""
    user = await users.find_one({"_id": user_id})
    if not user:
        data = {
            "_id": user_id,
            "name": name,
            "username": username,
            "point": 0,
            "balance": 0, # Tambah saldo buat Gacha
            "level": 1 
        }
        await users.insert_one(data)
        await logs.insert_one({"type": "start_first_time", "user_id": user_id, "name": name})
        return True
    return False

async def add_group_log(group_id, group_name, added_by_id, added_by_name):
    """Log tiap bot di-add ke grup"""
    group = await groups.find_one({"_id": group_id})
    if not group:
        data = {
            "_id": group_id,
            "group_name": group_name,
            "added_by_id": added_by_id,
            "added_by_name": added_by_name,
            "log_enabled": True
        }
        await groups.insert_one(data)
        return True
    return False

# Tambahin parameter q_score di fungsi update_point
async def update_point(user_id, amount, q_score=0, gelar="Easy"):
    user = await users.find_one({"_id": user_id})
    if not user: return
    
    new_point = max(0, user.get("point", 0) + amount)
    
    # Ambil rekor Q lama, kalau gak ada anggap 0
    high_q = user.get("high_q", 0)
    
    update_data = {"$set": {"point": new_point}}
    
    # Kalau Q sekarang lebih tinggi dari rekor, update High Q & High Gelar
    if q_score > high_q:
        update_data["$set"]["high_q"] = q_score
        update_data["$set"]["high_gelar"] = gelar
        
    await users.update_one({"_id": user_id}, update_data)

async def get_top_players():
    """Ambil data buat /top"""
    return await users.find().sort("point", -1).limit(10).to_list(length=10)
