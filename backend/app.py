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
    # Check DB Connection
    try:
        from database.mongo import client
        client.admin.command('ping')
        logger.info("Startup: Connected to MongoDB successfully.")
    except Exception as e:
        logger.error(f"Startup: Failed to connect to MongoDB: {e}")
        
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

@app.post("/api/tenders/{tender_id}/draft-proposal")
def draft_proposal(tender_id: str):
    """
    Generates a professional proposal draft using OpenAI.
    """
    if tenders_collection is None:
        return {"error": "Database not connected"}
        
    try:
        tender = tenders_collection.find_one({"_id": ObjectId(tender_id)})
        if not tender:
            return {"error": "Tender not found"}
            
        # Gather context
        bid_opt = tender.get("bid_optimization", {})
        comp_analysis = tender.get("competitor_analysis", {})
        
        context_data = {
            "title": tender.get("title"),
            "client": tender.get("client_name", "The Client"), # Assuming client_name might be there or generic
            "summary": tender.get("summary"),
            "our_offer_price": bid_opt.get("recommended_bid_price"),
            "our_strategy": bid_opt.get("strategy_rationale"),
            "key_risks_mitigated": comp_analysis.get("risks", [])[:2] # Mention how we handle top risks
        }
        
        import json
        prompt = f"""
        You are a Proposal Manager. Write a highly persuasive Executive Summary (Cover Letter) for this tender bid.
        
        BID CONTEXT:
        {json.dumps(context_data, default=str)}
        
        REQUIREMENTS:
        1. Keep it professional, confident, and winning.
        2. Highlight our competitive pricing (if optimized) and strategic value.
        3. Address key risks implicitly to show competence.
        4. Structure: Salutation, Value Proposition, Technical/Commercial Edge, Closing.
        
        OUTPUT:
        Return ONLY the plaintext of the letter. No markdown formatting like **bold** unless necessary for the letter structure itself.
        """
        
        from agents.llm_client import call_llm
        proposal_text = call_llm(prompt)
        
        # Save to DB
        tenders_collection.update_one(
            {"_id": ObjectId(tender_id)},
            {"$set": {"proposal_draft": proposal_text}}
        )
        
        return {"status": "success", "data": {"proposal_text": proposal_text}}
        
    except Exception as e:
        logger.error(f"Error in proposal drafting: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

# --- Chat Session API ---
from database.mongo import chat_sessions_collection

class CreateSessionRequest(BaseModel):
    title: str = "New Chat"

class ChatMessageResult(BaseModel):
    role: str
    content: str
    data: dict = None

@app.get("/api/chat/sessions")
def get_chat_sessions():
    """List all chat sessions for the sidebar"""
    if chat_sessions_collection is None:
        return []
    sessions = list(chat_sessions_collection.find({}, {"messages": 0}).sort("updated_at", -1))
    for s in sessions:
        s["_id"] = str(s["_id"])
    return sessions

@app.post("/api/chat/sessions")
def create_chat_session(req: CreateSessionRequest):
    """Create a new chat session"""
    if chat_sessions_collection is None:
        return {"error": "DB Error"}
    
    new_session = {
        "title": req.title,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "messages": [
            {"role": "system", "content": "Welcome to RFP Yukti Intelligence. I'm connected to your live tender database.", "timestamp": datetime.now()}
        ]
    }
    res = chat_sessions_collection.insert_one(new_session)
    return {"session_id": str(res.inserted_id), "title": req.title}

@app.get("/api/chat/sessions/{session_id}")
def get_session_history(session_id: str):
    """Get full message history for a session"""
    if chat_sessions_collection is None:
        return {"error": "DB Error"}
    
    session = chat_sessions_collection.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session["_id"] = str(session["_id"])
    return session

@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str):
    """Delete a chat session"""
    if chat_sessions_collection is None:
        return {"error": "DB Error"}
    
    result = chat_sessions_collection.delete_one({"_id": ObjectId(session_id)})
    if result.deleted_count == 0:
         raise HTTPException(status_code=404, detail="Session not found")
         
    return {"status": "success", "session_id": session_id}

class ExtendedChatPayload(BaseModel):
    query: str
    tender_id: str = None

@app.post("/api/chat/sessions/{session_id}/message")
def send_chat_message(session_id: str, payload: ExtendedChatPayload):
    """
    Send a message to a specific session.
    1. Fetch History
    2. Fetch RAG Context (Generic OR Tender Specific)
    3. Call LLM with Context + History
    4. Auto-Rename Session if new
    5. Save user & AI message
    """
    if chat_sessions_collection is None:
        return {"error": "DB Error"}

    from agents.llm_client import call_llm
    import json
    import re

    user_query = payload.query
    
    # 1. Fetch Session
    session = chat_sessions_collection.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    history = session.get("messages", [])
    
    # 2. RAG Context Fetch
    context_str = ""
    context_type = "GENERAL_OVERVIEW"
    
    if tenders_collection is not None:
        # A. Specific Tender Context
        if payload.tender_id and payload.tender_id != "all":
            try:
                tender = tenders_collection.find_one({"_id": ObjectId(payload.tender_id)})
                if tender:
                    context_data = {
                        "title": tender.get("title"),
                        "client": tender.get("client_name"),
                        "scope": tender.get("scope_of_supply"),
                        "status": tender.get("approval_status"),
                        "pricing": tender.get("total_tender_price"),
                        "analysis": tender.get("competitor_analysis"),
                        "strategy": tender.get("bid_optimization")
                    }
                    context_str = json.dumps(context_data, default=str)
                    context_type = f"SPECIFIC_TENDER_FOCUS: {tender.get('title')}"
            except Exception as e:
                logger.error(f"Error fetching specific tender context: {e}")
        
        # B. General Context (Fallback)
        if not context_str:
            recent = list(tenders_collection.find({}, {
                "title": 1, "client_name": 1, "total_tender_price": 1, 
                "approval_status": 1, "competitor_analysis": 1
            }).sort("scraped_at", -1).limit(10))
            context_str = json.dumps(recent, default=str)
    
    # 3. Construct Prompt with History
    chat_history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
    
    prompt = f"""
    You are 'RFP Yukti', an advanced procurement AI assistant.
    
    SYSTEM CONTEXT ({context_type}):
    {context_str}
    
    CHAT HISTORY:
    {chat_history_text}
    
    USER'S NEW MESSAGE:
    "{user_query}"
    
    AVAILABLE TOOLS/ACTIONS:
    You can control the system using these specific commands. 
    To use a tool, your response must start with "TOOL_CALL: <ToolName> <Args>".
    
    1. APPROVE_TENDER
       - Syntax: TOOL_CALL: APPROVE_TENDER <Tender_ID or Exact_Title>
       - Use: When user explicitly asks to approve a tender.
       
    2. REJECT_TENDER
       - Syntax: TOOL_CALL: REJECT_TENDER <Tender_ID or Exact_Title> | <Reason>
       - Use: When user asks to reject. Reason is optional but recommended.
       
    3. RUN_ANALYSIS
       - Syntax: TOOL_CALL: RUN_ANALYSIS <Tender_ID or Exact_Title>
       - Use: When user wants to run/re-run competitor analysis or bid optimization.
       
    INSTRUCTIONS:
    1. If the user asks to perform an action listed above, USE THE TOOL. Do successfully extract the specific Tender ID or Title from context.
    2. If NO action is needed, answer the user's question using the System Context or Chat History.
    3. If the user wants to ADD a tender, extract JSON details as before ("ADD_TENDER_JSON:").
    4. Be concise and professional.
    
    SPECIAL HANDLING:
    - If user provides tender details to add, output valid JSON starting with "ADD_TENDER_JSON:".
    """
    
    response_text = call_llm(prompt)
    
    # 4. Process Response (Check for ADD intent via special prefix)
    ai_msg_content = response_text
    extracted_data = None
    action_result = None
    
    # --- Tool Execution Logic ---
    if "TOOL_CALL:" in response_text:
        try:
            tool_command = response_text.split("TOOL_CALL:")[1].strip()
            tool_parts = tool_command.split(" ", 1)
            tool_name = tool_parts[0]
            tool_args = tool_parts[1] if len(tool_parts) > 1 else ""
            
            # Helper to find tender by ID or Title
            def find_tender(identifier):
                if ObjectId.is_valid(identifier):
                    return tenders_collection.find_one({"_id": ObjectId(identifier)})
                # Fuzzy/Exact Title Match
                return tenders_collection.find_one({"title": {"$regex": identifier, "$options": "i"}})

            if tool_name == "APPROVE_TENDER":
                tender = find_tender(tool_args.strip())
                if tender:
                    tenders_collection.update_one({"_id": tender["_id"]}, {"$set": {"approval_status": "APPROVED", "updated_at": datetime.now()}})
                    action_result = {"status": "success", "action": "approve", "tender": tender["title"]}
                    ai_msg_content = f"✅ Approved tender: **{tender['title']}**."
                else:
                    ai_msg_content = f"❌ Could not find tender: '{tool_args}' to approve."

            elif tool_name == "REJECT_TENDER":
                args_split = tool_args.split("|")
                identifier = args_split[0].strip()
                reason = args_split[1].strip() if len(args_split) > 1 else "Chat Rejection"
                tender = find_tender(identifier)
                if tender:
                    tenders_collection.update_one({"_id": tender["_id"]}, {"$set": {"approval_status": "REJECTED", "rejection_reason": reason, "updated_at": datetime.now()}})
                    action_result = {"status": "success", "action": "reject", "tender": tender["title"]}
                    ai_msg_content = f"🚫 Rejected tender: **{tender['title']}** (Reason: {reason})."
                else:
                    ai_msg_content = f"❌ Could not find tender: '{identifier}' to reject."

            elif tool_name == "RUN_ANALYSIS":
                tender = find_tender(tool_args.strip())
                if tender:
                    # Trigger specific analysis pipeline
                    from celery_tasks import reprocess_single_tender
                    task = reprocess_single_tender.delay(str(tender["_id"]))
                    
                    action_result = {"status": "success", "action": "analysis", "tender": tender["title"], "task_id": str(task.id)}
                    ai_msg_content = f"⚙️ Started targeted analysis for: **{tender['title']}**.\n\nPipeline ID: `{task.id}`"
                else:
                    ai_msg_content = f"❌ Could not find tender: '{tool_args}' to analyze."
                    
        except Exception as e:
            logger.error(f"Tool Execution Error: {e}")
            ai_msg_content = "⚠️ I accept the command, but something went wrong executing it on the server."

    elif "ADD_TENDER_JSON:" in response_text:
        try:
            json_part = response_text.split("ADD_TENDER_JSON:")[1].strip()
            if "```" in json_part: # Cleanup markdown
                json_part = json_part.split("```")[1]
                if json_part.startswith("json"): json_part = json_part[4:]
            
            tender_data = json.loads(json_part)
            extracted_data = tender_data
            
            # Insert Tender
            if tenders_collection is not None:
                tender_data["scraped_at"] = datetime.now()
                tender_data["source"] = "CHAT"
                tender_data["status"] = "PENDING"
                if not tenders_collection.find_one({"title": tender_data.get("title")}):
                    tenders_collection.insert_one(tender_data)
                    run_full_tender_pipeline.delay()
                    ai_msg_content = f"✅ I've processed that. New Tender '{tender_data.get('title')}' has been added and the pipeline is running."
                else:
                    ai_msg_content = f"⚠️ That tender '{tender_data.get('title')}' already exists in the database."
        except Exception as e:
            logger.error(f"Chat extraction error: {e}")
            ai_msg_content = "I tried to add that tender but couldn't parse the details. Could you check the format?"

    # 5. Update DB
    new_messages = [
        {"role": "user", "content": user_query, "timestamp": datetime.now()},
        {"role": "ai", "content": ai_msg_content, "data": extracted_data or action_result, "timestamp": datetime.now()}
    ]
    
    update_fields = {
        "updated_at": datetime.now()
    }
    
    # --- Auto-Rename Logic ---
    # Rename if title is default "New Chat" and we have a user message
    if session.get("title") == "New Chat" or session.get("title").startswith("Chat "):
        try:
            # Generate a short 3-5 word title based on the user's query
            title_prompt = f"Summarize this query into a very short 3-5 word title (No quotes): {user_query}"
            new_title = call_llm(title_prompt).strip()
            # Remove any quotes if LLM added them
            new_title = new_title.replace('"', '').replace("'", "")
            update_fields["title"] = new_title
        except Exception as e:
            logger.warning(f"Failed to auto-rename chat: {e}")

    chat_sessions_collection.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$push": {"messages": {"$each": new_messages}},
            "$set": update_fields
        }
    )
    
    return {
        "answer": ai_msg_content, 
        "data": extracted_data,
        "new_title": update_fields.get("title") # Return new title if renamed
    }

# --- Chat API (Legacy/Global) ---

class ChatQuery(BaseModel):
    query: str

from agents.llm_client import call_llm
import json
import re

@app.post("/api/chat/global")
def global_chat_interface(request: ChatQuery):
    """
    Bloomberg-style terminal chat interface.
    Handles:
    1. SEARCH/Please: Questions about existing tenders (RAG).
    2. ADD/Process: Manual entry of new tenders.
    """
    query = request.query
    
    # 1. Intent Classification
    intent_prompt = f"""
    Analyze the user's intent in this query: "{query}"
    
    Classify into one of two categories:
    - ADD: User is providing details of a new tender to add/process (e.g. "Add a tender...", "New RFP from...").
    - SEARCH: User is asking questions about existing data, status, generic queries, or market intel.
    
    Reply ONLY with the word ADD or SEARCH.
    """
    intent = call_llm(intent_prompt)
    if not intent:
        intent = "SEARCH"
    else:
        intent = intent.strip().upper()
        
    logger.info(f"Chat Intent: {intent}")
        
    if "ADD" in intent:
        # Extract Tender Details
        extract_prompt = f"""
        Extract the tender details from this text into a VALID JSON object.
        Text: "{query}"
        
        Fields required: 
        - title (generate a concise title if not explicit)
        - client_name (infer if possible, else "Unknown")
        - summary (the full context provided)
        - total_tender_price (numeric, infer from text like "50Cr", "10 Lakhs", "500000". If missing, use 0)
        - deadline (YYYY-MM-DD format. Infer from "next month", "in 2 weeks", etc. If impossible, use Future Date)
        
        Output ONLY the JSON object. No markdown.
        """
        json_str = call_llm(extract_prompt)
        
        try:
            # Clean markdown if present
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
                
            tender_data = json.loads(json_str.strip())
            
            # Add defaults
            tender_data["scraped_at"] = datetime.now()
            tender_data["source"] = "MANUAL_CHAT_ENTRY"
            tender_data["status"] = "PENDING"
            
            # Insert to DB
            if tenders_collection is not None:
                # Check dupe
                if not tenders_collection.find_one({"title": tender_data.get("title")}):
                    tenders_collection.insert_one(tender_data)
                    
                    # Trigger Pipeline
                    run_full_tender_pipeline.delay()
                    
                    return {
                        "answer": f"✅ New Tender '{tender_data.get('title')}' added to the database.\n\nRunning background pipeline (Analysis -> Strategy -> Pricing)...\n\nCheck the dashboard shortly.",
                        "intent": "ADD",
                        "data": tender_data
                    }
                else:
                    return {
                        "answer": f"⚠️ A tender with the title '{tender_data.get('title')}' already exists.",
                        "intent": "ADD_DUPLICATE"
                    }
            else:
                return {"answer": "Database error.", "intent": "ERROR"}
                
        except Exception as e:
            logger.error(f"Extraction Failed: {e}")
            return {"answer": "I understood you want to add a tender, but I couldn't extract the details. Please try providing: Title, Client, Value, and Deadline.", "intent": "ADD_FAILED"}
            
    else:
        # RAG / Search Algo
        # 1. Fetch relevant context (Naively fetch last 20 for now - Hackathon MVP)
        if tenders_collection is not None:
            recent_tenders = list(tenders_collection.find({}, {
                "title": 1, "client_name": 1, "total_tender_price": 1, 
                "approval_status": 1, "competitor_analysis.win_probability": 1, 
                "bid_optimization.recommended_bid_price": 1
            }).sort("scraped_at", -1).limit(20))
            
            context_str = json.dumps(recent_tenders, default=str)
        else:
            context_str = "No database connection."
            
        # 2. Answer Query
        rag_prompt = f"""
        You are 'RFP Yukti Terminal', an advanced procurement AI. 
        
        Context (Recent Tenders):
        {context_str}
        
        User Query: "{query}"
        
        Answer the user's question based on the context. 
        - Be professional, concise, and data-driven.
        - If they ask for high-value tenders, filter by price.
        - If they ask for win probability, use the competitor analysis data.
        - If the info isn't in the context, just say you don't have that data currently.
        """
        
        answer = call_llm(rag_prompt)
        return {"answer": answer, "intent": "SEARCH"}

# --- Analytics Endpoints ---
@app.get("/api/analytics/dashboard")
def get_analytics_dashboard():
    try:
        if tenders_collection is None:
            return {"error": "Database not connected"}
            
        tenders = list(tenders_collection.find({}))
        
        # 1. Volume Trends (Group by Date)
        trends = {}
        for t in tenders:
            if t.get("scraped_at"):
                # Handle both datetime and string if existing data is mixed
                ts = t["scraped_at"]
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except:
                        continue
                date_str = ts.strftime("%Y-%m-%d")
                trends[date_str] = trends.get(date_str, 0) + 1
        
        volume_trends = [{"date": k, "count": v} for k, v in sorted(trends.items())]
        
        # 2. Category Frequency
        categories = {}
        for t in tenders:
            cat = t.get("category", "Uncategorized")
            categories[cat] = categories.get(cat, 0) + 1
            
        category_distribution = [{"name": k, "value": v} for k, v in categories.items()]
        
        # 3. Status Distribution (Wins/Losses Proxy)
        status_counts = {"Approved": 0, "Rejected": 0, "Pending": 0}
        for t in tenders:
            status = t.get("approval_status", "PENDING")
            if status == "APPROVED": status_counts["Approved"] += 1
            elif status == "REJECTED": status_counts["Rejected"] += 1
            else: status_counts["Pending"] += 1
            
        # 4. Win Likelihood Distribution (Histogram)
        # Groups: 0-20, 20-40, 40-60, 60-80, 80-100
        win_dist = {"0-20%": 0, "20-40%": 0, "40-60%": 0, "60-80%": 0, "80-100%": 0}
        for t in tenders:
            prob = 0
            if t.get("competitor_analysis"):
                prob = t["competitor_analysis"].get("win_probability", 0)
            
            if prob <= 20: win_dist["0-20%"] += 1
            elif prob <= 40: win_dist["20-40%"] += 1
            elif prob <= 60: win_dist["40-60%"] += 1
            elif prob <= 80: win_dist["60-80%"] += 1
            else: win_dist["80-100%"] += 1
            
        win_likelihood = [{"range": k, "count": v} for k, v in win_dist.items()]

        # 5. AVG Time to Respond (Mock calculation for now as timestamps might be partial)
        # In real scenario: avg(master_processed_at - scraped_at)
        avg_response_time = 4.2 # hours (Mock)

        return {
            "volume_trends": volume_trends,
            "category_distribution": category_distribution,
            "status_distribution": [{"name": k, "value": v} for k,v in status_counts.items()],
            "win_likelihood": win_likelihood,
            "avg_response_time": avg_response_time,
            "total_tenders": len(tenders)
        }
    except Exception as e:
        logger.error(f"Analytics Error: {e}")
        return {"error": str(e)}

# --- Calendar Endpoints ---
from datetime import timedelta
from urllib.parse import quote

@app.get("/api/calendar/events")
def get_calendar_events():
    """
    Returns auto-generated calendar events for all tenders.
    Events: Submission Deadline, Tech Review, Pricing Approval.
    Includes 'google_link' for one-click add.
    """
    try:
        if tenders_collection is None:
            return []
            
        tenders = list(tenders_collection.find({}))
        events = []
        
        for t in tenders:
            # Determine Base Deadline
            deadline = None
            if t.get("submission_date"):
                if isinstance(t["submission_date"], datetime):
                    deadline = t["submission_date"]
                elif isinstance(t["submission_date"], str):
                    try:
                        deadline = datetime.fromisoformat(t["submission_date"].replace("Z", ""))
                    except: pass
            
            # Fallback Logic: Scraped + 14 Days
            if not deadline:
                scraped = t.get("scraped_at")
                if isinstance(scraped, str):
                    try: scraped = datetime.fromisoformat(scraped.replace("Z", ""))
                    except: scraped = datetime.now()
                elif not isinstance(scraped, datetime):
                    scraped = datetime.now()
                deadline = scraped + timedelta(days=14)
            
            # Calculate Milestones
            tech_deadline = deadline - timedelta(days=5)
            pricing_deadline = deadline - timedelta(days=2)
            
            # Helper to generate Google Calendar Link
            def get_gcal_link(title, start_dt, details):
                # Format: YYYYMMDDTHHMMSSZ
                fmt = "%Y%m%dT%H%M%S"
                start_str = start_dt.strftime(fmt)
                end_str = (start_dt + timedelta(hours=1)).strftime(fmt)
                base = "https://calendar.google.com/calendar/render?action=TEMPLATE"
                return f"{base}&text={quote(title)}&dates={start_str}/{end_str}&details={quote(details)}"

            # 1. Submission Event
            events.append({
                "id": f"{t['_id']}_sub",
                "tender_id": str(t["_id"]),
                "title": f"📅 Deadline: {t.get('title', 'Tender')[:30]}...",
                "start": deadline.isoformat(),
                "type": "submission",
                "google_link": get_gcal_link(f"DEADLINE: {t.get('title')}", deadline, f"Final submission for tender: {t.get('title')}")
            })
            
            # 2. Technical Review
            events.append({
                "id": f"{t['_id']}_tech",
                "tender_id": str(t["_id"]),
                "title": f"🔧 Tech Review: {t.get('title', 'Tender')[:30]}...",
                "start": tech_deadline.isoformat(),
                "type": "technical",
                "google_link": get_gcal_link(f"TECH REVIEW: {t.get('title')}", tech_deadline, "Internal technical spec review.")
            })
            
            # 3. Pricing Approval
            events.append({
                "id": f"{t['_id']}_price",
                "tender_id": str(t["_id"]),
                "title": f"💰 Pricing Check: {t.get('title', 'Tender')[:30]}...",
                "start": pricing_deadline.isoformat(),
                "type": "pricing",
                "google_link": get_gcal_link(f"PRICING APPROVAL: {t.get('title')}", pricing_deadline, "Finalize margin and approve bid price.")
            })
            
        return events
        
    except Exception as e:
        logger.error(f"Calendar Error: {e}")
        return []
