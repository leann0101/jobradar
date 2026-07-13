from __future__ import annotations
import time
import random
import logging
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
]


def random_delay(min_sec=1, max_sec=3):
    time.sleep(random.uniform(min_sec, max_sec))


def scrape_glassdoor(search_query: str, location: str = "Germany", days_ago: int = 15, existing_urls: set[str] = None) -> list[dict]:
    """
    Scrapes Glassdoor for PM jobs in Germany using requests + BeautifulSoup.
    Glassdoor heavily uses JavaScript; we use their public job listing pages.
    """
    jobs = []
    headers = random.choice(HEADERS_LIST)

    # Glassdoor's public job search URL (no login required for basic listing)
    url = (
        f"https://www.glassdoor.com/Job/germany-{search_query.replace(' ', '-')}-jobs-SRCH_IL.0,7_IN96_KO8,{8 + len(search_query)}.htm"
        f"?fromAge={days_ago}&sortBy=date_desc"
    )

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = (
            soup.find_all("li", attrs={"data-test": "jobListing"}) or
            soup.find_all("article", class_="JobCard") or
            soup.find_all("li", class_="react-job-listing")
        )
        logger.info(f"Glassdoor: found {len(cards)} cards")

        for card in cards[:20]:
            try:
                title_el   = card.find(attrs={"data-test": "job-title"}) or card.find("a", class_="job-title")
                company_el = card.find(attrs={"data-test": "employer-short-name"}) or card.find("div", class_="employer-name")
                loc_el     = card.find(attrs={"data-test": "emp-location"}) or card.find("div", class_="location")
                date_el    = card.find(attrs={"data-test": "listing-age"}) or card.find("div", class_="listing-age")
                link_el    = card.find("a")

                title   = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                loc     = loc_el.get_text(strip=True) if loc_el else location
                date_text = date_el.get_text(strip=True) if date_el else ""
                link_path = link_el.get("href", "") if link_el else ""

                if not title or not link_path:
                    continue

                link = f"https://www.glassdoor.com{link_path}" if link_path.startswith("/") else link_path
                link_clean = link.split("?")[0]
                if existing_urls and link_clean in existing_urls:
                    logger.info(f"Skipping already-scraped Glassdoor job: {link_clean}")
                    continue

                jd_text = _fetch_glassdoor_jd(link, headers)
                random_delay(1, 2)

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "date_posted": _parse_relative_date(date_text),
                    "url": link_clean,
                    "jd_text": jd_text,
                    "platform": "Glassdoor",
                })
            except Exception as e:
                logger.warning(f"Glassdoor card error: {e}")
                continue

    except Exception as e:
        logger.error(f"Glassdoor scraper error: {e}")

    return jobs


def _fetch_glassdoor_jd(url: str, headers: dict) -> str:
    """Fetch Glassdoor job description."""
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        jd_el = (
            soup.find("div", class_="jobDescriptionContent") or
            soup.find(attrs={"data-test": "description"}) or
            soup.find("div", id="JobDescriptionContainer")
        )
        if jd_el:
            return jd_el.get_text(separator="\n", strip=True)[:4000]
    except Exception as e:
        logger.warning(f"Glassdoor JD error: {e}")
    return ""


def _parse_relative_date(date_text: str) -> str:
    """Convert relative date to ISO format."""
    today = datetime.now()
    try:
        text = date_text.lower()
        if "today" in text or "just" in text or "hour" in text:
            return today.strftime("%Y-%m-%d")
        elif "day" in text:
            days = int("".join(filter(str.isdigit, text)) or "1")
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        pass
    return today.strftime("%Y-%m-%d")
