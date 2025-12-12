from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bson import ObjectId
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import logging
from datetime import datetime
import sys
import os

# Ensure backend directory is in path if running directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.mongo import tenders_collection, celery_tasks_collection
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

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For hackathon, allow all. In prod, specify ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    
    # Return all tenders including _id (serialized)
    tenders_cursor = tenders_collection.find().sort("scraped_at", -1)
    tenders = [serialize_mongo_doc(t) for t in tenders_cursor]
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

class RejectionPayload(BaseModel):
    reason: str

def serialize_mongo_doc(doc):
    doc["_id"] = str(doc["_id"])
    return doc

@app.get("/api/tenders/pending-approval")
def get_pending_approval_tenders():
    """
    Get all tenders that have completed previous stages but are waiting for approval.
    """
    if tenders_collection is None:
        return {"error": "Database not connected", "tenders": []}
    
    query = {
        "sales_processed": True,
        "technical_processed": True,
        "pricing_processed": True,
        "approval_status": {"$nin": ["APPROVED", "REJECTED"]}
    }
    
    # We need the _id to approve/reject, so we must include it
    tenders_cursor = tenders_collection.find(query).sort("scraped_at", -1)
    tenders = [serialize_mongo_doc(t) for t in tenders_cursor]
    return tenders

@app.post("/api/tenders/{tender_id}/approve")
def approve_tender(tender_id: str):
    """
    Approve a tender for Master Agent processing.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        result = tenders_collection.update_one(
            {"_id": ObjectId(tender_id)},
            {"$set": {"approval_status": "APPROVED", "approved_at": datetime.now()}}
        )
        
        if result.matched_count == 0:
             return {"error": "Tender not found"}
             
        return {"status": "success", "message": f"Tender {tender_id} approved"}
        
    except Exception as e:
        logger.error(f"Error approving tender: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/tenders/{tender_id}/reject")
def reject_tender(tender_id: str, payload: RejectionPayload):
    """
    Reject a tender and provide a reason.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        result = tenders_collection.update_one(
            {"_id": ObjectId(tender_id)},
            {"$set": {
                "approval_status": "REJECTED", 
                "rejected_at": datetime.now(),
                "rejection_reason": payload.reason
            }}
        )
        
        if result.matched_count == 0:
             return {"error": "Tender not found"}
             
        return {"status": "success", "message": f"Tender {tender_id} rejected"}
        
    except Exception as e:
        logger.error(f"Error rejecting tender: {e}")
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

@app.get("/api/tasks")
def list_tasks():
    """
    List all Celery tasks and their status.
    """
    if celery_tasks_collection is None:
        return {"error": "Database not connected", "tasks": []}
    
    tasks = list(celery_tasks_collection.find({}, {"_id": 0}).sort("created_at", -1))
    return tasks

@app.get("/api/tasks/{task_id}")
def get_task_details(task_id: str):
    """
    Get details of a specific Celery task.
    """
    if celery_tasks_collection is None:
        return {"error": "Database not connected"}
    
    task = celery_tasks_collection.find_one({"task_id": task_id}, {"_id": 0})
    if not task:
        return {"error": "Task not found"}
    
    return task

class ChatPayload(BaseModel):
    query: str

@app.post("/api/tenders/{tender_id}/chat")
def chat_with_tender(tender_id: str, payload: ChatPayload):
    """
    Chat with a specific tender's data using OpenAI.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
        if not tender:
            return {"error": "Tender not found"}
            
        # Serialize tender data for context
        # We limit what we send to avoid huge context windows if possible, 
        # but for now sending the main fields is good.
        context_data = {
            "title": tender.get("title"),
            "summary": tender.get("summary"),
            "scope_of_supply": tender.get("scope_of_supply"),
            "technical_recommendations": tender.get("technical_recommendations"),
            "pricing_table": tender.get("pricing_table"),
            "total_tender_price": tender.get("total_tender_price")
        }
        
        import json
        prompt = f"""
        You are an intelligent procurement assistant.
        The user is asking a question about a specific tender.
        
        TENDER DATA:
        {json.dumps(context_data, default=str)}
        
        USER QUESTION:
        {payload.query}
        
        Answer concisely and professionally based ONLY on the tender data provided.
        If the answer is not in the data, say "I cannot find that information in the tender documents."
        """
        
        # We need to import call_llm here or at top level. 
        # Since it's used in agents, let's import it.
        from agents.llm_client import call_llm
        
        response = call_llm(prompt)
        
        if not response:
            return {"answer": "I'm sorry, I couldn't process that request right now."}
            
        return {"answer": response}
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/tenders/{tender_id}/analyze-competitors")
def analyze_competitors(tender_id: str):
    """
    Generates a competitor analysis using OpenAI.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
        if not tender:
            return {"error": "Tender not found"}
            
        context_data = {
            "title": tender.get("title"),
            "summary": tender.get("summary"),
            "scope_of_supply": tender.get("scope_of_supply"),
            "total_tender_price": tender.get("total_tender_price")
        }
        
        import json
        prompt = f"""
        You are a Strategic Bid Manager for a large engineering firm.
        Analyze this tender and provide:
        1. List of 3-5 likely competitors (Global/Indian) for this specific work.
        2. A "Win Probability" score (0-100%).
        3. Key risks.
        
        TENDER DATA:
        {json.dumps(context_data, default=str)}
        
        OUTPUT FORMAT:
        Return ONLY valid JSON:
        {{
            "competitors": ["Comp A", "Comp B"],
            "win_probability": 75,
            "risks": ["Risk 1", "Risk 2"],
            "rationale": "Brief explanation..."
        }}
        """
        
        from agents.llm_client import call_llm
        response_text = call_llm(prompt)
        
        # Parse JSON from LLM
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        analysis = json.loads(response_text)
        
        # Save to DB
        tenders_collection.update_one(
            {"_id": ObjectId(tender_id)},
            {"$set": {"competitor_analysis": analysis}}
        )
        
        return {"status": "success", "data": analysis}
        
    except Exception as e:
        logger.error(f"Error in competitor analysis: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/tenders/{tender_id}/optimize-bid")
def optimize_bid(tender_id: str):
    """
    Generates a winning bid price and strategy using OpenAI.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
        if not tender:
            return {"error": "Tender not found"}
            
        # We need the cost estimate and competitor analysis to do this well
        if not tender.get("total_tender_price"):
             return {"error": "Cost estimation not yet completed by Pricing Agent."}
             
        competitor_analysis = tender.get("competitor_analysis", {})
        
        context_data = {
            "title": tender.get("title"),
            "estimated_cost": tender.get("total_tender_price"),
            "competitors": competitor_analysis.get("competitors", []),
            "win_probability": competitor_analysis.get("win_probability", 50)
        }
        
        import json
        prompt = f"""
        You are a Senior Pricing Strategist.
        Based on the estimated internal cost and the competitive landscape, recommend a Winning Bid Price.
        
        DATA:
        {json.dumps(context_data, default=str)}
        
        TASK:
        1. Determine an optimal profit margin (e.g., 10-25%) based on the win probability and competitors. 
           (Lower margin if competition is high/win prob is low).
        2. Calculate the Final Bid Price.
        3. Explain the strategy.
        
        OUTPUT FORMAT (JSON ONLY):
        {{
            "recommended_margin_percentage": 15,
            "recommended_bid_price": 1500000,
            "strategy_rationale": "Aggressive pricing needed due to presence of Competitor X...",
            "likelihood_to_win_with_this_price": "High"
        }}
        """
        
        from agents.llm_client import call_llm
        response_text = call_llm(prompt)
        
        # Parse JSON
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        optimization = json.loads(response_text)
        
        # Save to DB
        tenders_collection.update_one(
            {"_id": ObjectId(tender_id)},
            {"$set": {"bid_optimization": optimization}}
        )
        
        return {"status": "success", "data": optimization}
        
    except Exception as e:
        logger.error(f"Error in bid optimization: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
