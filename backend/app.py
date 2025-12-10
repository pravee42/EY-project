from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import logging
from datetime import datetime
import sys
import os

# Ensure backend directory is in path if running directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.mongo import tenders_collection
from scraper.scraper import scrape_all_sources

from agents.sales_agent import sales_summary_job, process_tenders_via_sales_agent
from agents.technical_agent import technical_agent_job, process_tenders_via_technical_agent
from agents.pricing_agent import pricing_agent_job, process_tenders_via_pricing_agent
from agents.master_agent import master_agent_job, process_tenders_via_master_agent
from celery_tasks import run_full_tender_pipeline
from fastapi.responses import FileResponse
import os

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- CRON JOB ---
def scheduled_scrape_job():
    """
    Background job to scrape tenders and save to MongoDB.
    Runs every 10 minutes.
    """
    logger.info(f"Starting scheduled scrape job at {datetime.now()}")
    try:
        tenders = scrape_all_sources()
        
        if not tenders:
            logger.info("No tenders found in this run.")
            return

        if tenders_collection is None:
            logger.error("Database connection not available. Skipping save.")
            return
        new_count = 0
        for tender_data in tenders:
            try:
                # Check duplicate by title
                if not tenders_collection.find_one({"title": tender_data["title"]}):
                    tenders_collection.insert_one(tender_data)
                    new_count += 1
            except Exception as insert_error:
                logger.error(f"Error inserting tender: {insert_error}")
        
        logger.info(f"Job finished. Scraped {len(tenders)} items. Inserted {new_count} new tenders.")
        
    except Exception as e:
        logger.error(f"CRITICAL: Error in scheduled scrape job: {e}")

# --- LIFESPAN MANAGER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Scheduler
    scheduler = BackgroundScheduler()
    
    # Scraper Job (Every 10 mins)
    scheduler.add_job(
        scheduled_scrape_job, 
        'interval', 
        minutes=50, 
        id='scheduled_scrape_job',
        replace_existing=True
    )
    
    # Sales Agent Job (Every 10 mins)
    scheduler.add_job(
        sales_summary_job,
        'interval',
        minutes=60,
        id='sales_summary_job',
        replace_existing=True
    )
    
    # Technical Agent Job (Every 10 mins)
    scheduler.add_job(
        technical_agent_job,
        'interval',
        minutes=60,
        id='technical_agent_job',
        replace_existing=True
    )
    
    # Pricing Agent Job (Every 10 mins)
    scheduler.add_job(
        pricing_agent_job,
        'interval',
        minutes=60,
        id='pricing_agent_job',
        replace_existing=True
    )
    
    # Master Agent Job (Every 10 mins)
    scheduler.add_job(
        master_agent_job,
        'interval',
        minutes=10,
        id='master_agent_job',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Background Scheduler started (Scraper + Sales + Technical + Pricing + Master).")
    
    yield
    
    # Shutdown Scheduler
    scheduler.shutdown()
    logger.info("Background Scheduler shut down.")

# --- FASTAPI APP ---
app = FastAPI(lifespan=lifespan, title="RFP-Yukti Backend Scraper")

@app.get("/")
def read_root():
    return {"status": "running", "service": "RFP-Yukti Scraper"}

@app.get("/tenders")
def get_tenders():
    """
    Retrieve all stored tenders.
    """
    if tenders_collection is None:
        return {"error": "Database not connected", "tenders": []}
    
    # Return all tenders excluding the internal MongoDB _id
    tenders = list(tenders_collection.find({}, {"_id": 0}).sort("scraped_at", -1))
    return tenders

@app.get("/api/tenders/process/sales")
def trigger_sales_process():
    """
    Manually trigger the Sales Agent processing job.
    """
    try:
        processed_ids = process_tenders_via_sales_agent(limit=20)
        return {"status": "ok", "processed_count": len(processed_ids), "processed_ids": processed_ids}
    except Exception as e:
        logger.error(f"Error in manual sales process trigger: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/tenders/process/technical")
def trigger_technical_process():
    """
    Manually trigger the Technical Agent processing job.
    """
    try:
        processed_ids = process_tenders_via_technical_agent(limit=20)
        return {"status": "ok", "processed_count": len(processed_ids), "processed_ids": processed_ids}
    except Exception as e:
        logger.error(f"Error in manual technical process trigger: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/tenders/process/pricing")
def trigger_pricing_process():
    """
    Manually trigger the Pricing Agent processing job.
    """
    try:
        processed_ids = process_tenders_via_pricing_agent(limit=20)
        return {"status": "ok", "processed_count": len(processed_ids), "processed_ids": processed_ids}
    except Exception as e:
        logger.error(f"Error in manual pricing process trigger: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/tenders/process/master")
def trigger_master_process():
    """
    Manually trigger the Master Agent processing job.
    """
    try:
        processed_ids = process_tenders_via_master_agent(limit=20)
        return {"status": "ok", "processed_count": len(processed_ids), "processed_ids": processed_ids}
    except Exception as e:
        logger.error(f"Error in manual master process trigger: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/tenders/{tender_id}/report/pdf")
def download_report_pdf(tender_id: str):
    """
    Download the generated PDF report for a tender.
    """
    try:
        from bson import ObjectId
        tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
        
        if not tender:
            return {"error": "Tender not found"}
            
        pdf_path = tender.get("final_report_pdf_path")
        
        if not pdf_path or not os.path.exists(pdf_path):
            return {"error": "PDF report not generated yet"}
            
        return FileResponse(pdf_path, media_type="application/pdf", filename=f"Tender_Report_{tender_id}.pdf")
        
    except Exception as e:
        logger.error(f"Error downloading PDF: {e}")
        return {"error": str(e)}

@app.post("/api/celery/start-process")
def start_celery_process():
    """
    Trigger the full tender processing pipeline via Celery.
    """
    try:
        task = run_full_tender_pipeline.delay()
        return {"status": "Task started", "task_id": str(task.id)}
    except Exception as e:
        logger.error(f"Error starting celery task: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
