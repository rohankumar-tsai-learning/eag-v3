import { API_KEY } from './config.js';

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'SYNTHESIZE') {
        handleSynthesize(message.words)
            .then(data => sendResponse({ success: true, data }))
            .catch(error => {
                console.error("Synthesize error:", error);
                sendResponse({ success: false, error: error.message });
            });
        return true;
    }
});

async function handleSynthesize(words) {
    const textToRead = words.join(" ");

    const requestBody = {
        contents: [
            {
                role: "user",
                parts: [{ text: textToRead }]
            }
        ],
        generationConfig: {
            responseModalities: ["AUDIO"],
            speechConfig: {
                voiceConfig: {
                    prebuiltVoiceConfig: {
                        voiceName: "Puck"
                    }
                }
            }
        }
    };

    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-tts-preview:generateContent?key=${API_KEY}`;
    
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Gemini TTS API Error: ${response.status} ${errText}`);
    }

    const data = await response.json();
    
    let audioBase64 = "";
    let audioMimeType = "audio/wav";
    let timepoints = [];

    if (data.candidates && data.candidates[0]) {
        const candidate = data.candidates[0];
        
        if (candidate.content && candidate.content.parts) {
            for (const part of candidate.content.parts) {
                if (part.inlineData && part.inlineData.data) {
                    audioBase64 = part.inlineData.data;
                    if (part.inlineData.mimeType) {
                        audioMimeType = part.inlineData.mimeType;
                    }
                    break;
                }
            }
        }
        
        // Try multiple possible locations for timepoints metadata
        const meta = candidate.generationMetadata || candidate.generation_metadata || {};
        if (meta.timepoints) {
            timepoints = meta.timepoints;
        }
    }

    if (!audioBase64) {
        throw new Error("No audio content returned from Gemini API");
    }

    return {
        audioContent: audioBase64,
        audioMimeType: audioMimeType,
        timepoints: timepoints || []
    };
}
