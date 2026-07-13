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
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
]


def random_delay(min_sec=1, max_sec=3):
    time.sleep(random.uniform(min_sec, max_sec))


def scrape_indeed(search_query: str, location: str = "Germany", days_ago: int = 15, existing_urls: set[str] = None) -> list[dict]:
    """
    Scrapes Indeed Germany for PM jobs using requests + BeautifulSoup.
    """
    jobs = []
    headers = random.choice(HEADERS_LIST)
    fromage = min(days_ago, 14)

    url = (
        f"https://de.indeed.com/jobs"
        f"?q={search_query.replace(' ', '+')}"
        f"&l={location.replace(' ', '+')}"
        f"&fromage={fromage}"
        f"&sort=date"
        f"&lang=en"
    )

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = (
            soup.find_all("div", class_="job_seen_beacon") or
            soup.find_all("div", attrs={"data-testid": "slider_item"}) or
            soup.find_all("div", class_="result")
        )
        logger.info(f"Indeed: found {len(cards)} cards")

        for card in cards[:25]:
            try:
                title_el   = card.find("h2", class_="jobTitle") or card.find("h2")
                company_el = (
                    card.find(attrs={"data-testid": "company-name"}) or
                    card.find("span", class_="companyName")
                )
                loc_el = (
                    card.find(attrs={"data-testid": "text-location"}) or
                    card.find("div", class_="companyLocation")
                )
                date_el = (
                    card.find(attrs={"data-testid": "myJobsStateDate"}) or
                    card.find("span", class_="date")
                )
                link_el = card.find("a", class_="jcs-JobTitle") or (title_el.find("a") if title_el else None)

                title   = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                loc     = loc_el.get_text(strip=True) if loc_el else location
                date_text = date_el.get_text(strip=True) if date_el else ""
                link_path = link_el.get("href", "") if link_el else ""

                if not title or not link_path:
                    continue

                link = f"https://de.indeed.com{link_path}" if link_path.startswith("/") else link_path
                link_clean = link.split("?")[0]
                if existing_urls and link_clean in existing_urls:
                    logger.info(f"Skipping already-scraped Indeed job: {link_clean}")
                    continue

                jd_text = _fetch_indeed_jd(link, headers)
                random_delay(1, 2)

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "date_posted": _parse_relative_date(date_text),
                    "url": link_clean,
                    "jd_text": jd_text,
                    "platform": "Indeed",
                })
            except Exception as e:
                logger.warning(f"Indeed card error: {e}")
                continue

    except Exception as e:
        logger.error(f"Indeed scraper error: {e}")

    return jobs


def _fetch_indeed_jd(url: str, headers: dict) -> str:
    """Fetch Indeed job description page."""
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        jd_el = soup.find(id="jobDescriptionText") or soup.find("div", class_="jobsearch-jobDescriptionText")
        if jd_el:
            return jd_el.get_text(separator="\n", strip=True)[:4000]
    except Exception as e:
        logger.warning(f"Indeed JD error: {e}")
    return ""


def _parse_relative_date(date_text: str) -> str:
    """Convert relative date text to ISO format."""
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
