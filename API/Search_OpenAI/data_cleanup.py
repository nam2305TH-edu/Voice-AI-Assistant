import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Optional
from dataclasses import dataclass

from API.Search_OpenAI.telegram_service import get_notifier

# Config
DATA_DIR = os.getenv("DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "tme_mess.db")
MAX_SIZE_MB = float(os.getenv("MAX_DATA_SIZE_MB", "1024"))  # 1GB default
CLEANUP_DAYS = int(os.getenv("CLEANUP_DAYS", "30"))  # Xóa data > 30 ngày


@dataclass
class CleanupResult:
    """Kết quả của việc cleanup"""
    deleted_conversations: int
    deleted_cache: int
    deleted_sessions: int
    size_before_mb: float
    size_after_mb: float
    freed_mb: float


class DataCleanupService:
    """Service dọn dẹp data tự động"""
    
    def __init__(self, db_path: str = None, max_size_mb: float = None):
        self.db_path = db_path or DB_PATH
        self.max_size_mb = max_size_mb or MAX_SIZE_MB
        self.notifier = get_notifier()
    
    def get_db_size_mb(self) -> float:
        """Lấy dung lượng database hiện tại (MB)"""
        try:
            if os.path.exists(self.db_path):
                size_bytes = os.path.getsize(self.db_path)
                return size_bytes / (1024 * 1024)
            return 0.0
        except Exception as e:
            print(f"Error getting DB size: {e}")
            return 0.0
    
    def get_data_dir_size_mb(self) -> float:
        """Lấy tổng dung lượng thư mục data (MB)"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(DATA_DIR):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
            return total_size / (1024 * 1024)
        except Exception as e:
            print(f"Error getting data dir size: {e}")
            return 0.0
    
    def needs_cleanup(self) -> bool:
        """Kiểm tra có cần cleanup không"""
        current_size = self.get_data_dir_size_mb()
        return current_size > self.max_size_mb
    
    def cleanup_old_data(self, days: int = None) -> CleanupResult:
        days = days or CLEANUP_DAYS
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        size_before = self.get_data_dir_size_mb()
        
        deleted_conversations = 0
        deleted_cache = 0
        deleted_sessions = 0
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. Xóa conversations cũ
            cursor.execute(
                "DELETE FROM conversations WHERE timestamp < ?",
                (cutoff_date,)
            )
            deleted_conversations = cursor.rowcount
            
            # 2. Xóa search cache cũ
            cursor.execute(
                "DELETE FROM search_cache WHERE timestamp < ?",
                (cutoff_date,)
            )
            deleted_cache = cursor.rowcount
            
            # 3. Xóa sessions cũ (không hoạt động > 30 ngày)
            cursor.execute(
                "DELETE FROM session_context WHERE updated_at < ?",
                (cutoff_date,)
            )
            deleted_sessions = cursor.rowcount
            
            conn.commit()
            
            # 4. Vacuum để giải phóng dung lượng thực sự
            cursor.execute("VACUUM")
            
            conn.close()
            
        except Exception as e:
            print(f"Cleanup error: {e}")
            # Gửi thông báo lỗi
            asyncio.create_task(
                self.notifier.send_error(e, "DataCleanupService.cleanup_old_data")
            )
        
        size_after = self.get_data_dir_size_mb()
        freed = size_before - size_after
        
        result = CleanupResult(
            deleted_conversations=deleted_conversations,
            deleted_cache=deleted_cache,
            deleted_sessions=deleted_sessions,
            size_before_mb=size_before,
            size_after_mb=size_after,
            freed_mb=max(0, freed)
        )
        
        return result
    
    async def check_and_cleanup(self) -> Optional[CleanupResult]:
        """
        Kiểm tra và cleanup nếu cần
        Gửi thông báo về Telegram
        """
        current_size = self.get_data_dir_size_mb()
        
        print(f"📊 Current data size: {current_size:.2f} MB / {self.max_size_mb:.2f} MB")
        
        if current_size > self.max_size_mb:
            print(f"⚠️ Data size exceeds limit! Starting cleanup...")
            
            # Gửi cảnh báo trước khi cleanup
            await self.notifier.send_warning(
                "Data Size Exceeded",
                f"Current size: {current_size:.2f} MB\n"
                f"Limit: {self.max_size_mb:.2f} MB\n"
                f"Starting cleanup of data older than {CLEANUP_DAYS} days..."
            )
            
            # Thực hiện cleanup
            result = self.cleanup_old_data()
            
            # Gửi báo cáo
            total_deleted = (result.deleted_conversations + 
                           result.deleted_cache + 
                           result.deleted_sessions)
            
            await self.notifier.send_data_cleanup_report(
                deleted_count=total_deleted,
                freed_mb=result.freed_mb,
                current_size_mb=result.size_after_mb
            )
            
            print(f"✅ Cleanup completed!")
            print(f"   Deleted: {total_deleted} records")
            print(f"   Freed: {result.freed_mb:.2f} MB")
            print(f"   Current size: {result.size_after_mb:.2f} MB")
            
            return result
        else:
            print(f"✓ Data size OK, no cleanup needed")
            return None
    
    def get_stats(self) -> dict:
        """Lấy thống kê data hiện tại"""
        stats = {
            "db_size_mb": self.get_db_size_mb(),
            "data_dir_size_mb": self.get_data_dir_size_mb(),
            "max_size_mb": self.max_size_mb,
            "needs_cleanup": self.needs_cleanup(),
        }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Count records
            cursor.execute("SELECT COUNT(*) FROM conversations")
            stats["conversations_count"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM search_cache")
            stats["cache_count"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM session_context")
            stats["sessions_count"] = cursor.fetchone()[0]
            
            # Oldest record
            cursor.execute("SELECT MIN(timestamp) FROM conversations")
            result = cursor.fetchone()
            stats["oldest_conversation"] = result[0] if result else None
            
            conn.close()
            
        except Exception as e:
            print(f"Error getting stats: {e}")
        
        return stats


# Singleton
_cleanup_service = None

def get_cleanup_service() -> DataCleanupService:
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = DataCleanupService()
    return _cleanup_service


# === Scheduled Task ===
async def run_scheduled_cleanup():
    """Chạy cleanup theo lịch (mỗi ngày)"""
    service = get_cleanup_service()
    
    while True:
        print(f"\n[{datetime.now()}] Running scheduled data check...")
        await service.check_and_cleanup()
        
        # Chờ 24 giờ
        await asyncio.sleep(24 * 60 * 60)


# === CLI ===
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="TME Data Cleanup Service")
    parser.add_argument("--check", action="store_true", help="Check data size")
    parser.add_argument("--cleanup", action="store_true", help="Force cleanup")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--days", type=int, default=30, help="Days to keep (default: 30)")
    
    args = parser.parse_args()
    
    service = DataCleanupService()
    
    if args.stats:
        print("\n📊 Data Statistics:")
        print("=" * 40)
        stats = service.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print("=" * 40)
        
    elif args.cleanup:
        print(f"\n Force cleanup (data older than {args.days} days)...")
        result = service.cleanup_old_data(args.days)
        print(f"\n Cleanup Results:")
        print(f"   Conversations deleted: {result.deleted_conversations}")
        print(f"   Cache entries deleted: {result.deleted_cache}")
        print(f"   Sessions deleted: {result.deleted_sessions}")
        print(f"   Size before: {result.size_before_mb:.2f} MB")
        print(f"   Size after: {result.size_after_mb:.2f} MB")
        print(f"   Freed: {result.freed_mb:.2f} MB")
        
    elif args.check:
        print("\n Checking data size...")
        asyncio.run(service.check_and_cleanup())
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
