"""
local_scrape.py
這是一個獨立的腳本，讓你能在「本機電腦」上跑爬蟲，
避開雲端伺服器容易被 LinkedIn 擋 IP 的問題。

它會：
1. 使用你本機的網路去爬 LinkedIn。
2. 用本機的 GROQ_API_KEY 做 AI 分析。
3. 直接連線寫入 Render 上的 PostgreSQL DB。

使用前請確認你的 .env 檔案裡有設定：
- GROQ_API_KEY
- DATABASE_URL (請使用 Render 的 External URL，例如 postgresql://...frankfurt-postgres.render.com/...)
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LocalScraper")

def main():
    db_url = os.environ.get("DATABASE_URL", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")

    if not db_url:
        logger.error("❌ 找不到 DATABASE_URL！請在 .env 中設定 Render 的 External Database URL。")
        sys.exit(1)
        
    if "internal" in db_url or "@dpg-" in db_url and "render.com" not in db_url:
        logger.error("❌ 你的 DATABASE_URL 似乎是 Internal URL！本機連線必須使用 External URL (有 frankfurt-postgres.render.com 結尾的那個)。")
        sys.exit(1)

    if not groq_key:
        logger.error("❌ 找不到 GROQ_API_KEY！請在 .env 中設定。")
        sys.exit(1)

    logger.info("🚀 啟動本機爬蟲任務...")
    
    # Import here to ensure env vars are loaded first
    from app import run_scrape_pipeline
    
    try:
        run_scrape_pipeline()
        logger.info("✅ 本機爬蟲任務完成！資料已同步至雲端資料庫。")
    except Exception as e:
        logger.error(f"❌ 執行過程中發生錯誤: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
