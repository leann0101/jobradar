import time
import random
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

HEADERS_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))


def scrape_indeed(search_query: str, location: str = "Germany", days_ago: int = 15) -> list[dict]:
    """
    Scrapes Indeed Germany for product manager jobs.
    Returns a list of job dicts.
    """
    jobs = []
    # Indeed fromage param: number of days ago
    fromage = min(days_ago, 14)  # Indeed max is 14
    url = (
        f"https://de.indeed.com/jobs"
        f"?q={search_query.replace(' ', '+')}"
        f"&l={location.replace(' ', '+')}"
        f"&lang=en"  # English jobs
        f"&fromage={fromage}"
        f"&sort=date"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(HEADERS_LIST),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            random_delay(3, 5)

            job_cards = page.query_selector_all('[data-testid="slider_item"]')
            if not job_cards:
                job_cards = page.query_selector_all(".job_seen_beacon")
            logger.info(f"Indeed: found {len(job_cards)} cards")

            for card in job_cards[:25]:
                try:
                    title_el = card.query_selector("h2.jobTitle span[title]") or card.query_selector("h2.jobTitle")
                    company_el = card.query_selector('[data-testid="company-name"]') or card.query_selector(".companyName")
                    location_el = card.query_selector('[data-testid="text-location"]') or card.query_selector(".companyLocation")
                    date_el = card.query_selector('[data-testid="myJobsStateDate"]') or card.query_selector(".date")
                    link_el = card.query_selector("h2.jobTitle a") or card.query_selector("a.jcs-JobTitle")

                    title = title_el.inner_text().strip() if title_el else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc = location_el.inner_text().strip() if location_el else ""
                    date_text = date_el.inner_text().strip() if date_el else ""
                    link_path = link_el.get_attribute("href") if link_el else ""

                    if not title or not link_path:
                        continue

                    # Build full URL
                    if link_path.startswith("/"):
                        link = f"https://de.indeed.com{link_path}"
                    else:
                        link = link_path

                    # Get JD
                    jd_text = _get_indeed_jd(page, link)
                    random_delay(2, 4)

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": loc,
                        "date_posted": _parse_indeed_date(date_text),
                        "url": link.split("?")[0],
                        "jd_text": jd_text,
                        "platform": "Indeed",
                    })
                except Exception as e:
                    logger.warning(f"Indeed card parse error: {e}")
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"Indeed scraper error: {e}")

    return jobs


def _get_indeed_jd(page, url: str) -> str:
    """Navigate to Indeed job page and extract JD text."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        random_delay(2, 3)
        jd_el = page.query_selector("#jobDescriptionText")
        if jd_el:
            return jd_el.inner_text().strip()[:5000]
    except Exception as e:
        logger.warning(f"Indeed JD fetch error: {e}")
    return ""


def _parse_indeed_date(date_text: str) -> str:
    """Convert Indeed relative date text to ISO date string."""
    today = datetime.now()
    try:
        if "today" in date_text.lower() or "just posted" in date_text.lower():
            return today.strftime("%Y-%m-%d")
        elif "day" in date_text.lower():
            days = int("".join(filter(str.isdigit, date_text)) or "0")
            return (today - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        pass
    return today.strftime("%Y-%m-%d")
