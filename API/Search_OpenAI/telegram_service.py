import os
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional
from functools import wraps
import traceback
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

_last_sent = {}
MIN_INTERVAL_SECONDS = 60 

class TelegramNotifier:
    
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

        
    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Gửi tin nhắn đến Telegram"""
        if not self.enabled:
            print("[Telegram] Not configured, skipping notification")
            return False
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        print(f"[Telegram] ✓ Notification sent")
                        return True
                    else:
                        print(f"[Telegram] ✗ Failed: {response.status}")
                        return False
        except Exception as e:
            print(f"[Telegram] ✗ Error: {e}")
            return False
    
    def send_message_sync(self, message: str) -> bool:
        """Sync version của send_message"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Nếu đang trong async context
                asyncio.create_task(self.send_message(message))
                return True
            else:
                return loop.run_until_complete(self.send_message(message))
        except RuntimeError:
            # Không có event loop
            return asyncio.run(self.send_message(message))
    
    async def send_error(self, error: Exception, context: str = "", 
                         include_traceback: bool = True) -> bool:
        """Gửi thông báo lỗi"""
        # Rate limiting
        error_key = f"{type(error).__name__}:{str(error)[:50]}"
        now = datetime.now().timestamp()
        
        if error_key in _last_sent:
            if now - _last_sent[error_key] < MIN_INTERVAL_SECONDS:
                print(f"[Telegram] Skipping duplicate error (rate limited)")
                return False
        
        _last_sent[error_key] = now
        
        # Build message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f""" <b>TME Brain Error</b>

             <b>Time:</b> {timestamp}
             <b>Context:</b> {context or 'Unknown'}
             <b>Error:</b> {type(error).__name__}
             <b>Message:</b> {str(error)[:500]}
            """
        
        if include_traceback:
            tb = traceback.format_exc()
            if tb and tb != "NoneType: None\n":
                # Truncate traceback nếu quá dài
                if len(tb) > 500:
                    tb = tb[:500] + "\n..."
                message += f"\n<pre>{tb}</pre>"
        
        return await self.send_message(message)
    
    async def send_warning(self, title: str, details: str) -> bool:
        """Gửi cảnh báo"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f""" <b>TME Brain Warning</b>

             <b>Time:</b> {timestamp}
             <b>Title:</b> {title}
             <b>Details:</b>
            {details}
            """
        return await self.send_message(message)
    
    async def send_info(self, title: str, details: str) -> bool:
        """Gửi thông tin"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""<b>TME Brain Info</b>

             <b>Time:</b> {timestamp}
             <b>Title:</b> {title}
             <b>Details:</b>
            {details}
            """
        return await self.send_message(message)
    
    async def send_data_cleanup_report(self, deleted_count: int, 
                                        freed_mb: float, 
                                        current_size_mb: float) -> bool:
        """Gửi báo cáo dọn dẹp data"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"""🧹 <b>TME Data Cleanup Report</b>

             <b>Time:</b> {timestamp}
             <b>Deleted:</b> {deleted_count} records
             <b>Freed:</b> {freed_mb:.2f} MB
             <b>Current Size:</b> {current_size_mb:.2f} MB
"""
        return await self.send_message(message)


# Singleton instance
_notifier = None

def get_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
def notify_on_error(context: str = ""):
    """Decorator để tự động gửi thông báo khi có lỗi"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                notifier = get_notifier()
                await notifier.send_error(e, context or func.__name__)
                raise
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                notifier = get_notifier()
                notifier.send_message_sync(
                    f" Error in {context or func.__name__}: {str(e)[:200]}"
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
