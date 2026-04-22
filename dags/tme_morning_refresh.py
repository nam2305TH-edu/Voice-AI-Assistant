from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
import os
import sys
from API.Search_OpenAI.brain import TmeBrain
from API.Search_OpenAI.news_service import NewsArticle
from langchain_core.documents import Document
import time
from kafka import KafkaProducer
import json
import asyncio
from API.Search_OpenAI.news_service import NewsScraperService
from datetime import datetime, timedelta


PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_PATH)

default_args = {
    'owner': 'tme_admin',
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
    'email_on_retry': False,
}


def scrape_top_news(**context):


    
    async def fetch():
        async with NewsScraperService() as scraper:
            articles = await scraper.fetch_all_news(max_per_source=10)
            return [article.to_dict() for article in articles]
    
  
    articles_data = asyncio.run(fetch())
    
    # Lưu vào XCom
    context['ti'].xcom_push(key='news_articles', value=articles_data)
    
    print(f" Scraped {len(articles_data)} articles")
    return len(articles_data)


def update_vector_db(**context):
    """
    Task 2: Cập nhật embeddings vào ChromaDB
    Lấy dữ liệu từ XCom của task trước
    """
    
    
    # Lấy articles từ XCom
    articles_data = context['ti'].xcom_pull(key='news_articles', task_ids='scrape_news')
    
    if not articles_data:
        print(" No articles to process")
        return 0
    
    # Convert dict back to NewsArticle
    articles = [NewsArticle(**data) for data in articles_data]
    
    # Khởi tạo brain và update vectorstore
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
    
    # Thêm vào vectorstore
    brain.add_to_vectorstore(texts, metadatas)
    
    # Cleanup
    brain.cleanup()
    
    print(f" Updated {len(texts)} articles to Vector DB")
    return len(texts)


def notify_kafka(**context):
    """
     Gửi thông báo qua Kafka rằng tin tức đã được cập nhật
    """
    
    
    try:
        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # Lấy số lượng articles
        articles_count = context['ti'].xcom_pull(task_ids='update_db')
        
        # Gửi event thông báo
        producer.send("tme_news_updates", {
            "event": "news_refreshed",
            "count": articles_count,
            "timestamp": datetime.now().isoformat(),
            "message": f"Đã cập nhật {articles_count} tin tức mới"
        })
        producer.flush()
        producer.close()
        
        print(f" Sent notification to Kafka: {articles_count} articles updated")
    except Exception as e:
        print(f" Kafka notification failed (non-critical): {e}")


def cleanup_old_news(**context):
    """
    Task 4: Dọn dẹp tin tức cũ (> 7 ngày)
    """
    import sqlite3

    
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
        
        print(f" Cleaned up {deleted} old cache entries")
        return deleted
    except Exception as e:
        print(f"⚠️ Cleanup failed: {e}")
        return 0



with DAG(
    dag_id='tme_daily_news_refresh',
    default_args=default_args,
    description='Tự động cập nhật tin tức mỗi sáng cho TME Chatbot',
    start_date=datetime(2024, 1, 1),
    schedule_interval='0 6 * * *',  # Chạy lúc 6:00 sáng mỗi ngày
    catchup=False,
    tags=['tme', 'news', 'chatbot'],
) as dag:
    
    # Task 1: Cào tin tức
    task_scrape_news = PythonOperator(
        task_id='scrape_news',
        python_callable=scrape_top_news,
        provide_context=True,
    )
    
    # Task 2: Update Vector DB
    task_update_db = PythonOperator(
        task_id='update_db',
        python_callable=update_vector_db,
        provide_context=True,
    )
    
    # Task 3: Thông báo qua Kafka
    task_notify = PythonOperator(
        task_id='notify_kafka',
        python_callable=notify_kafka,
        provide_context=True,
    )
    
    # Task 4: Dọn dẹp dữ liệu cũ
    task_cleanup = PythonOperator(
        task_id='cleanup_old_news',
        python_callable=cleanup_old_news,
        provide_context=True,
    )
    
    # Task dependencies
    # scrape_news -> update_db -> [notify_kafka, cleanup_old_news]
    task_scrape_news >> task_update_db >> [task_notify, task_cleanup]


# === Standalone Execution (không cần Airflow) ===
def run_morning_refresh():
    """
    Chạy refresh tin tức mà không cần Airflow
    Có thể gọi từ cron job hoặc scheduler khác
    """
    
    print("🌅 Starting TME Morning News Refresh...")
    print("=" * 50)
    
    # Step 1: Scrape
    print("\n📰 Step 1: Scraping news...")
    context = {'ti': MockXCom()}
    scrape_top_news(**context)
    
    # Step 2: Update DB
    print("\n💾 Step 2: Updating Vector DB...")
    update_vector_db(**context)
    
    # Step 3: Notify
    print("\n📡 Step 3: Sending Kafka notification...")
    notify_kafka(**context)
    
    # Step 4: Cleanup
    print("\n🧹 Step 4: Cleaning up old data...")
    cleanup_old_news(**context)
    
    print("\n" + "=" * 50)
    print("✅ Morning refresh completed!")


class MockXCom:
    """Mock XCom cho standalone execution"""
    def __init__(self):
        self.data = {}
    
    def xcom_push(self, key, value):
        self.data[key] = value
    
    def xcom_pull(self, key=None, task_ids=None):
        if key:
            return self.data.get(key)
        return self.data.get('news_articles')


if __name__ == "__main__":
    run_morning_refresh()

