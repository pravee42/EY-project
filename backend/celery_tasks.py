import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

from celery_app import celery_app
from scraper.scraper import scrape_all_sources
from agents.sales_agent import process_tenders_via_sales_agent
from agents.technical_agent import process_tenders_via_technical_agent
from agents.pricing_agent import process_tenders_via_pricing_agent
from agents.master_agent import process_tenders_via_master_agent
from database.mongo import tenders_collection, celery_tasks_collection
from bson import ObjectId

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("SMTP_APP_PASSWORD")

def send_email(to_email, subject, html_content):
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        logger.error("Mail credentials not found in .env")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

# --- Re-connect to Mongo for this worker process ---
# This is required because the module-level 'client' from mongo.py 
# might not be reliable after the fork/exec transition to Celery worker.
from pymongo import MongoClient
MONGO_URI_LOCAL = os.getenv("MONGO_URI", "mongodb+srv://admin:admin@cluster0.f1ccp3c.mongodb.net/")

def get_db_collections():
    try:
        # Create a fresh local connection for this thread/process
        _client = MongoClient(MONGO_URI_LOCAL)
        _db = _client["rfp_yukti"]
        return _db['tenders'], _db['celery_tasks']
    except Exception as e:
        logger.error(f"Failed to connect to local Mongo: {e}")
        return None, None

def update_task_status(task_id, stage, status, details=None):
    """Helper to update task status in MongoDB"""
    # Get fresh collection reference
    _, _tasks_col = get_db_collections()
    
    if _tasks_col is None:
        logger.error("Could not get celery_tasks_collection for update.")
        return
        
    update_data = {
        "current_stage": stage,
        "status": status,
        "updated_at": datetime.now()
    }
    if details:
        update_data["details"] = details
        
    try:
        _tasks_col.update_one(
            {"task_id": task_id},
            {"$set": update_data},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to write to MongoDB: {e}")

@celery_app.task(name="run_full_tender_pipeline", bind=True)
def run_full_tender_pipeline(self):
    task_id = self.request.id
    logger.info(f"Starting full tender pipeline task {task_id}...")
    
    # Initialize task record
    _, _tasks_col = get_db_collections()
    if _tasks_col is not None:
        try:
            _tasks_col.insert_one({
                "task_id": task_id,
                "status": "RUNNING",
                "current_stage": "INIT",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "details": {}
            })
        except Exception as e:
            logger.error(f"Failed to insert init task record: {e}")

    try:
        # 1. Scrape
        update_task_status(task_id, "SCRAPING", "RUNNING")
        logger.info("Step 1: Scraping...")
        scraped_tenders = scrape_all_sources()
        logger.info(f"Scraped {len(scraped_tenders)} tenders.")
        
        # Save Scraped Tenders to DB (Critical Step missed before)
        _tenders_col, _ = get_db_collections()
        new_count = 0
        if _tenders_col is not None:
            for tender_data in scraped_tenders:
                try:
                    # Check duplicate by title
                    if not _tenders_col.find_one({"title": tender_data["title"]}):
                        _tenders_col.insert_one(tender_data)
                        new_count += 1
                except Exception as insert_error:
                    logger.error(f"Error inserting tender in Celery task: {insert_error}")
        
        logger.info(f"Celery Scrape finished. Found {len(scraped_tenders)}, Inserted {new_count} new.")
        update_task_status(task_id, "SCRAPING", "COMPLETED", {"scraped_count": len(scraped_tenders), "inserted_count": new_count})
        
        # 2. Sales Agent
        update_task_status(task_id, "SALES_AGENT", "RUNNING")
        logger.info("Step 2: Sales Agent...")
        sales_ids = process_tenders_via_sales_agent(limit=50)
        update_task_status(task_id, "SALES_AGENT", "COMPLETED", {"sales_processed": len(sales_ids)})
        
        # 3. Technical Agent
        update_task_status(task_id, "TECHNICAL_AGENT", "RUNNING")
        logger.info("Step 3: Technical Agent...")
        tech_ids = process_tenders_via_technical_agent(limit=50)
        update_task_status(task_id, "TECHNICAL_AGENT", "COMPLETED", {"technical_processed": len(tech_ids)})
        
        # 4. Pricing Agent
        update_task_status(task_id, "PRICING_AGENT", "RUNNING")
        logger.info("Step 4: Pricing Agent...")
        price_ids = process_tenders_via_pricing_agent(limit=50)
        update_task_status(task_id, "PRICING_AGENT", "COMPLETED", {"pricing_processed": len(price_ids)})
        
        # 5. Master Agent
        update_task_status(task_id, "MASTER_AGENT", "RUNNING")
        logger.info("Step 5: Master Agent...")
        master_ids = process_tenders_via_master_agent(limit=50)
        update_task_status(task_id, "MASTER_AGENT", "COMPLETED", {"master_processed": len(master_ids)})
        
        logger.info(f"Pipeline finished. Master processed IDs: {master_ids}")
        
        # 6. Send Emails
        update_task_status(task_id, "EMAIL_NOTIFICATION", "RUNNING")
        if master_ids:
            _tenders_col, _ = get_db_collections() # Get fresh tender col
            
            for tender_id in master_ids:
                try:
                    if _tenders_col is not None:
                        tender = _tenders_col.find_one({"_id": ObjectId(tender_id)})
                        if tender:
                            final_report = tender.get("final_report_json", {})
                            
                            from jinja2 import Environment, FileSystemLoader
                            template_dir = os.path.join(os.path.dirname(__file__), "templates")
                            env = Environment(loader=FileSystemLoader(template_dir))
                            template = env.get_template("report_template.html")
                            
                            html_content = template.render(**final_report)
                            
                            subject = f"New Tender Report Processed: {final_report.get('tender_title', 'Untitled')}"
                            send_email("praveen@abipravi.in", subject, html_content)
                        
                except Exception as e:
                    logger.error(f"Error sending email for tender {tender_id}: {e}")
        
        update_task_status(task_id, "COMPLETED", "SUCCESS", {
            "scraped": len(scraped_tenders),
            "sales_processed": len(sales_ids),
            "technical_processed": len(tech_ids),
            "pricing_processed": len(price_ids),
            "master_processed": len(master_ids)
        })
        
        return {
            "scraped": len(scraped_tenders),
            "sales_processed": len(sales_ids),
            "technical_processed": len(tech_ids),
            "pricing_processed": len(price_ids),
            "master_processed": len(master_ids)
        }

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        update_task_status(task_id, "FAILED", "ERROR", {"error": str(e)})
        raise e

@celery_app.task(name="reprocess_single_tender", bind=True)
def reprocess_single_tender(self, tender_id: str):
    task_id = self.request.id
    logger.info(f"Starting targeted re-analysis for tender {tender_id} (Task {task_id})...")
    
    # Initialize Status
    _, _tasks_col = get_db_collections()
    if _tasks_col is not None:
         _tasks_col.insert_one({
            "task_id": task_id,
            "status": "RUNNING",
            "current_stage": "INIT",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "details": {"tender_id": tender_id, "type": "TARGETED_ANALYSIS"}
        })

    try:
        # Sales Agent
        update_task_status(task_id, "SALES_AGENT", "RUNNING")
        process_tenders_via_sales_agent(tender_id=tender_id)
        
        # Technical Agent
        update_task_status(task_id, "TECHNICAL_AGENT", "RUNNING")
        process_tenders_via_technical_agent(tender_id=tender_id)
        
        # Pricing Agent
        update_task_status(task_id, "PRICING_AGENT", "RUNNING")
        process_tenders_via_pricing_agent(tender_id=tender_id)
        
        # Master Agent
        update_task_status(task_id, "MASTER_AGENT", "RUNNING")
        process_tenders_via_master_agent(tender_id=tender_id)
        
        update_task_status(task_id, "COMPLETED", "SUCCESS", {"tender_id": tender_id})
        logger.info(f"Targeted re-analysis completed for {tender_id}")
        
    except Exception as e:
        logger.error(f"Re-analysis failed: {e}")
        update_task_status(task_id, "FAILED", "ERROR", {"error": str(e)})
