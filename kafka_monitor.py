import time
import os
import sys
from datetime import datetime
from typing import Dict, List
from collections import deque

try:
    from kafka import KafkaConsumer, KafkaAdminClient
    from kafka.admin import ConfigResource, ConfigResourceType
    from kafka.structs import TopicPartition
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    print("⚠️ kafka-python not installed. Run: pip install kafka-python")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

TOPICS_TO_MONITOR = [
    "voice_tasks",
    "brain_results",
    "tme_news_updates",
    "tme_news_requests"
]


class KafkaQueueMonitor:
    """Monitor Kafka queue sizes và consumer lag"""
    
    def __init__(self, bootstrap_servers: str = KAFKA_BOOTSTRAP_SERVERS):
        if not KAFKA_AVAILABLE:
            raise RuntimeError("kafka-python not installed")
        
        self.bootstrap_servers = bootstrap_servers
        self.admin_client = None
        self.consumers: Dict[str, KafkaConsumer] = {}
        self.history: Dict[str, deque] = {}
        self.max_history = 60  # Lưu 60 lần đo gần nhất
        
        for topic in TOPICS_TO_MONITOR:
            self.history[topic] = deque(maxlen=self.max_history)
    
    def connect(self):
        """Kết nối Kafka"""
        try:
            print(f"🔌 Connecting to Kafka: {self.bootstrap_servers}...")
            
            # Admin client để lấy metadata
            self.admin_client = KafkaAdminClient(
                bootstrap_servers=self.bootstrap_servers
            )
            
            # Consumer cho mỗi topic để monitor
            for topic in TOPICS_TO_MONITOR:
                try:
                    consumer = KafkaConsumer(
                        topic,
                        bootstrap_servers=self.bootstrap_servers,
                        group_id=f"monitor_{topic}",
                        auto_offset_reset='latest',
                        enable_auto_commit=False
                    )
                    self.consumers[topic] = consumer
                    print(f"   ✓ Connected to topic: {topic}")
                except Exception as e:
                    print(f"   ⚠️  Could not connect to {topic}: {e}")
            
            print("✅ Kafka monitor connected\n")
            return True
            
        except Exception as e:
            print(f"❌ Failed to connect to Kafka: {e}")
            return False
    
    def get_topic_lag(self, topic: str) -> Dict[int, int]:
        """
        Tính consumer lag cho topic
        Returns: {partition_id: lag_count}
        """
        if topic not in self.consumers:
            return {}
        
        consumer = self.consumers[topic]
        lags = {}
        
        try:
            # Lấy partitions
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                return {}
            
            for partition_id in partitions:
                tp = TopicPartition(topic, partition_id)
                
                # Current offset của consumer
                committed = consumer.committed(tp)
                current_offset = committed if committed is not None else 0
                
                # Latest offset (end of partition)
                consumer.seek_to_end(tp)
                end_offset = consumer.position(tp)
                
                # Lag = end - current
                lag = end_offset - current_offset
                lags[partition_id] = lag
            
        except Exception as e:
            print(f"⚠️  Error getting lag for {topic}: {e}")
        
        return lags
    
    def get_queue_size(self, topic: str) -> int:
        """Lấy tổng số messages chưa consume"""
        lags = self.get_topic_lag(topic)
        return sum(lags.values())
    
    def monitor_once(self) -> Dict[str, any]:
        """Thu thập metrics một lần"""
        timestamp = datetime.now()
        metrics = {
            "timestamp": timestamp.isoformat(),
            "topics": {}
        }
        
        for topic in TOPICS_TO_MONITOR:
            queue_size = self.get_queue_size(topic)
            lags = self.get_topic_lag(topic)
            
            metrics["topics"][topic] = {
                "queue_size": queue_size,
                "partitions": lags,
                "num_partitions": len(lags)
            }
            
            # Lưu vào history
            self.history[topic].append({
                "time": timestamp,
                "size": queue_size
            })
        
        return metrics
    
    def print_metrics(self, metrics: Dict):
        """In metrics ra console"""
        timestamp = metrics["timestamp"]
        
        print(f"\n{'='*70}")
        print(f"📊 KAFKA QUEUE METRICS - {timestamp}")
        print(f"{'='*70}")
        
        total_queue = 0
        
        for topic, data in metrics["topics"].items():
            queue_size = data["queue_size"]
            partitions = data["partitions"]
            total_queue += queue_size
            
            # Status indicator
            if queue_size == 0:
                status = "🟢 EMPTY"
            elif queue_size < 10:
                status = "🟡 LOW"
            elif queue_size < 50:
                status = "🟠 MEDIUM"
            else:
                status = "🔴 HIGH"
            
            print(f"\n📌 {topic}")
            print(f"   Status: {status}")
            print(f"   Queue Size: {queue_size} messages")
            print(f"   Partitions: {data['num_partitions']}")
            
            if partitions and queue_size > 0:
                print(f"   Lag by partition: {partitions}")
        
        print(f"\n{'='*70}")
        print(f"📦 TOTAL QUEUE: {total_queue} messages")
        print(f"{'='*70}")
    
    def print_history_summary(self):
        """In tóm tắt lịch sử"""
        print(f"\n{'='*70}")
        print("📈 QUEUE SIZE HISTORY (Last 60 measurements)")
        print(f"{'='*70}")
        
        for topic, history in self.history.items():
            if not history:
                continue
            
            sizes = [h["size"] for h in history]
            
            avg_size = sum(sizes) / len(sizes)
            max_size = max(sizes)
            min_size = min(sizes)
            current_size = sizes[-1] if sizes else 0
            
            print(f"\n{topic}:")
            print(f"   Current: {current_size}")
            print(f"   Average: {avg_size:.1f}")
            print(f"   Max: {max_size}")
            print(f"   Min: {min_size}")
            
            # Simple text-based graph
            if max_size > 0:
                graph = self._create_simple_graph(sizes, width=50)
                print(f"   Graph: {graph}")
    
    def _create_simple_graph(self, values: List[int], width: int = 50) -> str:
        """Tạo graph đơn giản bằng text"""
        if not values or max(values) == 0:
            return "▁" * min(width, len(values))
        
        max_val = max(values)
        # Chỉ lấy N giá trị cuối
        recent_values = values[-width:]
        
        chars = " ▁▂▃▄▅▆▇█"
        graph = ""
        
        for val in recent_values:
            normalized = val / max_val
            char_idx = int(normalized * (len(chars) - 1))
            graph += chars[char_idx]
        
        return graph
    
    def monitor_loop(self, interval: int = 5, duration: int = None):
        """
        Chạy monitoring loop
        Args:
            interval: Giây giữa mỗi lần check
            duration: Tổng thời gian chạy (None = forever)
        """
        if not self.connect():
            return
        
        print(f"\n🔍 Starting monitoring (interval: {interval}s)")
        print("Press Ctrl+C to stop\n")
        
        start_time = time.time()
        iteration = 0
        
        try:
            while True:
                iteration += 1
                
                # Thu thập metrics
                metrics = self.monitor_once()
                
                # In ra console
                self.print_metrics(metrics)
                
                # Kiểm tra cảnh báo
                self._check_alerts(metrics)
                
                # In history summary mỗi 10 lần
                if iteration % 10 == 0:
                    self.print_history_summary()
                
                # Kiểm tra duration
                if duration and (time.time() - start_time) >= duration:
                    print(f"\n⏱️  Monitoring duration reached ({duration}s)")
                    break
                
                # Chờ interval
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n⏹️  Monitoring stopped by user")
        finally:
            self.cleanup()
    
    def _check_alerts(self, metrics: Dict):
        """Kiểm tra và cảnh báo nếu queue quá cao"""
        for topic, data in metrics["topics"].items():
            queue_size = data["queue_size"]
            
            # Cảnh báo nếu queue > 100
            if queue_size > 100:
                print(f"\n⚠️  ALERT: {topic} has {queue_size} messages in queue!")
                print(f"   Consider scaling workers!")
            
            # Cảnh báo nghiêm trọng nếu queue > 500
            if queue_size > 500:
                print(f"\n🚨 CRITICAL: {topic} queue congested with {queue_size} messages!")
    
    def cleanup(self):
        """Dọn dẹp resources"""
        print("\n🧹 Cleaning up...")
        
        for consumer in self.consumers.values():
            consumer.close()
        
        if self.admin_client:
            self.admin_client.close()
        
        print("✅ Cleanup complete")


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor Kafka queues for Tme system")
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Monitoring interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Total monitoring duration in seconds (default: forever)"
    )
    parser.add_argument(
        "--kafka",
        type=str,
        default=KAFKA_BOOTSTRAP_SERVERS,
        help=f"Kafka bootstrap servers (default: {KAFKA_BOOTSTRAP_SERVERS})"
    )
    
    args = parser.parse_args()
    
    print("""
╔══════════════════════════════════════════════════════════╗
║         KAFKA QUEUE MONITOR - TME SYSTEM                 ║
╚══════════════════════════════════════════════════════════╝
""")
    
    if not KAFKA_AVAILABLE:
        print("\n❌ kafka-python not installed!")
        print("Install: pip install kafka-python")
        sys.exit(1)
    
    monitor = KafkaQueueMonitor(bootstrap_servers=args.kafka)
    monitor.monitor_loop(interval=args.interval, duration=args.duration)


if __name__ == "__main__":
    main()
