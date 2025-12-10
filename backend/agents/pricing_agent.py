import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Tuple
import json

from database.mongo import tenders_collection, inventory_collection, test_pricing_collection
from agents.llm_client import call_llm

logger = logging.getLogger(__name__)

def find_ready_for_pricing(limit=20) -> List[dict]:
    """
    Fetch tenders where sales_processed=True, technical_processed=True, pricing_processed!=True
    """
    if tenders_collection is None:
        logger.error("Database not connected.")
        return []
    
    query = {
        "sales_processed": True,
        "technical_processed": True,
        "pricing_processed": {"$ne": True}
    }
    return list(tenders_collection.find(query).limit(limit))

def extract_tests(pricing_summary_text: str) -> List[str]:
    """
    Extract list of required test names from the pricing summary text.
    Uses LLM for robustness.
    """
    if not pricing_summary_text:
        return []
    
    all_tests = list(test_pricing_collection.find({}))
        
    prompt = f"""
    Analyze the following Pricing/Testing Summary text and extract a list of specific test names required.
    
    TEXT:
    {pricing_summary_text}
    
    Information about test Codes:
    {str(all_tests)}

    OUTPUT:
    Return ONLY a comma-separated list of test Codes not test_name. Example: "RT-01, RT-02, RT-03"
    """
    try:
        response = call_llm(prompt)
        if response:
            # Split by comma and clean
            tests = [t.strip() for t in response.split(',')]
            return [t for t in tests if t]
    except Exception as e:
        logger.error(f"Error extracting tests via LLM: {e}")
        
    return []

def get_inventory_by_sku(sku_id: str) -> Dict[str, Any]:
    """
    Find SKU in inventory.
    """
    if inventory_collection is None or not sku_id:
        return {}
    return inventory_collection.find_one({"sku_id": sku_id}) or {}

def get_test_prices(test_list: List[str]) -> Dict[str, float]:
    """
    Fetch prices for the list of tests from test_pricing collection.
    Returns dict {test_name: price}
    """
    if test_pricing_collection is None or not test_list:
        return {}
    
    prices = {}
    # Simple regex match or exact match. For now, let's try to find exact or partial matches.
    # In a real system, we'd need fuzzy matching or standardized codes.
    
    # Fetch all test prices once (assuming small table)
    all_tests = list(test_pricing_collection.find({}))
    
    for req_test in test_list:
        price = 0.0
        req_test_lower = req_test.lower()
        
        for db_test in all_tests:
            # Check if db test name is in requested test name or vice versa
            db_name = db_test.get("test_code", "").lower()
            if db_name and (db_name in req_test_lower or req_test_lower in db_name):
                price = float(db_test.get("price", 0.0))
                break
        
        prices[req_test] = price
        
    return prices

def calculate_pricing_for_line_item(rfp_item: dict, sku_item: dict, test_list: List[str], test_prices: Dict[str, float]) -> Dict[str, Any]:
    """
    Calculate material cost, test cost, and total cost for a single line item.
    """
    # 1. Quantity
    qty_str = rfp_item.get("Quantity", "1")
    # Extract numeric quantity
    qty = 1.0
    match = re.search(r"(\d+(\.\d+)?)", str(qty_str))
    if match:
        qty = float(match.group(1))
        # Check units? Assuming Km/Meters/Nos match unit price.
        # If unit price is per Meter and Qty is Km, we need conversion.
        # For MVP, assume units match.
    
    # 2. Material Cost
    unit_price = float(sku_item.get("unit_price", 0.0))
    material_cost = unit_price * qty
    
    # 3. Test Cost
    test_cost = 0.0
    item_tests = []
    
    for test in test_list:
        price = test_prices.get(test, 0.0)
        test_cost += price
        item_tests.append({"test_name": test, "price": price})
        
    # 4. Total
    total_cost = material_cost + test_cost
    
    return {
        "qty": qty,
        "unit_price": unit_price,
        "material_cost": material_cost,
        "tests": item_tests,
        "test_cost": test_cost,
        "total_cost": total_cost
    }

def process_tenders_via_pricing_agent(limit=20) -> List[str]:
    """
    Main pipeline for Pricing Agent.
    """
    tenders = find_ready_for_pricing(limit)
    if not tenders:
        logger.info("No pending tenders for Pricing Agent.")
        return []
    
    processed_ids = []
    
    for tender in tenders:
        try:
            tender_id = tender["_id"]
            logger.info(f"Pricing Agent processing tender {tender_id}...")
            
            # 1. Extract Tests
            pricing_summary = tender.get("pricing_summary_text", "")
            required_tests = extract_tests(pricing_summary)
            test_prices = get_test_prices(required_tests)
            
            # 2. Process Recommendations
            recommendations = tender.get("technical_recommendations", [])
            pricing_table = []
            total_tender_price = 0.0
            
            for rec in recommendations:
                rfp_item = rec.get("rfp_item", {})
                sku_id = rec.get("final_recommended_sku")
                
                sku_details = {}
                if sku_id:
                    sku_details = get_inventory_by_sku(sku_id)
                
                # Calculate
                costs = calculate_pricing_for_line_item(rfp_item, sku_details, required_tests, test_prices)
                
                line_entry = {
                    "line_item_index": rec.get("line_item_index"),
                    "sku_id": sku_id,
                    "description": rfp_item.get("Description", "Unknown"),
                    "qty": costs["qty"],
                    "unit_price": costs["unit_price"],
                    "material_cost": costs["material_cost"],
                    "tests": costs["tests"],
                    "test_cost": costs["test_cost"],
                    "total_cost": costs["total_cost"]
                }
                
                pricing_table.append(line_entry)
                total_tender_price += costs["total_cost"]
            
            # 3. Save to MongoDB
            update_data = {
                "pricing_processed": True,
                "pricing_processed_at": datetime.now(),
                "pricing_table": pricing_table,
                "total_tender_price": total_tender_price,
                "pricing_engine_version": "1.0"
            }
            
            tenders_collection.update_one(
                {"_id": tender_id},
                {"$set": update_data}
            )
            
            processed_ids.append(str(tender_id))
            logger.info(f"Pricing Agent finished tender {tender_id}. Total: {total_tender_price}")
            
        except Exception as e:
            logger.error(f"Error in Pricing Agent for tender {tender.get('_id')}: {e}")
            
    return processed_ids

def pricing_agent_job():
    """
    Job to be scheduled.
    """
    logger.info("Starting Pricing Agent Job...")
    ids = process_tenders_via_pricing_agent()
    logger.info(f"Pricing Agent Job finished. Processed {len(ids)} tenders.")
