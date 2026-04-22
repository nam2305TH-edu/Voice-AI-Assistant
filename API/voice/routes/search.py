from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel

router = APIRouter(tags=["Search"])

# Singleton instance của TmeBrain
_brain_instance = None

def get_brain():
    global _brain_instance
    if _brain_instance is None:
        from API.Search_OpenAI.brain import TmeBrain
        _brain_instance = TmeBrain()
    return _brain_instance


class SearchRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


@router.post("/search")
async def search_api(request: SearchRequest):
    """
    Nhận text, tìm kiếm và trả lời với ngữ cảnh session
    """
    try:
        brain = get_brain()
        result = await brain.ask_tme(request.query, request.session_id)
        return {
            "status": "success", 
            "answer": result["answer"],
            "session_id": result["session_id"]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/search")
async def search_api_get(q: str, session_id: Optional[str] = None):
    """GET version cho tiện test - hỗ trợ session"""
    try:
        brain = get_brain()
        result = await brain.ask_tme(q, session_id)
        return {
            "status": "success", 
            "answer": result["answer"],
            "session_id": result["session_id"]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/search/session/{session_id}")
async def clear_session(session_id: str):
    """Xóa ngữ cảnh của một session"""
    try:
        brain = get_brain()
        brain.database.clear_session(session_id)
        return {"status": "success", "message": f"Session {session_id} cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/search/session/{session_id}")
async def get_session_info(session_id: str):
    """Lấy thông tin ngữ cảnh của session"""
    try:
        brain = get_brain()
        session = brain.database.get_session(session_id)
        if session:
            return {
                "status": "success",
                "session": session.to_dict()
            }
        return {"status": "not_found", "message": "Session không tồn tại"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==================== CACHE MANAGEMENT ====================

@router.delete("/cache")
async def clear_all_cache():
    """Xóa toàn bộ cache"""
    try:
        brain = get_brain()
        deleted = brain.database.clear_all_cache()
        return {"status": "success", "message": f"Cleared {deleted} cache entries"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/cache/expired")
async def clear_expired_cache():
    """Xóa cache quá 10 phút"""
    try:
        brain = get_brain()
        deleted = brain.database.clear_expired_cache()
        return {"status": "success", "message": f"Cleared {deleted} expired cache entries"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==================== NEWS UPDATE ====================

@router.post("/news/refresh")
async def trigger_news_refresh():
    """Manual trigger cập nhật tin tức"""
    try:
        from API.Search_OpenAI.news_service import NewsScraperService
        import time as t
        
        brain = get_brain()
        
        # Scrape news
        async with NewsScraperService() as scraper:
            articles = await scraper.fetch_all_news(max_per_source=5)
        
        if not articles:
            return {"status": "warning", "message": "No articles fetched"}
        
        # Update vector store
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
        
        brain.add_to_vectorstore(texts, metadatas)
        
        # Clear cache sau khi update
        brain.database.clear_all_cache()
        
        return {
            "status": "success", 
            "message": f"Updated {len(articles)} articles and cleared cache"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
