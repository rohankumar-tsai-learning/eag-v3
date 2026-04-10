import { getRoastFromGemini } from './api_handler.js';
import { CONFIG } from './config.js';

// Configuration for Productivity and Distraction
const PRODUCTIVE_DOMAINS = [
    'arxiv.org', 'scholar.google.com', 'stackoverflow.com', 'github.com', 
    'medium.com', 'docs.google.com', 'coursera.org', 'udemy.com', 
    'khanacademy.org', 'docs.microsoft.com', 'developer.mozilla.org',
    'chat.openai.com', 'claude.ai', 'gemini.google.com'
];

const DISTRACTION_DOMAINS = [
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com', 
    'reddit.com', 'youtube.com', 'wikipedia.org', 'buzzfeed.com', 
    'tiktok.com', 'netflix.com', 'twitch.tv'
];

let lastProductiveContext = null;
let productiveStartTime = null;
let lastRoastTime = 0;
const THRESHOLD_MS = 10000; // 10 seconds
const COOLDOWN_MS = 60000; // 60 seconds between roasts

// Track tab updates
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete' && tab.url) {
        checkUrl(tab);
    }
});

// Track tab switches
chrome.tabs.onActivated.addListener(async (activeInfo) => {
    const tab = await chrome.tabs.get(activeInfo.tabId);
    if (tab.url) {
        checkUrl(tab);
    }
});

async function checkUrl(tab) {
    const url = new URL(tab.url);
    const domain = url.hostname.replace('www.', '');
    
    console.log(`[Focus Bully] Checking URL: ${domain}`);
    
    const isProductive = PRODUCTIVE_DOMAINS.some(d => domain.includes(d));
    const isDistraction = DISTRACTION_DOMAINS.some(d => domain.includes(d));

    console.log(`[Focus Bully] Classification - Productive: ${isProductive}, Distraction: ${isDistraction}`);

    if (isProductive) {
        console.log("User is working. Good.");
        lastProductiveContext = {
            site: domain,
            title: tab.title,
            timestamp: Date.now()
        };
        if (!productiveStartTime) {
            productiveStartTime = Date.now();
        }
    } else if (isDistraction) {
        const now = Date.now();
        const sessionDuration = productiveStartTime ? now - productiveStartTime : 0;
        const sessionDurationSec = Math.floor(sessionDuration / 1000);

        console.log(`[Focus Bully] Distraction detected! Productive session was: ${sessionDurationSec}s`);

        if (lastProductiveContext && sessionDuration >= THRESHOLD_MS) {
            console.log("[Focus Bully] Threshold met. Triggering roast...");
            
            // Special check for Wikipedia "History of Spoons" type stuff
            let distractionTopic = {
                site: domain,
                title: tab.title
            };

            triggerRoast(tab.id, lastProductiveContext, distractionTopic);
            
            // Reset to prevent spamming
            lastProductiveContext = null;
            productiveStartTime = null;
        }
    } else {
        // Neutral site, ignore or keep state
    }
}

async function triggerRoast(tabId, context, distraction) {
    const now = Date.now();
    if (now - lastRoastTime < COOLDOWN_MS) {
        console.log("[Focus Bully] Roast in cooldown. Skipping to avoid rate limits.");
        return;
    }

    try {
        const apiKey = CONFIG.GEMINI_API_KEY;

        if (!apiKey || apiKey === "YOUR_API_KEY_HERE") {
            console.error("[Focus Bully] Gemini API Key not set in config.js.");
            return;
        }

        const roastData = await getRoastFromGemini(apiKey, context, distraction);
        
        // Inject content script if not already there
        chrome.scripting.executeScript({
            target: { tabId: tabId },
            files: ['content.js']
        }, () => {
            // Send the message to the content script
            chrome.tabs.sendMessage(tabId, {
                action: 'SHOW_ROAST',
                data: roastData
            });
            // Update last roast time only on success
            lastRoastTime = Date.now();
        });

    } catch (e) {
        console.error("Error triggering roast:", e);
    }
}
