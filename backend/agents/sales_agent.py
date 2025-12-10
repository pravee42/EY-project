import logging
import uuid
from datetime import datetime
from typing import List, Tuple

from database.mongo import tenders_collection
from agents.llm_client import call_llm

logger = logging.getLogger(__name__)

def find_unprocessed_tenders(limit=20) -> List[dict]:
    """
    Fetch tenders where sales_processed is not True.
    """
    if tenders_collection is None:
        logger.error("Database not connected.")
        return []
    
    # Find documents where sales_processed is False or doesn't exist
    query = {"sales_processed": {"$ne": True}}
    tenders = list(tenders_collection.find(query).limit(limit))
    return tenders

import io
import requests
from pypdf import PdfReader

def download_pdf_text(url: str) -> str:
    """
    Downloads PDF from URL and extracts text.
    Returns empty string on failure.
    """
    if not url:
        return ""
    
    try:
        logger.info(f"Downloading PDF from {url}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        with io.BytesIO(response.content) as f:
            reader = PdfReader(f)
            text = ""
            # Limit pages to avoid huge context, e.g., first 10 pages
            for i, page in enumerate(reader.pages):
                if i >= 15: 
                    break
                text += page.extract_text() + "\n"
                
        return text
    except Exception as e:
        logger.error(f"Failed to extract PDF text from {url}: {e}")
        return ""

def build_sales_prompt_for_technical(tender_doc: dict, pdf_text: str = "") -> Tuple[str, str]:
    """
    Returns (sales_summary, technical_prompt)
    """
    title = tender_doc.get("title", "")
    summary = tender_doc.get("summary", "")
    
    # Truncate PDF text if too long (approx 15k chars to be safe with tokens)
    if len(pdf_text) > 20000:
        pdf_text = pdf_text
    
    technical_prompt = f"""
    You are a Technical Sales Engineer.
    Analyze this tender based on the provided metadata and PDF content.
    
    Title: {title}
    Summary: {summary}
    
    PDF Content (Extracted):
    {pdf_text}
    
    Task 1: Provide a 1-2 sentence high-level sales summary of what is being requested.
    Task 2: Extract the "Scope of Supply".
    Task 3: Extract "Tender Application Format" details.
    Task 4: Extract "Mechanical Specifications".
    Task 5: Extract product line items (Quotation details) into a JSON-like list.
       For cables/wires, specifically look for:
       - Description
       - Quantity
       - Dimensions
       - Core Screen
       - Core Sheathing
       - Outer Sheath
       - Insulator Resistance
       - Voltage / Size / Armour / Temp Rating
    
    Output Format:
    SALES_SUMMARY: <text>
    SCOPE: <text>
    APPLICATION_FORMAT: <text>
    MECHANICAL_SPECS: <text>
    ITEMS: <json_list>
    """
    
    return "", technical_prompt

def build_sales_prompt_for_pricing(tender_doc: dict, pdf_text: str = "") -> Tuple[str, str]:
    """
    Returns (pricing_summary, pricing_prompt)
    """
    title = tender_doc.get("title", "")
    summary = tender_doc.get("summary", "")
    
    if len(pdf_text) > 20000:
        pdf_text = pdf_text[:20000] + "...[TRUNCATED]"
    
    pricing_prompt = f"""
    You are a Pricing Analyst.
    Analyze this tender based on the provided metadata and PDF content.
    
    Title: {title}
    Summary: {summary}
    
    PDF Content (Extracted):
    {pdf_text}
    
    Task: Extract testing and acceptance requirements.
    Identify:
    - Routine tests
    - Type tests
    - FAT (Factory Acceptance Tests)
    - Site acceptance tests
    
    Output Format:
    TESTING_REQUIREMENTS:
    <list details here>
    """
    
    return "", pricing_prompt

def process_tenders_via_sales_agent(limit=20) -> List[str]:
    """
    Main logic to process tenders.
    Returns list of processed tender IDs.
    """
    tenders = find_unprocessed_tenders(limit)
    if not tenders:
        logger.info("No unprocessed tenders found.")
        return []
    
    processed_ids = []
    
    for tender in tenders:
        try:
            tender_id = tender["_id"]
            logger.info(f"Processing tender {tender_id}...")
            
            # 0. Extract PDF Text if available
            pdf_link = tender.get("pdf_link")
            pdf_text = ""
            if pdf_link:
                pdf_text = download_pdf_text(pdf_link)
            
            # 1. Build Prompts
            _, tech_prompt_str = build_sales_prompt_for_technical(tender, pdf_text)
            _, price_prompt_str = build_sales_prompt_for_pricing(tender, pdf_text)
            
            # 2. Call LLM (Technical)
            tech_response = call_llm(tech_prompt_str)
            
            # Parse Sales Summary from Tech Response (heuristic)
            sales_summary = "Summary not generated"
            if tech_response and "SALES_SUMMARY:" in tech_response:
                parts = tech_response.split("SALES_SUMMARY:")
                if len(parts) > 1:
                    # Take content until next section
                    after_summary = parts[1]
                    # Assuming SCOPE is next
                    if "SCOPE:" in after_summary:
                        sales_summary = after_summary.split("SCOPE:")[0].strip()
                    else:
                        sales_summary = after_summary.strip()
            
            # 3. Call LLM (Pricing)
            price_response = call_llm(price_prompt_str)
            
            # 4. Store Results
            pipeline_run_id = str(uuid.uuid4())
            
            update_data = {
                "sales_processed": True,
                "sales_processed_at": datetime.now(),
                "sales_summary": sales_summary,
                "technical_prompt": tech_prompt_str,
                "pricing_prompt": price_prompt_str,
                "technical_summary_text": tech_response,
                "pricing_summary_text": price_response,
                "pipeline_run_id": pipeline_run_id
            }
            
            tenders_collection.update_one(
                {"_id": tender_id},
                {"$set": update_data}
            )
            
            processed_ids.append(str(tender_id))
            logger.info(f"Successfully processed tender {tender_id}")
            
        except Exception as e:
            logger.error(f"Error processing tender {tender.get('_id')}: {e}")
            
    return processed_ids

def sales_summary_job():
    """
    Job to be scheduled.
    """
    logger.info("Starting Sales Summary Job...")
    ids = process_tenders_via_sales_agent()
    logger.info(f"Sales Summary Job finished. Processed {len(ids)} tenders.")
