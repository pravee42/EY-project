import re

def clean_value(val):
    """Normalize string values for comparison."""
    if not val:
        return ""
    return str(val).lower().strip()

def extract_numeric(val):
    """Extract first numeric value from string."""
    if not val:
        return None
    match = re.search(r"(\d+(\.\d+)?)", str(val))
    if match:
        return float(match.group(1))
    return None

def compute_spec_match(rfp_item: dict, sku_item: dict) -> dict:
    """
    Computes match percentage between RFP item and SKU item.
    Attributes: conductor, insulation, voltage, size_sqmm, armour, temp_rating
    """
    attributes = ["conductor", "insulation", "voltage", "size_sqmm", "armour", "temp_rating"]
    scores = {}
    
    for attr in attributes:
        rfp_val = rfp_item.get(attr)
        sku_val = sku_item.get(attr)
        
        # If RFP doesn't specify an attribute, we assume it's not critical or matched
        # But for strict matching, if RFP has it and SKU doesn't, it's a mismatch.
        # If RFP doesn't have it, we can ignore it (score 1.0) or neutral.
        # Let's assume if RFP value is missing/empty, it's a match (wildcard).
        if not rfp_val:
            scores[attr] = 1.0
            continue
            
        if not sku_val:
            scores[attr] = 0.0
            continue
            
        # Check for numeric attributes (Voltage, Size, Temp)
        if attr in ["voltage", "size_sqmm", "temp_rating"]:
            r_num = extract_numeric(rfp_val)
            s_num = extract_numeric(sku_val)
            
            if r_num is not None and s_num is not None:
                # Numeric match logic: 1 - abs(diff) / max
                max_val = max(r_num, s_num, 1) # avoid div by zero
                diff = abs(r_num - s_num)
                score = max(0, 1 - (diff / max_val))
                scores[attr] = round(score, 2)
            else:
                # Fallback to string match if parsing fails
                r_str = clean_value(rfp_val)
                s_str = clean_value(sku_val)
                if r_str == s_str:
                    scores[attr] = 1.0
                elif r_str in s_str or s_str in r_str:
                    scores[attr] = 0.8
                else:
                    scores[attr] = 0.0
        else:
            # String attributes (Conductor, Insulation, Armour)
            r_str = clean_value(rfp_val)
            s_str = clean_value(sku_val)
            
            if r_str == s_str:
                scores[attr] = 1.0
            elif r_str in s_str or s_str in r_str:
                scores[attr] = 0.8
            else:
                scores[attr] = 0.0
                
    # Calculate final match percentage
    if not scores:
        final_pct = 0.0
    else:
        final_pct = (sum(scores.values()) / len(scores)) * 100
        
    return {
        "match_pct": round(final_pct, 2),
        "attribute_scores": scores
    }
