import requests
import os
import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")

def call_llm(prompt: str) -> Optional[str]:
    """
    Generic wrapper to call OpenAI LLM.
    Returns the generated text or None on failure.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found.")
        return None

    url = "https://api.openai.com/v1/chat/completions"
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful AI assistant."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        return result['choices'][0]['message']['content'].strip()
        
    except Exception as e:
        logger.error(f"LLM Call Failed: {e}")
        return None
