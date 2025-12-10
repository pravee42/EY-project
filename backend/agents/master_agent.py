import logging
import os
import json
from datetime import datetime
from typing import List, Dict, Any

from fastapi.responses import FileResponse
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

from database.mongo import tenders_collection

logger = logging.getLogger(__name__)

# Configuration
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")

# Ensure reports directory exists
os.makedirs(REPORTS_DIR, exist_ok=True)

def find_ready_for_master(limit=20) -> List[dict]:
    """
    Fetch tenders where all previous agents completed but master not processed.
    """
    if tenders_collection is None:
        logger.error("Database not connected.")
        return []
    
    query = {
        "sales_processed": True,
        "technical_processed": True,
        "pricing_processed": True,
        "master_processed": {"$ne": True}
    }
    return list(tenders_collection.find(query).limit(limit))

def sanitize_pricing_table(table: List[dict]) -> List[dict]:
    """Ensure all pricing fields are valid numbers/strings."""
    if not table: return []
    sanitized = []
    for row in table:
        sanitized.append({
            "line_item_index": row.get("line_item_index", 0),
            "description": row.get("description") or "",
            "sku_id": row.get("sku_id") or "",
            "qty": row.get("qty") or 0.0,
            "unit_price": row.get("unit_price") or 0.0,
            "material_cost": row.get("material_cost") or 0.0,
            "test_cost": row.get("test_cost") or 0.0,
            "total_cost": row.get("total_cost") or 0.0
        })
    return sanitized

def sanitize_tech_recs(recs: List[dict]) -> List[dict]:
    """Ensure all technical recommendation fields are valid."""
    if not recs: return []
    sanitized = []
    for rec in recs:
        # Sanitize top 3 skus
        top_3 = []
        for match in rec.get("top_3_skus") or []:
            sku = match.get("sku") or {}
            top_3.append({
                "sku": {
                    "sku_id": sku.get("sku_id") or "",
                    "product_name": sku.get("product_name") or ""
                },
                "match_pct": match.get("match_pct") or 0.0
            })
            
        sanitized.append({
            "line_item_index": rec.get("line_item_index", 0),
            "rfp_item": {"Description": rec.get("rfp_item", {}).get("Description") or ""},
            "final_recommended_sku": rec.get("final_recommended_sku") or "N/A",
            "top_3_skus": top_3
        })
    return sanitized

def build_final_report_json(tender_doc: dict) -> Dict[str, Any]:
    """
    Aggregate all agent outputs into a final report structure.
    """
    return {
        "tender_title": tender_doc.get("title") or "Untitled Tender",
        "source": tender_doc.get("source_url") or "N/A",
        "sales_summary": tender_doc.get("sales_summary") or "No summary available.",
        "scope_of_supply": tender_doc.get("scope_of_supply") or [],
        "technical_recommendations": sanitize_tech_recs(tender_doc.get("technical_recommendations") or []),
        "pricing_table": sanitize_pricing_table(tender_doc.get("pricing_table") or []),
        "total_tender_price": tender_doc.get("total_tender_price") if tender_doc.get("total_tender_price") is not None else 0.0,
        "pipeline_run_id": tender_doc.get("pipeline_run_id") or "unknown",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

def render_pdf_from_template(final_json: dict, output_filename: str) -> str:
    """
    Render HTML template with data and convert to PDF.
    Returns absolute path to generated PDF.
    """
    try:
        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
        template = env.get_template("report_template.html")
        html_content = template.render(**final_json)
        
        output_path = os.path.join(REPORTS_DIR, output_filename)
        
        with open(output_path, "wb") as pdf_file:
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_file)
            
        if pisa_status.err:
            logger.error(f"PDF generation error: {pisa_status.err}")
            return ""
            
        return output_path
    except Exception as e:
        logger.error(f"Failed to render PDF: {e}")
        return ""

def process_tenders_via_master_agent(limit=20) -> List[str]:
    """
    Main pipeline for Master Agent.
    """
    tenders = find_ready_for_master(limit)
    if not tenders:
        logger.info("No pending tenders for Master Agent.")
        return []
    
    processed_ids = []
    
    for tender in tenders:
        try:
            tender_id = tender["_id"]
            logger.info(f"Master Agent processing tender {tender_id}...")
            
            # 1. Build JSON
            final_report = build_final_report_json(tender)
            
            # 2. Generate PDF
            pipeline_run_id = tender.get("pipeline_run_id", "unknown")
            pdf_filename = f"{pipeline_run_id}.pdf"
            pdf_path = render_pdf_from_template(final_report, pdf_filename)
            
            if not pdf_path:
                logger.error(f"Failed to generate PDF for tender {tender_id}")
                continue
                
            # 3. Save to MongoDB
            update_data = {
                "master_processed": True,
                "master_processed_at": datetime.now(),
                "final_report_json": final_report,
                "final_report_pdf_path": pdf_path,
                "report_engine_version": "1.0"
            }
            
            tenders_collection.update_one(
                {"_id": tender_id},
                {"$set": update_data}
            )
            
            processed_ids.append(str(tender_id))
            logger.info(f"Master Agent finished tender {tender_id}. PDF: {pdf_path}")
            
        except Exception as e:
            logger.error(f"Error in Master Agent for tender {tender.get('_id')}: {e}")
            
    return processed_ids

def master_agent_job():
    """
    Job to be scheduled.
    """
    logger.info("Starting Master Agent Job...")
    ids = process_tenders_via_master_agent()
    logger.info(f"Master Agent Job finished. Processed {len(ids)} tenders.")
