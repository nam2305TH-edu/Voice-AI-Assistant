
const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const isSecure = window.location.protocol === 'https:';
const wsProtocol = isSecure ? 'wss:' : 'ws:';
const httpProtocol = isSecure ? 'https:' : 'http:';
const host = isLocalhost ? '127.0.0.1:8000' : window.location.host;

const WS_URL = `${wsProtocol}//${host}/v1/stt`;
const API_URL = `${httpProtocol}//${host}/v1/stt`;
const SEARCH_URL = `${httpProtocol}//${host}/v1/search`;

console.log('API URLs:', { WS_URL, API_URL, SEARCH_URL });

const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 1600;
const SILENCE_TIMEOUT = 1200; 

let ws = null;
let audioStream = null;
let audioContext = null;
let processor = null;
let isListening = false;
let fullTextAccumulated = "";
let silenceTimer = null;
let isSpeaking = false;
let autoMode = true; // Chế độ tự động
let isSearching = false; // Đang tìm kiếm
let lastActivityTime = 0; // Thời điểm có hoạt động cuối

const status = document.getElementById('status');
const partial = document.getElementById('partial');
const fullText = document.getElementById('fullText');
const debug = document.getElementById('debug');
const answer = document.getElementById('answer');


function log(msg) {
    console.log(msg);
    if (debug) debug.innerText = msg;
}

// ========== Check và trigger auto search ==========
function checkAndTriggerAutoSearch() {
    if (!autoMode || !fullTextAccumulated || isSpeaking || isSearching || !isListening) {
        return;
    }
    
    const timeSinceActivity = Date.now() - lastActivityTime;
    
    if (timeSinceActivity >= SILENCE_TIMEOUT && lastActivityTime > 0) {
        console.log("✅ Im lặng " + timeSinceActivity + "ms - Tự động tìm kiếm!");
        lastActivityTime = 0; // Reset để không trigger lại
        autoSearchAndSpeak();
    }
}

// ========== Start auto check interval ==========
let autoCheckInterval = null;
function startAutoCheck() {
    if (autoCheckInterval) return;
    autoCheckInterval = setInterval(checkAndTriggerAutoSearch, 500);
    console.log("Started auto check interval");
}

function stopAutoCheck() {
    if (autoCheckInterval) {
        clearInterval(autoCheckInterval);
        autoCheckInterval = null;
    }
}

// ========== TTS - Phát giọng nói ==========
function speak(text, onEnd = null) {
    if (!text) return;

    window.speechSynthesis.cancel();
    isSpeaking = true;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'vi-VN';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    utterance.onend = () => {
        isSpeaking = false;
        log("Đọc xong - Mở lại mic...");
        if (onEnd) onEnd();
    };

    utterance.onerror = () => {
        isSpeaking = false;
        log("Lỗi TTS - Mở lại mic...");
        if (onEnd) onEnd();
    };

    window.speechSynthesis.speak(utterance);
    log("Đang phát: " + text.substring(0, 50) + "...");
}

// ========== Auto Search & Speak (tự động) ==========
async function autoSearchAndSpeak() {
    if (!fullTextAccumulated || isSpeaking || isSearching) return;
    
    isSearching = true;
    stopAutoCheck();

    // Tắt mic trước khi tìm kiếm
    pauseListening();
    
    answer.innerText = "Đang tìm kiếm...";
    status.innerText = "Đang tìm kiếm...";
    log("Auto Searching: " + fullTextAccumulated);

    try {
        const response = await fetch(SEARCH_URL + "?q=" + encodeURIComponent(fullTextAccumulated));
        const data = await response.json();

        isSearching = false;
        
        if (data.status === "success") {
            answer.innerText = data.answer;
            status.innerText = "🔊 Đang đọc...";
            
            // Phát voice, khi xong thì mở lại mic
            speak(data.answer, () => {
                // Xóa text cũ và mở lại mic
                clearText();
                resumeListening();
            });
        } else {
            answer.innerText = "Lỗi: " + data.message;
            resumeListening();
        }
    } catch (err) {
        isSearching = false;
        answer.innerText = "Lỗi: " + err.message;
        log("Search error: " + err.message);
        resumeListening();
    }
}

// ========== Search & Speak (manual button) ==========
async function searchAndSpeak() {
    if (!fullTextAccumulated) {
        alert("Chưa có text để tìm kiếm!");
        return;
    }
    
    // Clear silence timer
    if (silenceTimer) clearTimeout(silenceTimer);
    
    await autoSearchAndSpeak();
}

function toggleListening() {
    if (isListening) {
        stopListening();
        document.getElementById('toggleBtn').innerText = "Bắt đầu";
    } else {
        startListening();
        document.getElementById('toggleBtn').innerText = "Tạm dừng";
    }
}

async function startListening() {
    if (isListening) return;

    try {
        status.innerText = "Yêu cầu microphone...";
        log("Requesting mic...");

        audioStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: TARGET_RATE,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true
            }
        });

        log("Mic OK, connecting WS...");
        status.innerText = "Kết nối server...";

        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            log("WebSocket connected!");
            status.innerText = "🎤 Đang nghe...";
            isListening = true;
            setupAudio();
            startAutoCheck(); // Bắt đầu kiểm tra tự động
        };

        ws.onmessage = (e) => {
            const data = JSON.parse(e.data);
            console.log("WS Message:", data);

            // Có hoạt động mới - cập nhật thời gian
            if (data.partial || data.text) {
                lastActivityTime = Date.now();
            }

            if (data.partial) {
                partial.innerText = "-> " + data.partial;
            }
            
            if (data.text) {
                fullTextAccumulated = data.text;
                fullText.innerText = data.text;
                console.log("Got text:", data.text);
                
                if (data.is_final) {
                    partial.innerText = "...";
                }
            }
            
            if (data.error) {
                log("Error: " + data.error);
            }
        };

        ws.onclose = () => {
            log("WebSocket closed");
            status.innerText = "Mất kết nối";
            isListening = false;
        };

        ws.onerror = (err) => {
            log("WebSocket error");
            status.innerText = "Lỗi WS";
        };

    } catch (err) {
        log("Error: " + err.message);
        status.innerText = "Lỗi: " + err.message;
    }
}

function setupAudio() {
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        log("AudioContext sampleRate: " + audioContext.sampleRate);

        const source = audioContext.createMediaStreamSource(audioStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);

        let pending = new Float32Array(0);
        let chunkCount = 0;

        processor.onaudioprocess = (e) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;

            const input = e.inputBuffer.getChannelData(0);

            // Downsample to 16kHz
            const ratio = audioContext.sampleRate / TARGET_RATE;
            const newLen = Math.floor(input.length / ratio);
            const downsampled = new Float32Array(newLen);
            for (let i = 0; i < newLen; i++) {
                downsampled[i] = input[Math.floor(i * ratio)];
            }

            // Accumulate
            const newPending = new Float32Array(pending.length + downsampled.length);
            newPending.set(pending, 0);
            newPending.set(downsampled, pending.length);
            pending = newPending;

            // Send when we have enough
            while (pending.length >= CHUNK_SAMPLES) {
                const chunk = pending.slice(0, CHUNK_SAMPLES);
                pending = pending.slice(CHUNK_SAMPLES);

                // Convert to int16
                const int16 = new Int16Array(chunk.length);
                for (let i = 0; i < chunk.length; i++) {
                    let s = Math.max(-1, Math.min(1, chunk[i]));
                    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }

                ws.send(int16.buffer);
                chunkCount++;

                if (chunkCount % 50 === 0) {
                    log("Sent " + chunkCount + " chunks");
                }
            }
        };

        source.connect(processor);
        processor.connect(audioContext.destination);

        log("Audio setup complete");

    } catch (err) {
        log("Audio setup error: " + err.message);
    }
}

function stopListening() {
    isListening = false;
    stopAutoCheck();
    if (silenceTimer) clearTimeout(silenceTimer);
    if (processor) processor.disconnect();
    if (audioContext) audioContext.close();
    if (audioStream) audioStream.getTracks().forEach(t => t.stop());
    if (ws) ws.close();
    processor = null;
    audioContext = null;
    audioStream = null;
    ws = null;
    status.innerText = "Đã dừng";
    log("Stopped");
}

// ========== Pause/Resume listening (không đóng hoàn toàn) ==========
function pauseListening() {
    stopAutoCheck();
    if (silenceTimer) clearTimeout(silenceTimer);
    if (processor) processor.disconnect();
    if (ws) ws.close();
    ws = null;
    isListening = false;
    status.innerText = "⏸️ Tạm dừng mic...";
    log("Paused listening");
}

function resumeListening() {
    if (isSpeaking) return;
    status.innerText = "🎤 Đang mở lại mic...";
    log("Resuming listening...");
    
    // Khởi động lại WebSocket và audio
    startListening();
}

function clearText() {
    fullTextAccumulated = "";
    fullText.innerText = "Hãy nói gì đó...";
    partial.innerText = "...";
    isSearching = false;
    lastActivityTime = 0;
    if (silenceTimer) clearTimeout(silenceTimer);
    silenceTimer = null;
}

// ========== Toggle Auto Mode ==========
function toggleAutoMode() {
    autoMode = !autoMode;
    const btn = document.getElementById('autoBtn');
    if (btn) {
        btn.innerText = autoMode ? "🤖 Auto: BẬT" : "🤖 Auto: TẮT";
        btn.style.background = autoMode ? "#4CAF50" : "#f44336";
    }
    log("Auto mode: " + (autoMode ? "ON" : "OFF"));
}



// Upload file
async function uploadFile() {
    const fileInput = document.getElementById("audioFile");
    if (!fileInput.files.length) {
        alert("Chọn file audio!");
        return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    document.getElementById("uploadResult").innerText = "Đang xử lý...";

    try {
        const response = await fetch(API_URL, {
            method: "POST",
            body: formData
        });
        const data = await response.json();

        if (data.status === "success") {
            document.getElementById("uploadResult").innerText =
                `[${data.language}] ${data.text} (${data.duration.toFixed(1)}s)`;
        } else {
            document.getElementById("uploadResult").innerText = "Lỗi: " + (data.message || data.detail);
        }
    } catch (err) {
        document.getElementById("uploadResult").innerText = "Lỗi: " + err.message;
    }
}

window.onbeforeunload = stopListening;
