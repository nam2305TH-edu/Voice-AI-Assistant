import asyncio
from API.Search_OpenAI.brain import TmeBrain

_brain_instance = None 

def get_brain_instance() -> TmeBrain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = TmeBrain()
    return _brain_instance

async def search_answer(user_query: str, session_id: str = None) -> dict:
    brain = get_brain_instance()
    return await brain.ask_tme(user_query, session_id)

async def main():
    brain = TmeBrain()
    session_id = None 
    try:
        for i in range(20):
            query = input("Hỏi: ")
            result = await brain.ask_tme(query, session_id)
            session_id = result["session_id"]  
            print("Trả lời:", result["answer"])
    finally:
        brain.cleanup()

if __name__ == "__main__":
    asyncio.run(main())  