# 🎧 Scholar's Walkman

**Scholar's Walkman** is a high-performance Chrome extension designed for academics and technical researchers. It transforms selected text from complex scientific papers (ArXiv, Google Scholar, Hugging Face) into high-fidelity, natural speech with real-time, word-level synchronization.

---

## 📺 Demo / Tutorial
> [!NOTE]  
> Demo: [https://youtu.be/f_9cyHwkDw4](https://youtu.be/f_9cyHwkDw4)
> Capabilities: [https://youtu.be/6gR5bI0lY8c](https://youtu.be/6gR5bI0lY8c)
> Contraints: [https://youtu.be/HhOfLE-FW6Q](https://youtu.be/HhOfLE-FW6Q)
> LinkedIn Post: https://www.linkedin.com/posts/rohan-kumar-07b341404_as-a-student-exploring-the-world-of-agentic-share-7450922949508952064-m8Nl?utm_source=share&utm_medium=member_desktop&rcm=ACoAAGdG7x8Bj-5xGd7nhtZAAejoilri157A2Ro

---

## 🚀 Key Features

- **Gemini-Powered Neural TTS**: Integrates the state-of-the-art `gemini-3.1-flash-tts` model for expressive, low-latency audio generation.
- **Precision Word Highlighting**: Active word-tracking via `requestAnimationFrame` and millisecond-accurate timepoint metadata.
- **Gesture-Compliant Playback**: Implements a dedicated UI overlay to meet modern browser autoplay security policies (ensuring reliable audio start).
- **Selection Boundary Clipping**: Intelligent `Range` processing that targets only your highlighted text, ignoring surrounding paragraph noise.
- **Full Playback Control**: Pause, resume, and stop functionality directly on the page.

---

## 🛠 Technical Architecture & Complexity

The extension is built on **Chrome Manifest V3** and leverages a multi-layered technical stack:

### 1. Neural Voice Engine (The "Brain")
It utilizes the **Google Generative Language API** (specifically the Gemini 3.1 Flash TTS Preview model). This involves:
- **Asynchronous Relay**: The extension manages API calls via a background service worker to keep the UI thread responsive.
- **Modality Handling**: Requesting `AUDIO` response modalities and handling binary data streams within a JSON wrapper.

### 2. Audio Reconstruction (The "Walkman")
Because the API returns raw, headerless L16 PCM data, the extension implements a custom **WAV Header Reconstruction** algorithm. It dynamically calculates byte rates and block aligns to transform raw bytes into a format decodable by the **Web Audio API (`AudioContext`)**.

### 3. DOM Synchronization (The "Visuals")
To achieve millisecond-perfect highlighting, the system uses a **TreeWalker-based word wrapper**:
- **Span Extraction**: Selected text nodes are dynamically split and wrapped into identified `<span>` elements without breaking the site's layout.
- **Sync-Loop**: It uses a high-frequency synchronization loop matching the audio's `currentTime` against the API-provided `timepoints` metadata.

### 4. Injection & Security
- **Content Security**: Carefully manages `host_permissions` to operate on sensitive technical domains.
- **UI Decoupling**: The player is injected as a separate DOM node to avoid interference with the host site's CSS.

---

## 💻 Powered By

- **Core**: JavaScript (ES6+), HTML5, Vanilla CSS
- **APIs**: Chrome Extension API (V3), Google AI Studio (Gemini 3.1)
- **Audio**: Web Audio API (PCM-to-WAV Decoding)

---

## 📜 Setup

1. Clone this repository.
2. Create a `config.js` file based on the template and add your `API_KEY`.
3. Load the folder as an **Unpacked Extension** in Chrome.
4. Highlight technical text and let our new clean voice guide you through the research!

---

*“I’ll be back... to read that next paragraph.”*
