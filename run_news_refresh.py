import asyncio
import argparse
import schedule
import time
from datetime import datetime
import sys
import os
import sqlite3
from datetime import timedelta

from API.Search_OpenAI.brain import TmeBrain
from API.Search_OpenAI.news_service import NewsScraperService, NewsArticle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def fetch_and_store_news(topic: str = "general", max_articles: int = 10):
    """Fetch tin tức và lưu vào vector store"""
    print(f"\n{'='*60}")
    print(f"TME News Refresh - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # Step 1: Fetch news
    print("\nStep 1: Fetching news from RSS feeds...")
    
    async with NewsScraperService() as scraper:
        if topic == "general":
            articles = await scraper.fetch_all_news(max_per_source=max_articles)
        else:
            articles = await scraper.fetch_by_topic(topic)
    
    print(f"Found {len(articles)} articles")
    
    if not articles:
        print("No articles found, exiting")
        return 0
    
    # Print sample articles
    print("\n   Sample articles:")
    for i, article in enumerate(articles[:3], 1):
        print(f"   {i}. [{article.source}] {article.title[:50]}...")
    
    # Step 2: Store to vector database
    print("\nStep 2: Storing to Vector Database...")
    
    try:
        brain = TmeBrain()
        
        texts = []
        metadatas = []
        current_time = time.time()
        
        for article in articles:
            texts.append(article.to_embedding_text())
            metadatas.append({
                "source": article.source,
                "category": article.category,
                "url": article.url,
                "title": article.title,
                "published_at": article.published_at,
                "type": "news",
                "timestamp": current_time
            })
        
        brain.add_to_vectorstore(texts, metadatas)
        brain.cleanup()
        
        print(f"Stored {len(texts)} articles to ChromaDB")
        
    except Exception as e:
        print(f"  Error storing to vector DB: {e}")
        return 0
    
    # Step 3: Cleanup old cache
    print("\nStep 3: Cleaning up old cache...")
    
    try:
        
        
        conn = sqlite3.connect('./data/tme_mess.db')
        cursor = conn.cursor()
        
        # Xóa cache cũ hơn 7 ngày
        cutoff_date = (datetime.now() - timedelta(days=7)).isoformat()
        cursor.execute(
            "DELETE FROM search_cache WHERE timestamp < ?",
            (cutoff_date,)
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        print(f"Cleaned {deleted} old cache entries")
        
    except Exception as e:
        print(f"   Cleanup warning: {e}")
    
    # Done
    print(f"\n{'='*60}")
    print(f"News refresh completed! Stored {len(articles)} articles")
    print(f"{'='*60}\n")
    
    return len(articles)


def run_refresh(topic: str = "general", max_articles: int = 10):
    """Wrapper để chạy async function"""
    return asyncio.run(fetch_and_store_news(topic, max_articles))


def run_scheduled():
    """Chạy theo lịch - 6:00 sáng mỗi ngày"""
    print("TME News Scheduler Started")
    print("   Scheduled: Every day at 6:00 AM")
    print("   Press Ctrl+C to stop\n")
    
    # Chạy ngay lần đầu
    run_refresh()
    
    # Schedule chạy mỗi ngày lúc 6:00
    schedule.every().day.at("06:00").do(run_refresh)
    
    # Cũng chạy mỗi 6 tiếng để cập nhật tin mới
    schedule.every(6).hours.do(run_refresh)
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check mỗi phút


def main():
    parser = argparse.ArgumentParser(description='TME News Refresh Tool')
    parser.add_argument('--topic', type=str, default='general',
                       help='Topic to fetch (general, thoi-su, the-gioi, kinh-doanh, cong-nghe)')
    parser.add_argument('--max', type=int, default=10,
                       help='Max articles per source')
    parser.add_argument('--schedule', action='store_true',
                       help='Run in scheduled mode (6:00 AM daily)')
    
    args = parser.parse_args()
    
    if args.schedule:
        run_scheduled()
    else:
        run_refresh(args.topic, args.max)


if __name__ == "__main__":
    main()
