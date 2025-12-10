import os
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://admin:admin@cluster0.f1ccp3c.mongodb.net/")

try:
    client = MongoClient(MONGO_URI)
    # Ping the database to check connection
    client.admin.command('ping')
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    # In a real app, you might want to raise the error or handle it more gracefully
    # For now, we'll proceed, but operations might fail if client isn't connected
    client = None

if client:
    db = client["rfp_yukti"]
    tenders_collection = db["tenders"]
else:
    tenders_collection = None
