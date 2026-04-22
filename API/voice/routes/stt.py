import shutil
import os
import asyncio
import json
import numpy as np

from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from langdetect import detect, LangDetectException
from pydub import AudioSegment

from config import USE_CELERY, _SAMPLE_, _MIN_, _MAX_, _MIN_VOICE_
from API.voice.audio_utils import detect_voice_activity, get_audio_energy, find_silence_split, SILENCE_DURATION
from API.voice.text_utils import is_valid_text
from API.voice.model_loader import get_model
from API.voice.tasks import transcribe_audio

router = APIRouter(tags=["STT"])

TEMP_DIR = Path("temp_audio")
TEMP_DIR.mkdir(exist_ok=True)

SAMPLE_RATE = _SAMPLE_
MIN_AUDIO_LENGTH = _MIN_
MAX_AUDIO_LENGTH = _MAX_
MIN_VOICE_ENERGY = _MIN_VOICE_


@router.websocket("/stt")
async def websocket_stt(ws: WebSocket):
    """WebSocket endpoint for real-time speech-to-text"""
    await ws.accept()
    print("Client connected for streaming STT")
    
    model = get_model()
    audio_buffer = np.array([], dtype=np.float32)
    full_text = ""
    silence_samples = 0
    chunk_count = 0
    
    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await ws.receive_bytes()
            chunk_count += 1
            
            if len(data) % 2 == 0:
                chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            elif len(data) % 4 == 0:
                chunk = np.frombuffer(data, dtype=np.float32)
            else:
                continue
            
            audio_buffer = np.concatenate([audio_buffer, chunk])
            has_voice = detect_voice_activity(chunk)
            chunk_energy = get_audio_energy(chunk)
            
            if chunk_count % 50 == 0:
                print(f"[DEBUG] Chunks: {chunk_count}, Buffer: {len(audio_buffer)/SAMPLE_RATE:.2f}s, Energy: {chunk_energy:.4f}")
            
            if not has_voice:
                silence_samples += len(chunk)
            else:
                silence_samples = 0
            
            audio_duration = len(audio_buffer) / SAMPLE_RATE
            silence_duration_current = silence_samples / SAMPLE_RATE
            
            should_transcribe = (
                audio_duration >= MIN_AUDIO_LENGTH and
                (silence_duration_current >= SILENCE_DURATION or audio_duration >= MAX_AUDIO_LENGTH)
            )
            
            if should_transcribe and len(audio_buffer) > 0:
                split_point = find_silence_split(audio_buffer, SAMPLE_RATE)
                
                if split_point > 0 and split_point < len(audio_buffer):
                    process_audio = audio_buffer[:split_point]
                    audio_buffer = audio_buffer[split_point:]
                else:
                    process_audio = audio_buffer
                    audio_buffer = np.array([], dtype=np.float32)
                
                silence_samples = 0
                audio_energy = get_audio_energy(process_audio)
                print(f"[DEBUG] Processing {len(process_audio)/SAMPLE_RATE:.2f}s, Energy: {audio_energy:.4f}")
                
                if audio_energy < MIN_VOICE_ENERGY:
                    print(f"[DEBUG] Skipped - energy too low")
                    continue
                
                try:
                    segments, _ = await loop.run_in_executor(
                        None,
                        lambda: model.transcribe(
                            process_audio,
                            beam_size=1,
                            vad_filter=True,
                            without_timestamps=True
                        )
                    )
                    
                    new_text = " ".join([seg.text for seg in segments]).strip()
                    print(f"[DEBUG] Raw: '{new_text}'")
                    
                    if new_text and is_valid_text(new_text):
                        full_text = (full_text + " " + new_text).strip()
                        print(f"[DEBUG] Sending: '{new_text}'")
                        
                        await ws.send_text(json.dumps({
                            "partial": new_text,
                            "text": full_text,
                            "is_final": silence_duration_current >= SILENCE_DURATION
                        }))
                        
                except Exception as e:
                    print(f"Transcription error: {e}")
                    await ws.send_text(json.dumps({"error": str(e)}))
            
            elif audio_duration > 0.5 and audio_duration < MIN_AUDIO_LENGTH:
                await ws.send_text(json.dumps({
                    "status": "listening",
                    "buffer_duration": round(audio_duration, 2)
                }))

    except WebSocketDisconnect:
        print("Client disconnected")
        if len(audio_buffer) > SAMPLE_RATE * 0.2:
            try:
                segments, _ = await loop.run_in_executor(
                    None,
                    lambda: model.transcribe(audio_buffer, beam_size=3, vad_filter=True)
                )
                final_text = " ".join([seg.text for seg in segments]).strip()
                if final_text and is_valid_text(final_text):
                    full_text = (full_text + " " + final_text).strip()
                print(f"Final: {full_text}")
            except Exception as e:
                print(f"Final error: {e}")
    
    except Exception as e:
        print(f"WebSocket error: {e}")


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    """
    Nhận file âm thanh, trả về:
    - text
    - duration (giây)
    - filename
    - file size
    """
    model = get_model()

    if not file.filename.lower().endswith((".wav", ".mp3", ".m4a")):
        raise HTTPException(status_code=400, detail="Định dạng file không được hỗ trợ")

    file_path = TEMP_DIR / file.filename
    wav_path = file_path.with_suffix(".wav")

    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = file_path.stat().st_size

        audio = AudioSegment.from_file(file_path)
        duration = len(audio) / 1000.0  

        if duration > 30:
            raise HTTPException(
                status_code=400,
                detail=f"File quá dài ({duration:.1f}s). Tối đa 30 giây."
            )

        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(wav_path, format="wav")

        if USE_CELERY:
            task = transcribe_audio.delay(str(wav_path))
            return {
                "status": "queued",
                "task_id": task.id,
                "filename": file.filename,
                "duration": duration,
                "size_bytes": file_size, 
            }

        # Transcribe with faster-whisper
        loop = asyncio.get_running_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(str(wav_path), beam_size=5)
        )

        text = " ".join([seg.text for seg in segments]).strip()

        # Determine language: prefer model info, fallback to langdetect
        language = "unknown"
        if isinstance(info, dict) and info.get("language"):
            language = info.get("language")
        else:
            try:
                if text:
                    language = detect(text)
            except LangDetectException:
                language = "unknown"

        return {
            "status": "success",
            "text": text,
            "language": language,
            "filename": file.filename,
            "duration": duration,
            "size_bytes": file_size
        }

    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

    finally:
        # Đợi một chút trước khi xóa file để đảm bảo không bị lock
        import time
        time.sleep(0.1)
        
        try:
            if file_path.exists():
                os.remove(file_path)
        except PermissionError:
            pass  # Bỏ qua nếu file đang bị lock
            
        try:
            if wav_path.exists():
                os.remove(wav_path)
        except PermissionError:
            pass  # Bỏ qua nếu file đang bị lock


@router.get("/v1/stt/result/{task_id}")
def get_task_result(task_id: str):
    """Get result of a Celery task by task_id"""
    task = transcribe_audio.AsyncResult(task_id)

    if task.state == "SUCCESS":
        return {
            "status": "success",
            "result": task.result
        }
    return {
        "status": task.state
    }
