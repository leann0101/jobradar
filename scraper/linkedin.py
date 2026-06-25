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


def scrape_linkedin(search_query: str, location: str = "Germany", days_ago: int = 15) -> list[dict]:
    """
    Scrapes LinkedIn public job search page using requests (no browser needed).
    Note: LinkedIn heavily blocks scrapers; this uses the public JSON API endpoint.
    """
    jobs = []
    headers = random.choice(HEADERS_LIST)

    # LinkedIn public job search API (no login needed)
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={search_query.replace(' ', '%20')}"
        f"&location={location.replace(' ', '%20')}"
        f"&f_TPR=r{days_ago * 86400}"   # Convert days to seconds
        f"&f_JT=F"                       # Full-time
        f"&sortBy=DD"                    # Sort by date
        f"&start=0"
    )

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"LinkedIn returned {resp.status_code}")
            # Try fallback URL
            url2 = (
                "https://www.linkedin.com/jobs/search/"
                f"?keywords={search_query.replace(' ', '+')}"
                f"&location={location.replace(' ', '+')}"
                f"&f_TPR=r{min(days_ago, 14) * 86400}"
                f"&sortBy=DD"
            )
            resp = requests.get(url2, headers=headers, timeout=15)

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("div", class_="base-card") or soup.find_all("li", class_="jobs-search__results-list")
        logger.info(f"LinkedIn: found {len(cards)} cards")

        for card in cards[:25]:
            try:
                title_el   = card.find("h3", class_="base-search-card__title") or card.find("h3")
                company_el = card.find("h4", class_="base-search-card__subtitle") or card.find("h4")
                loc_el     = card.find("span", class_="job-search-card__location") or card.find("span", class_="job-result-card__location")
                date_el    = card.find("time")
                link_el    = card.find("a", class_="base-card__full-link") or card.find("a")

                title   = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                loc     = loc_el.get_text(strip=True) if loc_el else location
                date_str = date_el.get("datetime", "") if date_el else ""
                link    = link_el.get("href", "") if link_el else ""

                if not title or not link:
                    continue

                # Filter by date
                if date_str:
                    try:
                        posted = datetime.fromisoformat(date_str[:10])
                        if (datetime.now() - posted).days > days_ago:
                            continue
                    except Exception:
                        pass

                # Get JD from job page
                jd_text = _fetch_page_text(link.split("?")[0], headers)
                random_delay(1, 2)

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "date_posted": date_str[:10] if date_str else datetime.now().strftime("%Y-%m-%d"),
                    "url": link.split("?")[0],
                    "jd_text": jd_text,
                    "platform": "LinkedIn",
                })
            except Exception as e:
                logger.warning(f"LinkedIn card error: {e}")
                continue

    except Exception as e:
        logger.error(f"LinkedIn scraper error: {e}")

    return jobs


def _fetch_page_text(url: str, headers: dict, max_chars: int = 4000) -> str:
    """Fetch a page and return cleaned text content."""
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        # Try job-specific containers first
        for selector in [
            ".show-more-less-html__markup",
            ".description__text",
            "#jobDescriptionText",
            ".jobDescriptionContent",
            "[data-testid='description']",
            "article",
            "main",
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text[:max_chars]
        # Fallback: full body text
        return soup.get_text(separator="\n", strip=True)[:max_chars]
    except Exception as e:
        logger.warning(f"Page fetch error {url}: {e}")
        return ""
