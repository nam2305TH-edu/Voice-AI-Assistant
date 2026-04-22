"""
News Scraper Service - Cào tin tức từ các nguồn tin Việt Nam
"""
import asyncio
import aiohttp
import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import json

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
    print("Warning: BeautifulSoup not installed. Run: pip install beautifulsoup4")


@dataclass
class NewsArticle:
    title: str
    summary: str
    url: str
    source: str
    category: str
    published_at: str
    content: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_embedding_text(self) -> str:
        """Tạo text để embedding vào vector store"""
        return f"""
        Tiêu đề: {self.title}
        Nguồn: {self.source}
        Danh mục: {self.category}
        Ngày: {self.published_at}
        Tóm tắt: {self.summary}
        {f'Nội dung: {self.content[:500]}...' if self.content else ''}
        """.strip()


class NewsScraperService:
    """Service cào tin tức từ các nguồn"""
    
    # Các nguồn tin RSS/API
    NEWS_SOURCES = {
        "vnexpress": {
            "rss": "https://vnexpress.net/rss/tin-moi-nhat.rss",
            "categories": {
                "thoi-su": "https://vnexpress.net/rss/thoi-su.rss",
                "the-gioi": "https://vnexpress.net/rss/the-gioi.rss",
                "kinh-doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
                "cong-nghe": "https://vnexpress.net/rss/khoa-hoc.rss",
            }
        },
        "tuoitre": {
            "rss": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
            "categories": {
                "thoi-su": "https://tuoitre.vn/rss/thoi-su.rss",
                "the-gioi": "https://tuoitre.vn/rss/the-gioi.rss",
                "kinh-doanh": "https://tuoitre.vn/rss/kinh-doanh.rss",
            }
        },
        "thanhnien": {
            "rss": "https://thanhnien.vn/rss/home.rss",
        }
    }
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "TmeBrain NewsBot/1.0"},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    async def fetch_rss(self, url: str) -> str:
        """Fetch RSS feed content"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                print(f"RSS fetch failed: {url} - Status {response.status}")
                return ""
        except Exception as e:
            print(f"RSS fetch error: {url} - {e}")
            return ""
    
    def parse_rss(self, rss_content: str, source: str, category: str = "general") -> List[NewsArticle]:
        """Parse RSS XML thành danh sách NewsArticle"""
        if not BeautifulSoup or not rss_content:
            return []
        
        articles = []
        try:
            soup = BeautifulSoup(rss_content, 'xml')
            items = soup.find_all('item')
            
            for item in items[:10]:  # Lấy 10 tin mới nhất
                title = item.find('title')
                description = item.find('description')
                link = item.find('link')
                pub_date = item.find('pubDate')
                
                if title and link:
                    # Clean HTML từ description
                    summary = ""
                    if description:
                        desc_soup = BeautifulSoup(description.text, 'html.parser')
                        summary = desc_soup.get_text()[:300]
                    
                    articles.append(NewsArticle(
                        title=title.text.strip(),
                        summary=summary.strip(),
                        url=link.text.strip(),
                        source=source,
                        category=category,
                        published_at=pub_date.text if pub_date else datetime.now().isoformat()
                    ))
        except Exception as e:
            print(f"RSS parse error: {e}")
        
        return articles
    
    async def fetch_all_news(self, max_per_source: int = 10) -> List[NewsArticle]:
        """Fetch tin tức từ tất cả các nguồn"""
        all_articles = []
        
        for source_name, source_config in self.NEWS_SOURCES.items():
            # Fetch RSS chính
            rss_url = source_config.get("rss")
            if rss_url:
                content = await self.fetch_rss(rss_url)
                articles = self.parse_rss(content, source_name, "general")
                all_articles.extend(articles[:max_per_source])
            
            # Fetch theo category
            categories = source_config.get("categories", {})
            for cat_name, cat_url in categories.items():
                content = await self.fetch_rss(cat_url)
                articles = self.parse_rss(content, source_name, cat_name)
                all_articles.extend(articles[:5])  # 5 tin mỗi category
                
            # Tránh spam request
            await asyncio.sleep(0.5)
        
        # Loại bỏ duplicate theo URL
        seen_urls = set()
        unique_articles = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)
        
        return unique_articles
    
    async def fetch_by_topic(self, topic: str) -> List[NewsArticle]:
        """Fetch tin tức theo chủ đề cụ thể"""
        topic_mapping = {
            "thời sự": "thoi-su",
            "thế giới": "the-gioi", 
            "kinh doanh": "kinh-doanh",
            "công nghệ": "cong-nghe",
            "tài chính": "kinh-doanh",
        }
        
        category = topic_mapping.get(topic.lower(), "general")
        all_articles = []
        
        for source_name, source_config in self.NEWS_SOURCES.items():
            categories = source_config.get("categories", {})
            if category in categories:
                content = await self.fetch_rss(categories[category])
                articles = self.parse_rss(content, source_name, category)
                all_articles.extend(articles[:5])
        
        return all_articles


class NewsProcessor:
    """Xử lý và lưu tin tức vào Vector Database"""
    
    def __init__(self, brain=None):
        self.brain = brain
    
    def set_brain(self, brain):
        self.brain = brain
    
    async def process_and_store(self, articles: List[NewsArticle]) -> int:
        """Xử lý và lưu tin vào vector store"""
        if not self.brain or not articles:
            return 0
        
        texts = []
        metadatas = []
        
        for article in articles:
            texts.append(article.to_embedding_text())
            metadatas.append({
                "source": article.source,
                "category": article.category,
                "url": article.url,
                "title": article.title,
                "published_at": article.published_at,
                "type": "news"
            })
        
        try:
            self.brain.add_to_vectorstore(texts, metadatas)
            print(f"Stored {len(texts)} articles to vector database")
            return len(texts)
        except Exception as e:
            print(f"Error storing articles: {e}")
            return 0
    
    def get_news_summary(self, articles: List[NewsArticle], max_items: int = 5) -> str:
        """Tạo tóm tắt tin tức cho chatbot"""
        if not articles:
            return "Không có tin tức mới."
        
        summary_parts = [f"📰 **Tin tức mới nhất ({datetime.now().strftime('%d/%m/%Y')}):**\n"]
        
        for i, article in enumerate(articles[:max_items], 1):
            summary_parts.append(
                f"{i}. [{article.source.upper()}] {article.title}\n"
                f"   {article.summary[:100]}...\n"
            )
        
        return "\n".join(summary_parts)


# Singleton instance
_news_service = None
_news_processor = None

def get_news_service() -> NewsScraperService:
    global _news_service
    if _news_service is None:
        _news_service = NewsScraperService()
    return _news_service

def get_news_processor() -> NewsProcessor:
    global _news_processor
    if _news_processor is None:
        _news_processor = NewsProcessor()
    return _news_processor


# === CLI Test ===
async def main():
    """Test scraping"""
    async with NewsScraperService() as scraper:
        print("Fetching news...")
        articles = await scraper.fetch_all_news(max_per_source=5)
        print(f"Found {len(articles)} articles")
        
        for article in articles[:5]:
            print(f"\n- {article.title}")
            print(f"  Source: {article.source} | Category: {article.category}")
            print(f"  URL: {article.url}")

if __name__ == "__main__":
    asyncio.run(main())
