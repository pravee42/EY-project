from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Tender(BaseModel):
    title: str
    summary: Optional[str] = None
    due_date: Optional[str] = None
    source_url: str
    pdf_link: Optional[str] = None
    category: Optional[str] = "Uncategorized"
    scraped_at: datetime
    
    # Sales Agent Fields
    sales_processed: bool = False
    sales_processed_at: Optional[datetime] = None
    sales_summary: Optional[str] = None
    technical_prompt: Optional[str] = None
    pricing_prompt: Optional[str] = None
    technical_summary_text: Optional[str] = None
    pricing_summary_text: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    
    # Technical Agent Fields
    technical_processed: bool = False
    technical_processed_at: Optional[datetime] = None
    scope_of_supply: Optional[List[dict]] = None
    technical_recommendations: Optional[List[dict]] = None
    technical_engine_version: Optional[str] = None
    
    # Pricing Agent Fields
    pricing_processed: bool = False
    pricing_processed_at: Optional[datetime] = None
    pricing_table: Optional[List[dict]] = None
    total_tender_price: Optional[float] = None
    pricing_engine_version: Optional[str] = None
    
    # Master Agent Fields
    master_processed: bool = False
    master_processed_at: Optional[datetime] = None
    final_report_json: Optional[dict] = None
    final_report_pdf_path: Optional[str] = None
    report_engine_version: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
