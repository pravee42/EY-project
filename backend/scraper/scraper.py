import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging
from typing import List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_biddetail() -> List[dict]:
    """
    Scrapes tenders from biddetail.com (or similar structure).
    Uses fallback selectors to find content.
    """
    url = "https://www.biddetail.com"
    results = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        logger.info(f"Scraping {url}...")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Fallback selectors to identify tender cards/items
        selectors = [".post", ".news-card", "article", "h2", "h3"]
        items = []
        
        # Try to find items using the selectors in order
        for selector in selectors:
            found_items = soup.select(selector)
            if found_items:
                # If we found h2/h3, they might be titles, so we treat them as the item or look at parent
                # For simplicity, if we match h2/h3, we assume the header itself contains the title
                # and we might look at siblings for other info.
                items = found_items
                logger.info(f"Found {len(items)} items using selector '{selector}'")
                break
        
        if not items:
            logger.warning("No items found with fallback selectors.")
            return []

        for item in items:
            try:
                # Extract Title
                # If item is a header tag, use its text. Else look for a header inside.
                if item.name in ['h2', 'h3', 'h4', 'h5', 'h6']:
                    title = item.get_text(strip=True)
                else:
                    title_elem = item.select_one("h2, h3, h4, .title, a")
                    title = title_elem.get_text(strip=True) if title_elem else "Untitled Tender"

                if not title:
                    continue

                # Extract Summary
                # Look for paragraph or description classes
                summary = None
                summary_elem = item.find_next("p") if item.name in ['h2', 'h3'] else item.select_one("p, .description, .summary")
                if summary_elem:
                    summary = summary_elem.get_text(strip=True)
                    # Trim to 300-350 chars
                    if len(summary) > 350:
                        summary = summary[:347] + "..."

                # Extract PDF Link
                pdf_link = None
                # Search within item or next sibling if item is just a header
                container = item.parent if item.name in ['h2', 'h3'] else item
                pdf_elem = container.select_one("a[href$='.pdf']")
                if pdf_elem:
                    href = pdf_elem.get('href')
                    if href:
                        pdf_link = requests.compat.urljoin(url, href)

                # Extract Due Date
                due_date = None
                # Heuristic: look for 'due' or date patterns, or specific class
                # For now, we'll try a generic class or leave None as per instructions "if not available -> None"
                date_elem = container.select_one(".date, .due-date")
                if date_elem:
                    due_date = date_elem.get_text(strip=True)

                # Source URL
                source_url = url
                link_elem = item.select_one("a") if item.name not in ['a'] else item
                if link_elem and link_elem.get('href'):
                    href = link_elem.get('href')
                    source_url = requests.compat.urljoin(url, href)

                tender = {
                    "title": title,
                    "summary": summary,
                    "pdf_link": pdf_link,
                    "due_date": due_date,
                    "source_url": source_url,
                    "scraped_at": datetime.now(timezone.utc)
                }
                
                results.append(tender)

            except Exception as e:
                logger.error(f"Error parsing item: {e}")
                continue

    except Exception as e:
        logger.error(f"Error scraping {url}: {e}")

    return results

def scrape_all_sources() -> List[dict]:
    """
    Orchestrates scraping of all configured sources.
    """
    all_tenders = []
    
    # # 1. Scrape Biddetail
    # try:
    #     tenders = scrape_biddetail()
    #     all_tenders.extend(tenders)
    # except Exception as e:
    #     logger.error(f"Failed to scrape Biddetail: {e}")

    # 2. Scrape Mock Site (Localhost)
    try:
        tenders = scrape_mock_site()
        all_tenders.extend(tenders)
    except Exception as e:
        logger.error(f"Failed to scrape Mock Site: {e}")
    
    return all_tenders

import requests
import os
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") # Keep for reference or remove if strictly switching
OPENAI_API_KEY = "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"

def analyze_tenders_with_ai(tenders: List[dict]) -> List[dict]:
    """
    Sends a list of tenders to OpenAI via REST API to classify them.
    """
    if not tenders or not OPENAI_API_KEY:
        missing_item = "tenders" if not tenders else "OpenAI API Key"
        logger.warning(f"Skipping AI analysis: No {missing_item} missing.")
        return tenders
    
    try:
        url = "https://api.openai.com/v1/chat/completions"
        
        # Prepare a simplified list for the prompt
        tender_summaries = []
        for i, t in enumerate(tenders):
            tender_summaries.append({
                "id": i,
                "title": t["title"],
                "summary": t["summary"]
            })
            
        prompt = f"""
        You are an expert procurement analyst.
        Analyze the following list of tenders.
        For each tender, classify it into one of these exact categories:
        1. "FMEG" (Fast Moving Electrical Goods)
        2. "Cables/Wires"
        3. "Other"
        
        Input JSON:
        {json.dumps(tender_summaries)}
        
        Return ONLY a valid JSON object where keys are the string "id" (from input) and values are the category string.
        Example format: {{"0": "FMEG", "1": "Other"}}
        Do not include markdown formatting like ```json.
        """
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {OPENAI_API_KEY}'
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        # Extract text from response structure
        try:
            response_text = result['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected OpenAI response structure: {result}")
            return tenders

        # Clean up markdown if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        categories = json.loads(response_text)
        
        for i, tender in enumerate(tenders):
            cat = categories.get(str(i), "Uncategorized")
            tender["category"] = cat
            tenders[i]["category"] = cat
            # logger.info(f"Tender '{tender['title'][:30]}...' classified as: {cat}")
            
    except Exception as e:
        logger.error(f"Error analyzing tenders with OpenAI REST API: {e}")
        
    return tenders

def scrape_mock_site() -> List[dict]:
    """
    Scrapes the locally hosted mock tender website, handling pagination.
    """
    # Updated URL as per request
    base_url = "http://127.0.0.1:5500/mock_website"
    start_url = f"{base_url}/index.html"
    results = []
    
    current_url = start_url
    visited_urls = set()
    
    while current_url and current_url not in visited_urls:
        try:
            logger.info(f"Scraping Mock Site Page: {current_url}...")
            visited_urls.add(current_url)
            
            response = requests.get(current_url, timeout=5)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            cards = soup.select(".tender-card")
            
            logger.info(f"Found {len(cards)} tenders on {current_url}")
            
            page_tenders = []
            
            for card in cards:
                try:
                    title = card.select_one(".tender-title").get_text(strip=True)
                    company = card.select_one(".company-name").get_text(strip=True)
                    summary = card.select_one(".tender-desc").get_text(strip=True)
                    
                    full_title = f"{title} ({company})"
                    
                    due_date_text = card.select_one(".deadline").get_text(strip=True)
                    due_date = due_date_text.replace("Deadline:", "").strip()
                    
                    pdf_elem = card.select_one(".rfp-link")
                    pdf_link = None
                    if pdf_elem and pdf_elem.get('href'):
                         pdf_link = requests.compat.urljoin(current_url, pdf_elem['href'])
                    
                    tender = {
                        "title": full_title,
                        "summary": summary,
                        "pdf_link": pdf_link,
                        "due_date": due_date,
                        "source_url": current_url,
                        "scraped_at": datetime.now(timezone.utc),
                        "category": "Pending AI Analysis"
                    }
                    page_tenders.append(tender)
                    
                except Exception as e:
                    logger.error(f"Error parsing mock card: {e}")
            
            # Analyze this page's tenders with AI
            if page_tenders:
                logger.info("Sending page tenders to OpenAI for analysis...")
                analyzed_tenders = analyze_tenders_with_ai(page_tenders)
                results.extend(analyzed_tenders)
            
            # Find Next Page
            next_link = soup.find('a', string="Next")
            if next_link and next_link.get('href') and '#' not in next_link.get('href'):
                next_href = next_link.get('href')
                current_url = requests.compat.urljoin(current_url, next_href)
            else:
                current_url = None
                
        except Exception as e:
            logger.warning(f"Could not scrape {current_url}. Error: {e}")
            current_url = None
    return results
