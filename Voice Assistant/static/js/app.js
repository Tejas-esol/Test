/**
 * Aria Voice Assistant — client application.
 *
 * Responsibilities:
 *   - Capture the microphone on demand (Start/Stop Recording buttons).
 *   - Transcribe speech in-browser via the Web Speech API and show it
 *     immediately in the chat log.
 *   - Send the transcript + conversation history to the backend, which
 *     forwards it to Gemini.
 *   - Speak the reply aloud while revealing it word-by-word in sync with
 *     the actual speech (via SpeechSynthesisUtterance boundary events).
 *   - Drive visual state (recording / processing / thinking / speaking).
 */

(() => {
  "use strict";

  // --------------------------------------------------------------------- //
  // State machine
  // --------------------------------------------------------------------- //
  const State = Object.freeze({
    IDLE: "idle",
    RECORDING: "recording",
    PROCESSING: "processing",
    THINKING: "thinking",
    SPEAKING: "speaking",
    ENDED: "ended",
  });

  const STATUS_LABELS = {
    [State.IDLE]: "Idle",
    [State.RECORDING]: "Listening…",
    [State.PROCESSING]: "Processing speech…",
    [State.THINKING]: "Thinking…",
    [State.SPEAKING]: "Speaking…",
    [State.ENDED]: "Conversation ended",
  };

  let currentState = State.IDLE;
  let isExiting = false; // set just before speaking the "Goodbye!" reply
  const conversationHistory = []; // [{ role: 'user' | 'model', text: string }]

  // --------------------------------------------------------------------- //
  // DOM references
  // --------------------------------------------------------------------- //
  const chatLog = document.getElementById("chat-log");
  const emptyState = document.getElementById("empty-state");
  const chatViewport = document.getElementById("chat-viewport");
  const liveCaption = document.getElementById("live-caption");
  const statusDot = document.getElementById("status-dot");
  const statusLabel = document.getElementById("status-label");
  const waveform = document.getElementById("waveform");
  const waveformBars = waveform.querySelectorAll(".bar");
  const startBtn = document.getElementById("start-btn");
  const stopBtn = document.getElementById("stop-btn");
  const restartBtn = document.getElementById("restart-btn");
  const dockHint = document.getElementById("dock-hint");

  const EXIT_KEYWORD = "exit";

  // --------------------------------------------------------------------- //
  // State transitions & UI sync
  // --------------------------------------------------------------------- //
  function setState(nextState) {
    currentState = nextState;

    statusLabel.textContent = STATUS_LABELS[nextState];
    statusDot.className = "status-dot " + nextState;

    waveform.classList.remove("is-recording", "is-thinking", "is-speaking");
    if (nextState === State.RECORDING) waveform.classList.add("is-recording");
    if (nextState === State.PROCESSING || nextState === State.THINKING) {
      waveform.classList.add("is-thinking");
    }
    if (nextState === State.SPEAKING) waveform.classList.add("is-speaking");

    const showStart = nextState === State.IDLE;
    const showStop = nextState === State.RECORDING;
    const showRestart = nextState === State.ENDED;

    startBtn.hidden = !showStart;
    stopBtn.hidden = !showStop;
    restartBtn.hidden = !showRestart;

    // Disable Start while the assistant is busy (processing/thinking/speaking)
    startBtn.disabled = nextState === State.PROCESSING ||
                         nextState === State.THINKING ||
                         nextState === State.SPEAKING;

    dockHint.style.visibility = nextState === State.ENDED ? "hidden" : "visible";

    if (nextState !== State.RECORDING) {
      liveCaption.textContent = "";
      resetWaveformBars();
    }
  }

  function resetWaveformBars() {
    waveformBars.forEach((bar) => { bar.style.height = "6px"; });
  }

  // --------------------------------------------------------------------- //
  // Chat log rendering
  // --------------------------------------------------------------------- //
  function scrollToBottom() {
    chatViewport.scrollTop = chatViewport.scrollHeight;
  }

  function hideEmptyState() {
    if (emptyState) emptyState.style.display = "none";
  }

  /**
   * Append a user message bubble to the chat log.
   * @param {string} text
   */
  function addUserMessage(text) {
    hideEmptyState();
    const row = document.createElement("div");
    row.className = "msg-row user";
    row.innerHTML = `
      <div class="bubble">
        <div class="msg-meta">You</div>
        <span class="bubble-text"></span>
      </div>`;
    row.querySelector(".bubble-text").textContent = text;
    chatLog.appendChild(row);
    scrollToBottom();
  }

  /**
   * Append an empty assistant bubble that will be filled progressively
   * as speech plays. Returns the text span element to update.
   * @param {boolean} isError
   * @returns {HTMLElement}
   */
  function addAssistantBubble(isError = false) {
    hideEmptyState();
    const row = document.createElement("div");
    row.className = "msg-row ai";
    row.innerHTML = `
      <div class="bubble${isError ? " error" : ""}">
        <div class="msg-meta">Aria</div>
        <span class="bubble-text"></span><span class="cursor"></span>
      </div>`;
    chatLog.appendChild(row);
    scrollToBottom();
    return row.querySelector(".bubble-text");
  }

  function removeCursor(bubbleTextEl) {
    const cursor = bubbleTextEl.parentElement.querySelector(".cursor");
    if (cursor) cursor.remove();
  }

  // --------------------------------------------------------------------- //
  // Speech-to-Text (Web Speech API)
  // --------------------------------------------------------------------- //
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;
  let recognitionActive = false;
  let finalTranscript = "";

  function isSpeechRecognitionSupported() {
    return !!SpeechRecognitionImpl;
  }

  function createRecognizer() {
    const recognition = new SpeechRecognitionImpl();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcriptPiece = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcriptPiece + " ";
        } else {
          interim += transcriptPiece;
        }
      }
      liveCaption.textContent = (finalTranscript + interim).trim();
    };

    recognition.onerror = (event) => {
      console.error("Speech recognition error:", event.error);
      if (event.error === "no-speech" || event.error === "aborted") return;
      recognitionActive = false;
      handleRecognitionSettled();
    };

    recognition.onend = () => {
      recognitionActive = false;
      handleRecognitionSettled();
    };

    return recognition;
  }

  let settleHandled = false;

  function handleRecognitionSettled() {
    if (settleHandled) return;
    settleHandled = true;
    stopMicVisualizer();

    const transcript = finalTranscript.trim();
    finalTranscript = "";

    if (!transcript) {
      setState(State.IDLE);
      return;
    }

    setState(State.PROCESSING);
    addUserMessage(transcript);
    conversationHistory.push({ role: "user", text: transcript });

    if (transcript.toLowerCase().replace(/[.!?]/g, "").trim() === EXIT_KEYWORD) {
      handleExit();
    } else {
      requestReply(transcript);
    }
  }

  function startRecording() {
    if (!isSpeechRecognitionSupported()) {
      addAssistantBubble(true).textContent =
        "Speech recognition isn't supported in this browser. Please use Chrome or Edge.";
      return;
    }

    finalTranscript = "";
    settleHandled = false;
    liveCaption.textContent = "";

    recognizer = createRecognizer();
    try {
      recognizer.start();
      recognitionActive = true;
      setState(State.RECORDING);
      startMicVisualizer();
    } catch (err) {
      console.error("Failed to start recognition:", err);
    }
  }

  function stopRecording() {
    if (recognizer && recognitionActive) {
      recognizer.stop(); // triggers onend -> handleRecognitionSettled
    } else {
      handleRecognitionSettled();
    }
  }

  // --------------------------------------------------------------------- //
  // Microphone amplitude visualizer (Web Audio API)
  // --------------------------------------------------------------------- //
  let audioContext = null;
  let analyserNode = null;
  let micStream = null;
  let visualizerFrame = null;

  async function startMicVisualizer() {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(micStream);
      analyserNode = audioContext.createAnalyser();
      analyserNode.fftSize = 64;
      source.connect(analyserNode);

      const dataArray = new Uint8Array(analyserNode.frequencyBinCount);

      const tick = () => {
        analyserNode.getByteFrequencyData(dataArray);
        waveformBars.forEach((bar, i) => {
          const sample = dataArray[i % dataArray.length];
          const height = 6 + (sample / 255) * 26;
          bar.style.height = `${height.toFixed(1)}px`;
        });
        visualizerFrame = requestAnimationFrame(tick);
      };
      tick();
    } catch (err) {
      console.warn("Mic visualizer unavailable (permission or device issue):", err);
    }
  }

  function stopMicVisualizer() {
    if (visualizerFrame) cancelAnimationFrame(visualizerFrame);
    visualizerFrame = null;
    if (micStream) {
      micStream.getTracks().forEach((track) => track.stop());
      micStream = null;
    }
    if (audioContext) {
      audioContext.close().catch(() => {});
      audioContext = null;
    }
    analyserNode = null;
  }

  // --------------------------------------------------------------------- //
  // Backend call (Gemini)
  // --------------------------------------------------------------------- //
  async function requestReply(userMessage) {
    setState(State.THINKING);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          history: conversationHistory.slice(0, -1), // exclude the message just added
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "The server returned an error.");
      }

      conversationHistory.push({ role: "model", text: data.reply });
      speakReply(data.reply);

    } catch (err) {
      console.error("Chat request failed:", err);
      const bubbleTextEl = addAssistantBubble(true);
      bubbleTextEl.textContent =
        "Sorry, I couldn't reach the assistant just now. Please check your connection and try again.";
      setState(State.IDLE);
    }
  }

  // --------------------------------------------------------------------- //
  // Text-to-Speech with synchronized progressive text reveal
  // --------------------------------------------------------------------- //
  const synth = window.speechSynthesis;

  function speakReply(replyText) {
    const bubbleTextEl = addAssistantBubble(false);

    if (!synth) {
      // No TTS available: just show the full text.
      bubbleTextEl.textContent = replyText;
      removeCursor(bubbleTextEl);
      setState(isExiting ? State.ENDED : State.IDLE);
      return;
    }

    setState(State.SPEAKING);

    const utterance = new SpeechSynthesisUtterance(replyText);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    let boundaryFired = false;
    let fallbackTimer = null;

    utterance.onboundary = (event) => {
      if (event.name && event.name !== "word") return;
      boundaryFired = true;
      const revealedUpTo = event.charIndex + (event.charLength || 0);
      bubbleTextEl.textContent = replyText.slice(0, revealedUpTo || event.charIndex);
      scrollToBottom();
    };

    utterance.onstart = () => {
      // Fallback for browsers (e.g. Firefox) that don't reliably fire
      // onboundary: reveal text on a timer roughly paced to speech rate.
      fallbackTimer = setTimeout(() => {
        if (!boundaryFired) revealByTimer(bubbleTextEl, replyText);
      }, 250);
    };

    utterance.onend = () => {
      clearTimeout(fallbackTimer);
      bubbleTextEl.textContent = replyText;
      removeCursor(bubbleTextEl);
      scrollToBottom();
      setState(isExiting ? State.ENDED : State.IDLE);
    };

    utterance.onerror = (event) => {
      console.error("Speech synthesis error:", event.error);
      clearTimeout(fallbackTimer);
      bubbleTextEl.textContent = replyText;
      removeCursor(bubbleTextEl);
      setState(isExiting ? State.ENDED : State.IDLE);
    };

    synth.cancel(); // clear any queued utterances
    synth.speak(utterance);
  }

  /** Word-paced fallback reveal for engines without onboundary support. */
  function revealByTimer(bubbleTextEl, fullText) {
    const words = fullText.split(/\s+/);
    const estimatedMs = Math.max(1200, fullText.length * 55); // ~55ms/char heuristic
    const perWordMs = estimatedMs / words.length;
    let shown = 0;

    const interval = setInterval(() => {
      shown += 1;
      bubbleTextEl.textContent = words.slice(0, shown).join(" ");
      scrollToBottom();
      if (shown >= words.length || !synth.speaking) {
        clearInterval(interval);
      }
    }, perWordMs);
  }

  // --------------------------------------------------------------------- //
  // Exit / restart flow
  // --------------------------------------------------------------------- //
  function handleExit() {
    const goodbye = "Goodbye!";
    conversationHistory.push({ role: "model", text: goodbye });
    isExiting = true; // tells speakReply's onend handler to land on ENDED, not IDLE
    speakReply(goodbye);
  }

  function restartConversation() {
    conversationHistory.length = 0;
    isExiting = false;
    chatLog.innerHTML = "";
    if (emptyState) {
      chatLog.appendChild(emptyState);
      emptyState.style.display = "flex";
    }
    setState(State.IDLE);
  }

  // --------------------------------------------------------------------- //
  // Wire up buttons
  // --------------------------------------------------------------------- //
  startBtn.addEventListener("click", startRecording);
  stopBtn.addEventListener("click", stopRecording);
  restartBtn.addEventListener("click", restartConversation);

  // --------------------------------------------------------------------- //
  // Initial UI state
  // --------------------------------------------------------------------- //
  if (!isSpeechRecognitionSupported()) {
    dockHint.textContent = "Speech recognition isn't supported in this browser. Try Chrome or Edge.";
    startBtn.disabled = true;
  }

  setState(State.IDLE);
})();
