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
            "level": 1 # Nanti narik dari 1.txt
        }
        await users.insert_one(data)
        # Log untuk admin
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
    """Update poin (+10, -5, -15)"""
    await users.update_one({"_id": user_id}, {"$inc": {"point": amount}})

async def get_top_players():
    """Buat command /top"""
    return await users.find().sort("point", -1).limit(10).to_list(length=10)
