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


def scrape_glassdoor(search_query: str, location: str = "Germany", days_ago: int = 15) -> list[dict]:
    """
    Scrapes Glassdoor for product manager jobs in Germany.
    Returns a list of job dicts.
    """
    jobs = []
    url = (
        f"https://www.glassdoor.com/Job/germany-{search_query.replace(' ', '-')}-jobs-SRCH_IL.0,7_IN96_KO8,{8 + len(search_query)}.htm"
        f"?fromAge={days_ago}&sortBy=date_desc"
    )
    # Fallback simpler URL
    url_simple = (
        f"https://www.glassdoor.com/Job/jobs.htm"
        f"?sc.keyword={search_query.replace(' ', '+')}"
        f"&locId=96&locT=N"  # Germany
        f"&fromAge={days_ago}&sortBy=date_desc"
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
            
            # Try Glassdoor — it heavily blocks bots, use fallback gracefully
            try:
                page.goto(url_simple, timeout=25000, wait_until="domcontentloaded")
            except Exception:
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
            
            random_delay(3, 6)

            job_cards = page.query_selector_all('[data-test="jobListing"]')
            if not job_cards:
                job_cards = page.query_selector_all(".react-job-listing")
            logger.info(f"Glassdoor: found {len(job_cards)} cards")

            for card in job_cards[:20]:
                try:
                    title_el = card.query_selector('[data-test="job-title"]') or card.query_selector(".job-title")
                    company_el = card.query_selector('[data-test="employer-short-name"]') or card.query_selector(".employer-short-name")
                    location_el = card.query_selector('[data-test="emp-location"]') or card.query_selector(".location")
                    date_el = card.query_selector('[data-test="listing-age"]') or card.query_selector(".listing-age")
                    link_el = card.query_selector("a[data-test='job-title']") or card.query_selector("a.jobLink")

                    title = title_el.inner_text().strip() if title_el else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc = location_el.inner_text().strip() if location_el else ""
                    date_text = date_el.inner_text().strip() if date_el else ""
                    link_path = link_el.get_attribute("href") if link_el else ""

                    if not title or not link_path:
                        continue

                    if link_path.startswith("/"):
                        link = f"https://www.glassdoor.com{link_path}"
                    else:
                        link = link_path

                    # Click card to load JD in panel
                    try:
                        card.click()
                        random_delay(2, 3)
                        jd_el = page.query_selector(".jobDescriptionContent") or page.query_selector('[data-test="description"]')
                        jd_text = jd_el.inner_text().strip()[:5000] if jd_el else ""
                    except Exception:
                        jd_text = ""

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": loc,
                        "date_posted": _parse_glassdoor_date(date_text),
                        "url": link,
                        "jd_text": jd_text,
                        "platform": "Glassdoor",
                    })
                except Exception as e:
                    logger.warning(f"Glassdoor card parse error: {e}")
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"Glassdoor scraper error: {e}")

    return jobs


def _parse_glassdoor_date(date_text: str) -> str:
    """Convert Glassdoor relative date to ISO string."""
    today = datetime.now()
    try:
        if "today" in date_text.lower() or "just now" in date_text.lower():
            return today.strftime("%Y-%m-%d")
        elif "hour" in date_text.lower():
            return today.strftime("%Y-%m-%d")
        elif "day" in date_text.lower():
            days = int("".join(filter(str.isdigit, date_text)) or "0")
            from datetime import timedelta
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        pass
    return today.strftime("%Y-%m-%d")
