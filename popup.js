const PUNCHY_WARNINGS = [
    "Get to the chopper! (And keep it under 300 words, please)",
    "I'll be back... but only if you select fewer than 300 words.",
    "Hasta la vista, baby! That's too many words (limit: 300).",
    "It's not a tumor! But it is over 300 words.",
    "If it bleeds, we can kill it... but we can't read over 300 words.",
    "You're one... huge block of text! Keep it under 300 words.",
    "Put the text down! Now! (Under 300 words limit)."
];

document.addEventListener('DOMContentLoaded', async () => {
    const statusEl = document.getElementById('selection-status');
    const wordCountEl = document.getElementById('word-count');
    const warningEl = document.getElementById('warning-message');
    const playBtn = document.getElementById('btn-play');
    const errorEl = document.getElementById('error-message');

    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        
        if (!tab) {
             throw new Error("No active tab found.");
        }
        
        const url = new URL(tab.url);
        if (!url.hostname.includes('arxiv.org') && 
            !url.hostname.includes('scholar.google.com') && 
            !url.hostname.includes('huggingface.co')) {
            statusEl.textContent = "Unsupported website";
            wordCountEl.textContent = "Navigate to Arxiv, Google Scholar, or Hugging Face.";
            return;
        }

        chrome.tabs.sendMessage(tab.id, { type: 'GET_SELECTION' }, (response) => {
            if (chrome.runtime.lastError) {
                statusEl.textContent = "Not Ready";
                wordCountEl.textContent = "Please refresh the page and try again.";
                return;
            }

            if (!response || !response.hasSelection) {
                statusEl.textContent = "No text selected";
                wordCountEl.textContent = "Select some text on the page first.";
                return;
            }

            const wordCount = response.wordCount;
            statusEl.textContent = "Text Selected";
            wordCountEl.textContent = `${wordCount} words selected`;

            if (wordCount > 300) {
                const randomWarning = PUNCHY_WARNINGS[Math.floor(Math.random() * PUNCHY_WARNINGS.length)];
                warningEl.textContent = randomWarning;
                warningEl.classList.remove('hidden');
                playBtn.disabled = true;
            } else if (wordCount > 0) {
                playBtn.disabled = false;
                
                playBtn.addEventListener('click', () => {
                    playBtn.disabled = true;
                    playBtn.textContent = 'Processing...';
                    
                    chrome.tabs.sendMessage(tab.id, { type: 'START_TTS' });
                    
                    setTimeout(() => window.close(), 1000);
                });
            }
        });
    } catch (err) {
        if(err.message.includes("Invalid URL")) {
            statusEl.textContent = "Unsupported website";
            wordCountEl.textContent = "Navigate to a supported domain.";
        } else {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        }
    }
});
