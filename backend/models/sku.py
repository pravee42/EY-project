from typing import Optional
from pydantic import BaseModel

class SKU(BaseModel):
    sku_id: str
    product_name: str
    conductor: Optional[str] = None
    insulation: Optional[str] = None
    voltage: Optional[str] = None
    size_sqmm: Optional[str] = None
    armour: Optional[str] = None
    temp_rating: Optional[str] = None
    unit_price: float = 0.0
