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

def update_task_status(task_id, stage, status, details=None):
    """Helper to update task status in MongoDB"""
    if celery_tasks_collection is None:
        return
        
    update_data = {
        "current_stage": stage,
        "status": status,
        "updated_at": datetime.now()
    }
    if details:
        update_data["details"] = details
        
    celery_tasks_collection.update_one(
        {"task_id": task_id},
        {"$set": update_data},
        upsert=True
    )

@celery_app.task(name="run_full_tender_pipeline", bind=True)
def run_full_tender_pipeline(self):
    task_id = self.request.id
    logger.info(f"Starting full tender pipeline task {task_id}...")
    
    # Initialize task record
    if celery_tasks_collection is not None:
        celery_tasks_collection.insert_one({
            "task_id": task_id,
            "status": "RUNNING",
            "current_stage": "INIT",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "details": {}
        })

    try:
        # 1. Scrape
        update_task_status(task_id, "SCRAPING", "RUNNING")
        logger.info("Step 1: Scraping...")
        scraped_tenders = scrape_all_sources()
        logger.info(f"Scraped {len(scraped_tenders)} tenders.")
        update_task_status(task_id, "SCRAPING", "COMPLETED", {"scraped_count": len(scraped_tenders)})
        
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
            for tender_id in master_ids:
                try:
                    tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
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
