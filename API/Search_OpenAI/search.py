import asyncio
import os

from dotenv import load_dotenv
from typing import Union, List, Dict
from langchain_tavily import TavilySearch


class SearchManager:
    def __init__(self):
        load_dotenv()
        TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
        # Sử dụng TavilySearch từ langchain-tavily (updated)
        self.search_tool = TavilySearch(
            max_results=2,  # Giảm để tìm kiếm nhanh hơn
            tavily_api_key=TAVILY_API_KEY
        )
    
    async def search(self, query: str) -> Union[str, Dict, List[Dict]]:
        """Thực hiện tìm kiếm web"""
        try:
            # Giới hạn độ dài query để tránh lỗi 400
            query = query[:500] if len(query) > 500 else query
            
            # Thử dùng async trước
            if hasattr(self.search_tool, "ainvoke"):
                result = await self.search_tool.ainvoke(query)
            elif hasattr(self.search_tool, "arun"):
                result = await self.search_tool.arun(query)
            else:
                # Fallback sync
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, self.search_tool.invoke, query)
            
            return result
        except Exception as e:
            error_msg = str(e)
            print(f"Search error: {error_msg}")
            # Trả về thông báo lỗi rõ ràng hơn
            if "400" in error_msg:
                return "Không thể tìm kiếm với câu hỏi này. Vui lòng thử câu hỏi khác."
            return ""