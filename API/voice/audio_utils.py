"""
Audio processing utilities for voice detection and manipulation
"""
import numpy as np
from config import _SILENCE_THRESHOLD_, _SILENCE_DURATION_

SILENCE_THRESHOLD = _SILENCE_THRESHOLD_
SILENCE_DURATION = _SILENCE_DURATION_


def detect_voice_activity(audio: np.ndarray, threshold: float = SILENCE_THRESHOLD) -> bool:
    """Phát hiện có giọng nói hay không"""
    if len(audio) == 0:
        return False
    rms = np.sqrt(np.mean(audio ** 2))
    return rms > threshold


def get_audio_energy(audio: np.ndarray) -> float:
    """Tính năng lượng RMS của audio"""
    if len(audio) == 0:
        return 0.0
    return np.sqrt(np.mean(audio ** 2))


def find_silence_split(audio: np.ndarray, sample_rate: int) -> int:
    """Tìm vị trí im lặng để cắt audio"""
    window_size = int(SILENCE_DURATION * sample_rate)
    if len(audio) < window_size:
        return -1
    
    for i in range(len(audio) - window_size, max(0, len(audio) // 2), -int(sample_rate * 0.1)):
        window = audio[i:i + window_size]
        if not detect_voice_activity(window):
            return i + window_size // 2
    return -1
