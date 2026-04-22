import asyncio
import schedule
import time
import json
import os
from datetime import datetime
from typing import Optional

# Kafka imports
try:
    from kafka import KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    print("⚠️ Kafka not installed. Run: pip install kafka-python")

from API.Search_OpenAI.database import DatabaseManager
from API.Search_OpenAI.brain import TmeBrain
from API.Search_OpenAI.telegram_service import get_notifier

# Config
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
MORNING_UPDATE_HOUR = int(os.getenv("MORNING_UPDATE_HOUR", "7"))  # 7:00 AM
CACHE_CLEANUP_INTERVAL_MINUTES = int(os.getenv("CACHE_CLEANUP_INTERVAL", "5"))


class TmeScheduler:
    def __init__(self):
        self.database = DatabaseManager()
        self.notifier = get_notifier()
        self.producer: Optional[KafkaProducer] = None
        self.brain: Optional[TmeBrain] = None
        self.running = False
        
    def setup_kafka(self):
        """Khởi tạo Kafka producer"""
        if not KAFKA_AVAILABLE:
            print("⚠️ Kafka not available")
            return False
            
        try:
            self.producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
            )
            print(f" Kafka Producer connected to {KAFKA_BOOTSTRAP_SERVERS}")
            return True
        except Exception as e:
            print(f" Kafka connection failed: {e}")
            return False
    
    def cleanup_expired_cache(self):
        """Xóa cache quá 10 phút"""
        try:
            deleted = self.database.clear_expired_cache()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] Cache cleanup: {deleted} entries removed")
        except Exception as e:
            print(f" Cache cleanup error: {e}")
    
    def send_kafka_news_request(self):
        """Gửi request cập nhật tin tức qua Kafka"""
        if not self.producer:
            print("⚠️ Kafka producer not available, trying direct update...")
            self.direct_news_update()
            return
            
        try:
            message = {
                "action": "morning_refresh",
                "timestamp": datetime.now().isoformat(),
                "request_id": f"morning_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            }
            
            self.producer.send("tme_news_requests", value=message)
            self.producer.flush()
            
            print(f" [{datetime.now().strftime('%H:%M:%S')}] Sent morning news update request to Kafka")
            
            # Notify qua Telegram
            asyncio.create_task(self.notifier.send_message("🌅 Morning news update triggered via Kafka"))
            
        except Exception as e:
            print(f" Kafka send error: {e}")
            # Fallback: Direct update
            self.direct_news_update()
    
    def direct_news_update(self):
        """Cập nhật tin tức trực tiếp (không qua Kafka)"""
        try:
            from API.Search_OpenAI.news_service import NewsScraperService
            
            async def fetch_and_update():
                print(f" [{datetime.now().strftime('%H:%M:%S')}] Starting direct news update...")
                
                # Scrape news
                async with NewsScraperService() as scraper:
                    articles = await scraper.fetch_all_news(max_per_source=10)
                
                if not articles:
                    print(" No articles fetched")
                    return
                
                # Update brain vector store
                if self.brain is None:
                    self.brain = TmeBrain()
                
                import time as t
                texts = []
                metadatas = []
                current_time = t.time()
                
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
                
                self.brain.add_to_vectorstore(texts, metadatas)
                print(f" Updated {len(texts)} articles to Vector DB")
                
                # Clear old cache after update
                # self.database.clear_all_cache()
                
                # Notify
                await self.notifier.send_message(f" Morning update: {len(articles)} articles added")
            
            asyncio.run(fetch_and_update())
            
        except Exception as e:
            print(f" Direct update error: {e}")
    
    def morning_update(self):
        """Task chạy mỗi sáng"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*50}")
        print(f" [{timestamp}] MORNING UPDATE STARTED")
        print(f"{'='*50}")
        
        # 1. Clear all cache
        self.database.clear_all_cache()
        
        # 2. Send news update request
        self.send_kafka_news_request()
        
        print(f"{'='*50}\n")
    
    def start(self):
        """Bắt đầu scheduler"""
        print(f"\n TME Scheduler Started")
        print(f"   - Morning update: {MORNING_UPDATE_HOUR}:00 AM")
        print(f"   - Cache cleanup: Every {CACHE_CLEANUP_INTERVAL_MINUTES} minutes")
        print(f"   - Cache timeout: 10 minutes")
        print(f"{'='*50}\n")
        
        # Setup Kafka
        self.setup_kafka()
        
        # Schedule morning update
        schedule.every().day.at(f"{MORNING_UPDATE_HOUR:02d}:00").do(self.morning_update)
        
        # Schedule cache cleanup every 5 minutes
        schedule.every(CACHE_CLEANUP_INTERVAL_MINUTES).minutes.do(self.cleanup_expired_cache)
        
        # Run initial cache cleanup
        self.cleanup_expired_cache()
        
        self.running = True
        
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check mỗi phút
    
    def stop(self):
        """Dừng scheduler"""
        self.running = False
        if self.producer:
            self.producer.close()
        if self.brain:
            self.brain.cleanup()
        self.database.close()
        print(" Scheduler stopped")


def run_scheduler():
    """Entry point để chạy scheduler"""
    scheduler = TmeScheduler()
    
    import signal
    def signal_handler(sig, frame):
        print("\n Received shutdown signal...")
        scheduler.stop()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
