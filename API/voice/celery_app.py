from celery import Celery
from config import REDIS_BROKER, REDIS_BACKEND

celery_app = Celery(
    "stt_worker",
    broker=REDIS_BROKER,
    backend=REDIS_BACKEND,
)

celery_app.conf.task_routes = {
    "app.tasks.transcribe_audio": {"queue": "stt_queue"}
}
