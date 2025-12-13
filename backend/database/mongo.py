import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://admin:admin@cluster0.f1ccp3c.mongodb.net/")

try:
    client = MongoClient(MONGO_URI, connect=False, uuidRepresentation="standard")
    # client.admin.command('ping') -> Removed to allow lazy connection for Celery fork safety
    # print("Connected to MongoDB successfully.")

    db = client["rfp_yukti"]
    tenders_collection = db['tenders']
    inventory_collection = db['inventory']
    test_pricing_collection = db['test_pricing']
    celery_tasks_collection = db['celery_tasks']
    chat_sessions_collection = db['chat_sessions']
    
    # Create indexes
    tenders_collection.create_index("title", unique=True)
    tenders_collection.create_index("scraped_at")
    inventory_collection.create_index("sku_id", unique=True)
    test_pricing_collection.create_index("test_name", unique=True)
    chat_sessions_collection.create_index("updated_at")

except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    # In a real app, you might want to raise the error or handle it more gracefully
    # For now, we'll proceed, but operations might fail if client isn't connected
    client = None

if not client:
    tenders_collection = None
    inventory_collection = None
    test_pricing_collection = None
    celery_tasks_collection = None
    chat_sessions_collection = None
