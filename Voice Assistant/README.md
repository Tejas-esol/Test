# Aria — Voice Assistant (Web Edition)

A browser-based conversational voice assistant with a real chat UI,
Gemini-powered responses, and speech synced to a live typing effect.

This is a redesign of an earlier CLI prototype. See **"Why this
architecture"** at the bottom for the reasoning.

## What it does

1. Click **Start Recording** — the browser begins listening.
2. Your speech is transcribed live and appears in the chat as you speak.
3. Click **Stop Recording** — the final transcript is sent to Gemini.
4. Gemini's reply is spoken aloud, and the text is revealed in sync with
   the speech (word by word), so you can read and listen at once.
5. Say **"exit"** at any point to end the conversation gracefully.

**Note on Recent Updates:** The project has been restructured to correctly place HTML, CSS, and JS files into their respective `templates/` and `static/` directories as required by Flask. Additionally, `.env` files are now securely ignored by Git.

Recording, processing, thinking, and speaking are all shown as distinct
visual states so you always know what the app is doing.

## Project Structure

```
voice_assistant_web/
├── app.py                  # Flask backend — proxies chat to Gemini
├── requirements.txt        # Python dependencies
├── .env.example             # Template for your Gemini API key
├── templates/
│   └── index.html          # Chat UI markup
└── static/
    ├── css/style.css       # Visual design (studio-console theme)
    └── js/app.js           # Recording, STT, TTS, state machine
```

## Prerequisites

- Python 3.9+
- A Gemini API key: https://aistudio.google.com/app/apikey
- **Google Chrome or Microsoft Edge** — the app uses the browser's native
  `SpeechRecognition` API for speech-to-text, which Firefox and Safari
  don't support yet. Text-to-speech (`speechSynthesis`) works in all
  modern browsers.
- A microphone, obviously.

## Installation

1. Open a terminal in the `voice_assistant_web` folder.
2. (Recommended) create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set your Gemini API key:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and paste in your key:
   ```
   GEMINI_API_KEY=your_actual_key_here
   ```

## Running the Application

```bash
python app.py
```

Then open **http://localhost:5000** in Chrome or Edge.

The browser will ask for microphone permission the first time you click
**Start Recording** — allow it.

## How It's Built

### Speech-to-text (client-side)
Uses the browser's native `SpeechRecognition` API. This runs entirely
in the browser (no audio file upload, no server round-trip), so the
transcript appears close to instantly as you speak, with the final
result finalized on **Stop Recording**.

### Response generation (server-side)
The transcript is POSTed to `/api/chat` along with the recent
conversation history. The Flask backend calls the Gemini API
(`google-genai` SDK) with a system instruction that keeps replies short
and speakable (no markdown, no bullet points — this is going to be read
aloud). The Gemini API key never touches the browser.

### Text-to-speech + synced reveal (client-side)
The reply is spoken using the browser's `speechSynthesis` API. Chrome
and Edge fire an `onboundary` event at each spoken word, which the app
uses to reveal the matching slice of text in the chat bubble — so the
typing effect is driven by the actual audio playback, not a fake timer.
Browsers that don't support word boundaries fall back to a
timing-estimated word-by-word reveal.

### State machine
`idle → recording → processing → thinking → speaking → idle`, with a
separate `ended` state after "exit". Each state drives the status pill,
the waveform visualizer (real microphone amplitude while recording via
the Web Audio API; animated bars while thinking/speaking), and which
buttons are enabled.

## Troubleshooting

- **"Speech recognition isn't supported in this browser"** — switch to
  Chrome or Edge.
- **No response after Stop Recording** — check the terminal running
  `app.py` for errors; most commonly `GEMINI_API_KEY` is missing or
  invalid. `GET /api/health` will tell you if the key is configured.
- **Nothing is spoken aloud** — some browsers require a page interaction
  before allowing audio; clicking Start Recording counts as that
  interaction, so this should resolve itself after the first turn.
- **Mic permission denied** — the waveform will just stay flat during
  recording (visualizer is best-effort); transcription itself still
  requires mic permission and won't work without it.

## Why this architecture

The original version was a Python CLI script (`sounddevice` → file →
`speech_recognition` → dictionary lookup → `pyttsx3` → file → playback).
For a fixed 5-second batch recording with canned replies, that was
reasonable. It doesn't fit the interactive, real-time experience you
described, for a few concrete reasons:

- **Round-tripping WAV files through the server adds latency** a
  browser-native `SpeechRecognition` call doesn't have — transcription
  starts appearing while you're still talking, not after a file finishes
  uploading and processing.
- **A fixed 5-second window doesn't match user-controlled turn-taking.**
  Start/Stop buttons need the recognizer to be started and stopped on
  demand, which the CLI's `sd.rec(duration)` call can't do.
- **Syncing a typing effect to speech requires knowing what's being
  said and when.** The browser's `speechSynthesis` API exposes
  per-word timing (`onboundary`); a server-rendered `.wav` file played
  back separately would need forced-alignment tooling to get the same
  effect.
- **The dictionary-based bot logic doesn't scale to open-ended
  conversation**, which is the whole point of wiring in Gemini.

The trade-off: this version requires Chrome/Edge (for `SpeechRecognition`)
and an internet connection (for Gemini), whereas the CLI version could
run fully offline with `pyttsx3`. If offline operation matters more than
the interactive UI, the original script is the better fit — otherwise,
this redesign is a strict upgrade for the experience you described.
