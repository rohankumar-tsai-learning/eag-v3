# 🐙 The Focus Bully

**The Focus Bully** is a Chrome Extension (Manifest V3) that detects when you are procrastinating and uses the **Google Gemini API** to roast you with witty, judgmental jokes. It's the AI focus coach you didn't ask for, but definitely need.

## 🚀 Features
- **Context-Aware Roasting**: Knows what you were supposed to be doing and what you're actually doing.
- **Smart Detection**: Detects transitions from productive sites (arXiv, GitHub, Docs) to distractions (Wikipedia, Reddit, YouTube).
- **Premium UI**: Beautiful glassmorphism pop-ups that don't mess with the host page's styling.
- **AI-Powered**: Leverages Gemini 1.5 Flash for unique, smart-aleck roasts every time.

## 📺 Demo
Part 1: [https://youtu.be/OpOaz3nPRnI](https://youtu.be/OpOaz3nPRnI)
Part 2: [https://youtu.be/_doxroSI5tw](https://youtu.be/_doxroSI5tw)

## 🛠️ Installation

1. **Clone the Repository**:
   ```bash
   git clone <your-repo-url>
   cd focus-bully
   ```

2. **Configure API Key**:
   - Copy `config.example.js` to `config.js`.
   - Get your API key from [Google AI Studio](https://aistudio.google.com/).
   - Paste your key into `config.js`:
     ```javascript
     const CONFIG = {
         GEMINI_API_KEY: "YOUR_ACTUAL_API_KEY_HERE"
     };
     ```

3. **Load in Chrome**:
   - Open Chrome and navigate to `chrome://extensions/`.
   - Enable **Developer mode** (top right toggle).
   - Click **Load unpacked** and select the `focus-bully` folder.

## ⚙️ How it Works
The extension monitors your tabs. If you've been on a "Productive" site for more than **10 seconds** and then switch to a "Distraction" site, the Bully will trigger.

- **Productive Domains**: arXiv, GitHub, StackOverflow, Google Docs, etc.
- **Distraction Domains**: Wikipedia (Trivia/Lists), Facebook, Reddit, YouTube, etc.

## 🔒 Security
Your API key is stored in `config.js`, which is listed in `.gitignore`. **Never commit your `config.js` file to GitHub.**

## 🤖 AI Personality
The Focus Bully is programmed to be "smart-aleck" and witty. It's judgmental about your curiosity regarding "History of Spoons" but ultimately wants you to succeed.

---
*Built with logic, judgment, and a bit of salt.*
