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

async def add_user_log(user_id, name, username):
    """Log tiap orang klik start pertama kali"""
    user = await users.find_one({"_id": user_id})
    if not user:
        data = {
            "_id": user_id,
            "name": name,
            "username": username,
            "point": 0,
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

async def update_point(user_id, amount):
    """Update poin & Leveling Otomatis"""
    # 1. Update poin (dengan minimal 0, biar gak minus parah)
    user = await users.find_one({"_id": user_id})
    if not user: return
    
    new_point = max(0, user.get("point", 0) + amount)
    
    # 2. Hitung level baru (tiap 100 poin naik 1 level)
    # Level 1 (0-99), Level 2 (100-199), dst.
    new_level = (new_point // 100) + 1
    
    await users.update_one(
        {"_id": user_id}, 
        {"$set": {"point": new_point, "level": new_level}}
    )

async def get_top_players():
    """Ambil data buat /top"""
    return await users.find().sort("point", -1).limit(10).to_list(length=10)
