import logging
import json
import re
from datetime import datetime
from typing import List, Dict, Any

from database.mongo import tenders_collection, inventory_collection
from spec_match_engine import compute_spec_match

logger = logging.getLogger(__name__)

def find_sales_processed_tenders(limit=20) -> List[dict]:
    """
    Fetch tenders where sales_processed=True AND technical_processed!=True
    """
    if tenders_collection is None:
        logger.error("Database not connected.")
        return []
    
    query = {
        "sales_processed": True,
        "technical_processed": {"$ne": True}
    }
    return list(tenders_collection.find(query).limit(limit))

def get_inventory_skus() -> List[dict]:
    """
    Fetch all SKUs from inventory.
    """
    if inventory_collection is None:
        return []
    return list(inventory_collection.find({}, {"_id": 0}))

def parse_technical_summary(text: str) -> List[dict]:
    """
    Parses the JSON list of items from the LLM technical summary text.
    Expected format in text: ITEMS: [...]
    """
    if not text:
        return []
    
    try:
        # Look for ITEMS: marker
        if "**ITEMS:**" in text:
            json_part = text.split("**ITEMS:**")[1].strip()
            # It might be wrapped in ```json ... ```
            if json_part.startswith("```"):
                # Remove first line (```json) and last line (```)
                lines = json_part.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                lines = [x.strip() for x in lines]
                lines = lines[:lines.index('```')]
                json_part = "\n".join(lines)
            # Attempt to parse
            items = json.loads(json_part)
            if isinstance(items, list):
                return items
    except Exception as e:
        logger.error(f"Failed to parse technical summary JSON: {e}")
    return []

from agents.llm_client import call_llm

def match_line_item_to_skus_with_llm(rfp_item: dict, sku_list: List[dict]) -> List[dict]:
    """
    Use LLM to match RFP item against ALL inventory SKUs.
    Returns Top 3 SKUs with match percentage and reasoning.
    """
    if not sku_list:
        return []

    # Prepare simplified inventory list for prompt to save tokens
    # We send all SKUs to the LLM. If inventory is huge, we might need to chunk or use RAG.
    # For now assuming manageable inventory size (<50-100 items).
    simplified_inventory = []
    for sku in sku_list:
        simplified_inventory.append({
            "sku_id": sku.get("sku_id"),
            "product_name": sku.get("product_name"),
            "specs": {k: v for k, v in sku.items() if k not in ["sku_id", "product_name", "_id", "unit_price"]}
        })

    prompt = f"""
    You are an expert Technical Sales Engineer.
    Your task is to find the best matching products from the Inventory for a specific RFP Line Item.

    RFP LINE ITEM:
    {json.dumps(rfp_item, indent=2)}

    INVENTORY LIST:
    {json.dumps(simplified_inventory, indent=2)}

    INSTRUCTIONS:
    1. Analyze the RFP item requirements (Description, Specs, etc.).
    2. Compare against EACH item in the Inventory.
    3. Select the Top 5 matches based on technical specifications (Conductor, Insulation, Voltage, Size, Armour, etc.).
    4. Calculate a match percentage (0-100%) for each.
    5. From the Top 5, strictly filter down to the Top 3 best matches.
    6. Provide a brief reasoning for the match.

    OUTPUT FORMAT:
    Return ONLY a valid JSON list of the Top 3 matches.
    [
      {{
        "sku_id": "SKU123",
        "match_pct": 95.5,
        "reasoning": "Exact match on voltage and size..."
      }},
      ...
    ]
    """

    try:
        response_text = call_llm(prompt)
        
        # Clean up markdown
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        matches = json.loads(response_text.strip())
        
        # Rehydrate with full SKU details
        final_results = []
        for match in matches:
            sku_id = match.get("sku_id")
            full_sku = next((s for s in sku_list if s.get("sku_id") == sku_id), None)
            if full_sku:
                final_results.append({
                    "sku": full_sku,
                    "match_pct": match.get("match_pct", 0),
                    "reasoning": match.get("reasoning", "")
                })
                
        return final_results

    except Exception as e:
        logger.error(f"LLM Matching failed: {e}")
        return []

def build_comparison_table(rfp_item: dict, top_3_skus: List[dict]) -> Dict[str, Any]:
    """
    Builds a dictionary for the comparison table.
    """
    attributes = ["conductor", "insulation", "voltage", "size_sqmm", "armour", "temp_rating", "product_name"]
    table = {}
    
    for attr in attributes:
        row = {
            "rfp_value": rfp_item.get(attr, "N/A"),
            "sku1_value": top_3_skus[0]["sku"].get(attr, "N/A") if len(top_3_skus) > 0 else "-",
            "sku2_value": top_3_skus[1]["sku"].get(attr, "N/A") if len(top_3_skus) > 1 else "-",
            "sku3_value": top_3_skus[2]["sku"].get(attr, "N/A") if len(top_3_skus) > 2 else "-"
        }
        table[attr] = row
        
    return table

def process_tenders_via_technical_agent(limit=20) -> List[str]:
    """
    Main pipeline for Technical Agent.
    """
    tenders = find_sales_processed_tenders(limit)
    if not tenders:
        logger.info("No pending tenders for Technical Agent.")
        return []
    
    inventory = get_inventory_skus()
    if not inventory:
        logger.warning("Inventory is empty! Cannot perform matching.")
        # We might still want to process them but with 0 matches? 
        # For now let's proceed, matches will just be empty.
    
    processed_ids = []
    
    for tender in tenders:
        try:
            tender_id = tender["_id"]
            logger.info(f"Technical Agent processing tender {tender_id}...")
            
            # 1. Parse Line Items
            tech_text = tender.get("technical_summary_text", "")
            scope_of_supply = parse_technical_summary(tech_text)
            
            if not scope_of_supply:
                logger.warning(f"No line items found for tender {tender_id}")
                # We still mark it processed so we don't loop forever
            
            recommendations = []
            
            # 2. Match each item
            for idx, item in enumerate(scope_of_supply):
                # Normalize keys to lowercase for matching engine
                # The LLM might return "Description", "Quantity" etc.
                # The engine expects "conductor", "insulation" etc.
                # Let's normalize the item dict keys to lowercase
                normalized_item = {k.lower(): v for k, v in item.items()}
                
                # Use LLM matching instead of rule-based
                top_3 = match_line_item_to_skus_with_llm(normalized_item, inventory)
                
                comparison = build_comparison_table(normalized_item, top_3)
                
                # Pick best SKU
                best_sku_id = None
                if top_3 and top_3[0]["match_pct"] > 0:
                    best_sku_id = top_3[0]["sku"].get("sku_id")
                
                rec = {
                    "line_item_index": idx,
                    "rfp_item": item,
                    "top_3_skus": top_3,
                    "comparison_table": comparison,
                    "final_recommended_sku": best_sku_id
                }
                recommendations.append(rec)
            
            # 3. Save to MongoDB
            update_data = {
                "technical_processed": True,
                "technical_processed_at": datetime.now(),
                "scope_of_supply": scope_of_supply,
                "technical_recommendations": recommendations,
                "technical_engine_version": "1.0"
            }
            
            tenders_collection.update_one(
                {"_id": tender_id},
                {"$set": update_data}
            )
            
            processed_ids.append(str(tender_id))
            logger.info(f"Technical Agent finished tender {tender_id}")
            
        except Exception as e:
            logger.error(f"Error in Technical Agent for tender {tender.get('_id')}: {e}")
            
    return processed_ids

def technical_agent_job():
    """
    Job to be scheduled.
    """
    logger.info("Starting Technical Agent Job...")
    ids = process_tenders_via_technical_agent()
    logger.info(f"Technical Agent Job finished. Processed {len(ids)} tenders.")
