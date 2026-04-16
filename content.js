let restoreTimeout = null;
let audioContext = null;
let audioSource = null;
let animFrameId = null;
let startTime = 0;

const TTS_WORD_PREFIX = "tts-word-";
const TTS_HIGHLIGHT_CLASS = "tts-highlight";

let currentHighlightedId = null;
let activeElementsMap = {};

// ─── Message Listener ───────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'GET_SELECTION') {
        const selection = window.getSelection();
        if (!selection || !selection.rangeCount || selection.isCollapsed) {
            sendResponse({ hasSelection: false });
            return;
        }
        const text = selection.toString().trim();
        if (!text) {
            sendResponse({ hasSelection: false });
            return;
        }
        const words = text.split(/\s+/).filter(w => w.length > 0);
        sendResponse({ hasSelection: true, wordCount: words.length });
    } else if (message.type === 'START_TTS') {
        startTTSProcess();
    }
});

// ─── Main Process ───────────────────────────────────────────────────
function startTTSProcess() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) return;
    // Get the exact selected text for the API payload
    const selectedText = selection.toString().trim();
    if (!selectedText) return;
    const wordsPayload = selectedText.split(/\s+/).filter(w => w.length > 0);
    const range = selection.getRangeAt(0);

    cleanupExistingPlayback();

    let rootNode = range.commonAncestorContainer;
    if (rootNode.nodeType === Node.TEXT_NODE) {
        rootNode = rootNode.parentNode;
    }

    const treeWalker = document.createTreeWalker(
        rootNode,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode: function(node) {
                if (range.intersectsNode(node)) {
                    if (node.nodeValue.trim() !== '') {
                        return NodeFilter.FILTER_ACCEPT;
                    }
                }
                return NodeFilter.FILTER_REJECT;
            }
        }
    );

    const textNodes = [];
    let currentNode;
    while (currentNode = treeWalker.nextNode()) {
        textNodes.push(currentNode);
    }
    if (textNodes.length === 0) return;

    let wordIndex = 0;
    const elementsMap = new Map();

    textNodes.forEach(node => {
        const parent = node.parentNode;
        const fullText = node.nodeValue;

        // Clip to selection range boundaries
        let startIdx = 0;
        let endIdx = fullText.length;

        if (node === range.startContainer) {
            startIdx = range.startOffset;
        }
        if (node === range.endContainer) {
            endIdx = range.endOffset;
        }

        const textBefore = fullText.substring(0, startIdx);
        const selectedPart = fullText.substring(startIdx, endIdx);
        const textAfter = fullText.substring(endIdx);

        const fragment = document.createDocumentFragment();

        // Keep text before selection untouched
        if (textBefore) {
            fragment.appendChild(document.createTextNode(textBefore));
        }

        // Wrap only the selected portion's words in spans
        const parts = selectedPart.split(/(\s+)/);
        parts.forEach(part => {
            if (part.trim() === '') {
                fragment.appendChild(document.createTextNode(part));
            } else {
                const span = document.createElement('span');
                span.id = `${TTS_WORD_PREFIX}${wordIndex}`;
                span.className = 'tts-word';
                span.textContent = part;
                fragment.appendChild(span);
                elementsMap.set(wordIndex.toString(), span);
                wordIndex++;
            }
        });

        // Keep text after selection untouched
        if (textAfter) {
            fragment.appendChild(document.createTextNode(textAfter));
        }

        parent.replaceChild(fragment, node);
    });

    selection.removeAllRanges();

    activeElementsMap = {};
    for (let [key, val] of elementsMap.entries()) {
        activeElementsMap[key] = val;
    }

    // Show a "Processing..." indicator
    showPlayerOverlay('processing');

    chrome.runtime.sendMessage({ type: 'SYNTHESIZE', words: wordsPayload }, (response) => {
        if (chrome.runtime.lastError) {
            console.error("Message error:", chrome.runtime.lastError.message);
            removePlayerOverlay();
            scheduleRestore(0);
            return;
        }
        if (!response || !response.success) {
            console.error("Synthesize failed:", response?.error || "Unknown error");
            removePlayerOverlay();
            scheduleRestore(0);
            return;
        }

        // Audio data received — show the play button
        showPlayerOverlay('ready', response.data);
    });
}

// ─── Floating Player Overlay ────────────────────────────────────────
// We inject a small "▶ Play" button on the page. When the user clicks
// it, that click IS a real user gesture, which lets us create an 
// AudioContext and call play() without DOMException.

function showPlayerOverlay(state, audioData) {
    removePlayerOverlay();

    const overlay = document.createElement('div');
    overlay.id = 'tts-player-overlay';
    overlay.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 2147483647;
        background: #0f172a;
        color: #fff;
        border-radius: 12px;
        padding: 14px 22px;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 14px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        cursor: default;
        display: flex;
        align-items: center;
        gap: 10px;
        user-select: none;
        transition: opacity 0.3s;
    `;

    if (state === 'processing') {
        overlay.innerHTML = `
            <span style="font-size:18px;">⏳</span>
            <span>Processing audio...</span>
        `;
    } else if (state === 'ready') {
        overlay.innerHTML = `
            <button id="tts-play-btn" style="
                appearance: none;
                background: #22c55e;
                color: #fff;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 6px;
            ">▶ Play</button>
        `;
        const btn = overlay.querySelector('#tts-play-btn');
        btn.addEventListener('click', () => {
            showPlayerOverlay('playing');
            playAudioWithContext(audioData);
        });
    } else if (state === 'playing') {
        overlay.innerHTML = `
            <span style="font-size:16px;">🔊</span>
            <span>Playing...</span>
            <button id="tts-pause-btn" style="
                appearance: none;
                background: #eab308;
                color: #000;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
            ">⏸ Pause</button>
            <button id="tts-stop-btn" style="
                appearance: none;
                background: #ef4444;
                color: #fff;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
                cursor: pointer;
            ">⏹ Stop</button>
        `;
        const pauseBtn = overlay.querySelector('#tts-pause-btn');
        const stopBtn = overlay.querySelector('#tts-stop-btn');

        pauseBtn.addEventListener('click', () => {
            if (audioContext && audioContext.state === 'running') {
                audioContext.suspend();
                pauseBtn.textContent = '▶ Resume';
                pauseBtn.style.background = '#22c55e';
                pauseBtn.style.color = '#fff';
                overlay.querySelector('span:nth-child(2)').textContent = 'Paused';
            } else if (audioContext && audioContext.state === 'suspended') {
                audioContext.resume();
                pauseBtn.textContent = '⏸ Pause';
                pauseBtn.style.background = '#eab308';
                pauseBtn.style.color = '#000';
                overlay.querySelector('span:nth-child(2)').textContent = 'Playing...';
            }
        });

        stopBtn.addEventListener('click', () => {
            cleanupExistingPlayback();
        });
    }

    document.body.appendChild(overlay);
}

function removePlayerOverlay() {
    const existing = document.getElementById('tts-player-overlay');
    if (existing) existing.remove();
}

// ─── Audio Playback via Web Audio API ───────────────────────────────
// AudioContext.decodeAudioData handles WAV/PCM natively, which avoids
// the format mismatch that caused the DOMException with new Audio().

function playAudioWithContext(data) {
    const { audioContent, audioMimeType, timepoints } = data;

    // Decode base64 to ArrayBuffer
    const binaryStr = atob(audioContent);
    const len = binaryStr.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
    }
    const arrayBuffer = bytes.buffer;

    // Gemini TTS always returns raw PCM (s16le, 24kHz, mono) — always add WAV header
    const finalBuffer = addWavHeader(arrayBuffer, 24000, 1, 16);

    // Create AudioContext (user just clicked, so this is allowed)
    audioContext = new AudioContext();

    audioContext.decodeAudioData(finalBuffer.slice(0))
        .then(audioBuffer => {
            // Build timepoints for highlighting
            const totalWords = Object.keys(activeElementsMap).length;
            let workingTimepoints = (timepoints && timepoints.length > 0) ? timepoints : [];
            
            if (workingTimepoints.length === 0 && totalWords > 0) {
                // Fallback: evenly distribute highlights across audio duration
                const dur = audioBuffer.duration;
                for (let i = 0; i < totalWords; i++) {
                    workingTimepoints.push({ timeSeconds: (dur / totalWords) * i });
                }
            }

            // Play the audio
            audioSource = audioContext.createBufferSource();
            audioSource.buffer = audioBuffer;
            audioSource.connect(audioContext.destination);
            startTime = audioContext.currentTime;
            audioSource.start(0);

            // Start highlight sync loop
            let nextIdx = 0;
            function syncLoop() {
                const elapsed = audioContext.currentTime - startTime;
                while (
                    nextIdx < workingTimepoints.length &&
                    elapsed >= (workingTimepoints[nextIdx].timeSeconds || 0)
                ) {
                    // Remove previous highlight
                    if (currentHighlightedId !== null) {
                        const prev = activeElementsMap[currentHighlightedId];
                        if (prev) prev.classList.remove(TTS_HIGHLIGHT_CLASS);
                    }
                    // Add new highlight
                    const idxStr = nextIdx.toString();
                    const el = activeElementsMap[idxStr];
                    if (el) {
                        el.classList.add(TTS_HIGHLIGHT_CLASS);
                    }
                    currentHighlightedId = idxStr;
                    nextIdx++;
                }
                if (nextIdx < workingTimepoints.length || audioContext.currentTime - startTime < audioBuffer.duration) {
                    animFrameId = requestAnimationFrame(syncLoop);
                }
            }
            animFrameId = requestAnimationFrame(syncLoop);

            // Handle audio end
            audioSource.onended = () => {
                if (animFrameId) cancelAnimationFrame(animFrameId);
                if (currentHighlightedId !== null) {
                    const prev = activeElementsMap[currentHighlightedId];
                    if (prev) prev.classList.remove(TTS_HIGHLIGHT_CLASS);
                    currentHighlightedId = null;
                }
                removePlayerOverlay();
                scheduleRestore(5000);
            };
        })
        .catch(err => {
            console.error("AudioContext decodeAudioData failed:", err);
            // Fallback: try using HTMLAudioElement with Blob
            fallbackHTMLAudio(audioContent, audioMimeType, timepoints);
        });
}

// ─── Fallback: HTML5 Audio via Blob ─────────────────────────────────
function fallbackHTMLAudio(audioBase64, mimeType, timepoints) {
    const binaryStr = atob(audioBase64);
    const len = binaryStr.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
    }
    
    // Try common audio mime types
    const mimeAttempts = [mimeType, 'audio/wav', 'audio/mpeg', 'audio/ogg'];
    
    function tryMime(idx) {
        if (idx >= mimeAttempts.length) {
            console.error("All audio playback attempts failed");
            removePlayerOverlay();
            scheduleRestore(0);
            return;
        }
        const blob = new Blob([bytes], { type: mimeAttempts[idx] });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        
        const totalWords = Object.keys(activeElementsMap).length;
        let workingTimepoints = (timepoints && timepoints.length > 0) ? timepoints : [];

        audio.addEventListener('loadedmetadata', () => {
            if (workingTimepoints.length === 0 && totalWords > 0) {
                const dur = audio.duration;
                for (let i = 0; i < totalWords; i++) {
                    workingTimepoints.push({ timeSeconds: (dur / totalWords) * i });
                }
            }
        });

        let nextIdx = 0;
        audio.addEventListener('timeupdate', () => {
            while (nextIdx < workingTimepoints.length && audio.currentTime >= (workingTimepoints[nextIdx].timeSeconds || 0)) {
                if (currentHighlightedId !== null) {
                    const prev = activeElementsMap[currentHighlightedId];
                    if (prev) prev.classList.remove(TTS_HIGHLIGHT_CLASS);
                }
                const idxStr = nextIdx.toString();
                const el = activeElementsMap[idxStr];
                if (el) el.classList.add(TTS_HIGHLIGHT_CLASS);
                currentHighlightedId = idxStr;
                nextIdx++;
            }
        });

        audio.addEventListener('ended', () => {
            if (currentHighlightedId !== null) {
                const prev = activeElementsMap[currentHighlightedId];
                if (prev) prev.classList.remove(TTS_HIGHLIGHT_CLASS);
                currentHighlightedId = null;
            }
            URL.revokeObjectURL(url);
            removePlayerOverlay();
            scheduleRestore(5000);
        });

        audio.play().then(() => {
            // Success
        }).catch(() => {
            URL.revokeObjectURL(url);
            tryMime(idx + 1);
        });
    }
    tryMime(0);
}

// ─── WAV Header Builder (for raw PCM / L16 data) ───────────────────
function addWavHeader(pcmBuffer, sampleRate, numChannels, bitsPerSample) {
    const pcmBytes = new Uint8Array(pcmBuffer);
    const dataLength = pcmBytes.length;
    const header = new ArrayBuffer(44);
    const view = new DataView(header);
    
    function writeString(offset, str) {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset + i, str.charCodeAt(i));
        }
    }
    
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * numChannels * (bitsPerSample / 8), true);
    view.setUint16(32, numChannels * (bitsPerSample / 8), true);
    view.setUint16(34, bitsPerSample, true);
    writeString(36, 'data');
    view.setUint32(40, dataLength, true);
    
    const result = new Uint8Array(44 + dataLength);
    result.set(new Uint8Array(header), 0);
    result.set(pcmBytes, 44);
    return result.buffer;
}

// ─── Cleanup ────────────────────────────────────────────────────────
function scheduleRestore(delayMs) {
    if (restoreTimeout) clearTimeout(restoreTimeout);
    restoreTimeout = setTimeout(() => {
        cleanupExistingPlayback();
    }, delayMs);
}

function cleanupExistingPlayback() {
    if (restoreTimeout) {
        clearTimeout(restoreTimeout);
        restoreTimeout = null;
    }
    if (animFrameId) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
    }
    if (audioSource) {
        try { audioSource.stop(); } catch (e) {}
        audioSource = null;
    }
    if (audioContext) {
        try { audioContext.close(); } catch (e) {}
        audioContext = null;
    }
    removePlayerOverlay();
    
    const spans = document.querySelectorAll('.tts-word');
    spans.forEach(span => {
        const textNode = document.createTextNode(span.textContent);
        if (span.parentNode) {
            span.parentNode.replaceChild(textNode, span);
        }
    });

    activeElementsMap = {};
    currentHighlightedId = null;
}
