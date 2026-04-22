import json
import asyncio
import signal
import sys
import os
from datetime import datetime
from typing import Optional
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

from API.Search_OpenAI.brain import TmeBrain
from API.Search_OpenAI.news_service import NewsScraperService, NewsProcessor, get_news_processor
from API.Search_OpenAI.telegram_service import get_notifier
from API.Search_OpenAI.data_cleanup import get_cleanup_service

# === Cấu hình Kafka Topics (đọc từ ENV) ===
WORKER_ID = os.getenv("WORKER_ID", f"worker-{os.getpid()}")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

KAFKA_CONFIG = {
    "bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS,
    "topics": {
        "voice_tasks": "voice_tasks",           # Nhận câu hỏi từ user
        "brain_results": "brain_results",       # Trả kết quả
        "news_updates": "tme_news_updates",     # Event cập nhật tin tức
        "news_requests": "tme_news_requests",   # Request fetch tin tức mới
    },
    "group_id": "tme_brain_group"
}


class TmeKafkaWorker:
    """Worker xử lý Kafka messages với session support"""
    
    def __init__(self, worker_id: str = None):
        self.worker_id = worker_id or WORKER_ID
        self.brain: Optional[TmeBrain] = None
        self.producer: Optional[KafkaProducer] = None
        self.consumer: Optional[KafkaConsumer] = None
        self.news_processor: Optional[NewsProcessor] = None
        self.notifier = get_notifier()
        self.cleanup_service = get_cleanup_service()
        self.running = False
        self.processed_count = 0
        self.error_count = 0
        
    def setup(self):
        """Khởi tạo các components"""
        print(f"🚀 [{self.worker_id}] Initializing TME Kafka Worker...")
        print(f"   Kafka: {KAFKA_CONFIG['bootstrap_servers']}")
        
        # Khởi tạo Brain
        self.brain = TmeBrain()
        print(f"   [{self.worker_id}] ✓ Brain initialized")
        
        # Khởi tạo News Processor
        self.news_processor = get_news_processor()
        self.news_processor.set_brain(self.brain)
        print(f"   [{self.worker_id}] ✓ News Processor initialized")
        
        # Khởi tạo Kafka Producer
        self.producer = KafkaProducer(
            bootstrap_servers=KAFKA_CONFIG["bootstrap_servers"],
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
        )
        print(f"   [{self.worker_id}] ✓ Kafka Producer connected")
        
        # Khởi tạo Kafka Consumer (lắng nghe nhiều topics)
        self.consumer = KafkaConsumer(
            KAFKA_CONFIG["topics"]["voice_tasks"],
            KAFKA_CONFIG["topics"]["news_requests"],
            bootstrap_servers=KAFKA_CONFIG["bootstrap_servers"],
            group_id=KAFKA_CONFIG["group_id"],
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            auto_offset_reset='latest',
            enable_auto_commit=True,
        )
        print(f"   [{self.worker_id}] ✓ Kafka Consumer connected")
        
        print(f"✅ [{self.worker_id}] TME Kafka Worker ready!")
        
    def cleanup(self):
        """Dọn dẹp resources"""
        print(f"\n [{self.worker_id}] Shutting down (processed {self.processed_count} messages)...")
        self.running = False
        
        if self.brain:
            self.brain.cleanup()
        if self.producer:
            self.producer.close()
        if self.consumer:
            self.consumer.close()
            
        print(f"✅ [{self.worker_id}] Worker shutdown complete")
    
    def send_result(self, topic: str, data: dict):
        """Gửi kết quả về Kafka topic"""
        try:
            # Thêm worker_id vào response
            data["processed_by"] = self.worker_id
            self.producer.send(topic, data)
            self.producer.flush()
        except KafkaError as e:
            print(f"[{self.worker_id}] ❌ Kafka send error: {e}")
    
    async def process_voice_task(self, data: dict):
        """
        Xử lý câu hỏi từ user với session context
        """
        user_id = data.get("user_id", "anonymous")
        query_text = data.get("text", "")
        session_id = data.get("session_id")  # Có thể None nếu là conversation mới
        message_id = data.get("message_id", "N/A")
        
        self.processed_count += 1
        print(f"\n📝 [{self.worker_id}] Processing message #{self.processed_count}")
        print(f"   Message ID: {message_id}")
        print(f"   User: {user_id}")
        print(f"   Query: {query_text[:50]}...")
        
        try:
            # Gọi brain với session support
            result = await self.brain.ask_tme(query_text, session_id)
            
            # Gửi kết quả
            response = {
                "user_id": user_id,
                "message_id": message_id,
                "answer": result["answer"],
                "session_id": result["session_id"],
                "timestamp": datetime.now().isoformat(),
                "status": "success"
            }
            
            self.send_result(KAFKA_CONFIG["topics"]["brain_results"], response)
            print(f"   [{self.worker_id}] ✓ Done! (session: {result['session_id'][:8]}...)")
            
        except Exception as e:
            self.error_count += 1
            
            # Gửi thông báo lỗi về Telegram
            await self._notify_error(e, f"process_voice_task: {query_text[:50]}")
            
            error_response = {
                "user_id": user_id,
                "message_id": message_id,
                "answer": f"Xin lỗi, có lỗi xảy ra: {str(e)}",
                "session_id": session_id or "",
                "timestamp": datetime.now().isoformat(),
                "status": "error"
            }
            self.send_result(KAFKA_CONFIG["topics"]["brain_results"], error_response)
            print(f"   [{self.worker_id}] ❌ Error: {e}")
    
    async def _notify_error(self, error: Exception, context: str = ""):
        """Gửi thông báo lỗi về Telegram"""
        try:
            await self.notifier.send_error(
                error, 
                f"[{self.worker_id}] {context}"
            )
        except Exception as e:
            print(f"   [{self.worker_id}] Failed to send notification: {e}")

    async def process_news_request(self, data: dict):
        """
        Xử lý request fetch tin tức mới
        """
        topic = data.get("topic", "general")
        max_articles = data.get("max_articles", 10)
        
        print(f"\n📰 [{self.worker_id}] Processing news request: topic={topic}")
        
        try:
            async with NewsScraperService() as scraper:
                if topic == "general":
                    articles = await scraper.fetch_all_news(max_per_source=max_articles)
                else:
                    articles = await scraper.fetch_by_topic(topic)
            
            # Lưu vào vector store
            stored_count = await self.news_processor.process_and_store(articles)
            
            # Gửi notification
            self.send_result(KAFKA_CONFIG["topics"]["news_updates"], {
                "event": "news_fetched",
                "topic": topic,
                "count": stored_count,
                "timestamp": datetime.now().isoformat()
            })
            
            print(f"   [{self.worker_id}] ✓ Fetched and stored {stored_count} articles")
            
        except Exception as e:
            self.error_count += 1
            await self._notify_error(e, f"process_news_request: {topic}")
            print(f"   [{self.worker_id}] ❌ News fetch error: {e}")
    
    async def _check_data_cleanup(self):
        """Kiểm tra và cleanup data định kỳ"""
        try:
            if self.cleanup_service.needs_cleanup():
                print(f"\n🧹 [{self.worker_id}] Data cleanup triggered...")
                await self.cleanup_service.check_and_cleanup()
        except Exception as e:
            print(f"   [{self.worker_id}] Cleanup error: {e}")

    async def process_message(self, message):
        """Route message đến handler phù hợp"""
        topic = message.topic
        data = message.value
        
        # Kiểm tra cleanup mỗi 50 messages
        if self.processed_count % 50 == 0:
            await self._check_data_cleanup()
        
        if topic == KAFKA_CONFIG["topics"]["voice_tasks"]:
            await self.process_voice_task(data)
        elif topic == KAFKA_CONFIG["topics"]["news_requests"]:
            await self.process_news_request(data)
        else:
            print(f"⚠️ [{self.worker_id}] Unknown topic: {topic}")
    
    def run(self):
        """Main loop - lắng nghe và xử lý messages"""
        self.setup()
        self.running = True
        
        # Setup signal handlers
        def signal_handler(sig, frame):
            self.cleanup()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        print("\n👂 TME Worker is listening for messages...")
        print("   Press Ctrl+C to stop\n")
        
        # Event loop cho async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            for message in self.consumer:
                if not self.running:
                    break
                    
                try:
                    loop.run_until_complete(self.process_message(message))
                except Exception as e:
                    print(f" Message processing error: {e}")
                    
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()
            self.cleanup()


# === Helper functions để gửi messages ===

def send_voice_query(user_id: str, text: str, session_id: str = None):
    """Helper: Gửi câu hỏi vào Kafka"""
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_CONFIG["bootstrap_servers"],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
    )
    
    message = {
        "user_id": user_id,
        "text": text,
        "session_id": session_id,
        "timestamp": datetime.now().isoformat()
    }
    
    producer.send(KAFKA_CONFIG["topics"]["voice_tasks"], message)
    producer.flush()
    producer.close()
    
    print(f"Sent query to Kafka: {text[:30]}...")


def request_news_update(topic: str = "general", max_articles: int = 10):
    """Helper: Request cập nhật tin tức"""
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_CONFIG["bootstrap_servers"],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode('utf-8')
    )
    
    message = {
        "topic": topic,
        "max_articles": max_articles,
        "timestamp": datetime.now().isoformat()
    }
    
    producer.send(KAFKA_CONFIG["topics"]["news_requests"], message)
    producer.flush()
    producer.close()
    
    print(f"Requested news update: topic={topic}")


# === Entry point ===
if __name__ == "__main__":
    worker = TmeKafkaWorker()
    worker.run()
