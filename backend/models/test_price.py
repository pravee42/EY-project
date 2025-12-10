from pydantic import BaseModel
from typing import Optional

class TestPrice(BaseModel):
    test_name: str
    test_code: Optional[str] = None
    price: float = 0.0
