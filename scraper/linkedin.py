import json
import time
import random
import logging
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

HEADERS_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))


def scrape_linkedin(search_query: str, location: str = "Germany", days_ago: int = 15) -> list[dict]:
    """
    Scrapes LinkedIn public job search (no login required).
    Returns a list of job dicts.
    """
    jobs = []
    # LinkedIn date filter: r86400=1day, r604800=1week, r2592000=1month
    # For 15 days we use the 1-month filter and post-filter by date
    url = (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={search_query.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}"
        f"&f_TPR=r1209600"  # past 14 days (closest LinkedIn filter)
        f"&f_JT=F"          # Full-time
        f"&sortBy=DD"        # Sort by date
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
            random_delay(3, 6)

            # Scroll to load more jobs
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                random_delay(1, 2)

            job_cards = page.query_selector_all(".base-card")
            logger.info(f"LinkedIn: found {len(job_cards)} cards")

            for card in job_cards[:30]:  # Limit to 30 per run
                try:
                    title_el = card.query_selector(".base-search-card__title")
                    company_el = card.query_selector(".base-search-card__subtitle")
                    location_el = card.query_selector(".job-search-card__location")
                    date_el = card.query_selector("time")
                    link_el = card.query_selector("a.base-card__full-link")

                    title = title_el.inner_text().strip() if title_el else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc = location_el.inner_text().strip() if location_el else ""
                    date_str = date_el.get_attribute("datetime") if date_el else ""
                    link = link_el.get_attribute("href") if link_el else ""

                    # Filter by date
                    if date_str:
                        try:
                            posted_date = datetime.fromisoformat(date_str[:10])
                            if (datetime.now() - posted_date).days > days_ago:
                                continue
                        except Exception:
                            pass

                    if not title or not link:
                        continue

                    # Get JD from job detail page
                    jd_text = _get_linkedin_jd(page, link)
                    random_delay(2, 4)

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": loc,
                        "date_posted": date_str[:10] if date_str else "",
                        "url": link.split("?")[0],
                        "jd_text": jd_text,
                        "platform": "LinkedIn",
                    })
                except Exception as e:
                    logger.warning(f"LinkedIn card parse error: {e}")
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"LinkedIn scraper error: {e}")

    return jobs


def _get_linkedin_jd(page, url: str) -> str:
    """Navigate to job page and extract JD text."""
    try:
        page.goto(url, timeout=20000, wait_until="domcontentloaded")
        random_delay(2, 3)
        # Try to click "Show more" if present
        try:
            page.click(".show-more-less-html__button", timeout=3000)
            random_delay(1, 2)
        except Exception:
            pass
        jd_el = page.query_selector(".show-more-less-html__markup")
        if jd_el:
            return jd_el.inner_text().strip()[:5000]
        # Fallback
        jd_el = page.query_selector(".description__text")
        if jd_el:
            return jd_el.inner_text().strip()[:5000]
    except Exception as e:
        logger.warning(f"LinkedIn JD fetch error: {e}")
    return ""
