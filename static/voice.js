// ===============================
// 🎙 Voice Dictation for Projects
// ===============================

let recognition;
let isRecording = false;
console.log("🎙 Dictation init running");
function initVoiceDictation(textareaId, statusElId) {
  const textarea = document.getElementById(textareaId);
  const statusEl = document.getElementById(statusElId);
  console.log("🎯 textarea:", textarea);
  if (!("webkitSpeechRecognition" in window)) {
    statusEl.textContent = "🎙 Voice not supported in this browser";
    return;
  }

  recognition = new webkitSpeechRecognition();
  recognition.lang = "en-IN";
  recognition.continuous = true;      // ✅ pause & resume
  recognition.interimResults = false; // ✅ final text only

  recognition.onstart = () => {
    isRecording = true;
    statusEl.textContent = "🎙 Listening… speak naturally";
  };

  recognition.onend = () => {
    isRecording = false;
    statusEl.textContent = "⏸️ Paused. Tap mic to continue.";
  };

  recognition.onerror = (e) => {
    console.error("Voice error:", e);
    statusEl.textContent = "⚠️ Voice error. Try again.";
  };

  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      let text = event.results[i][0].transcript.trim();

      // ✅ normalize dates HERE (correct place)
      text = normalizeNaturalDates(text);

      // ✅ each pause → new task line
      textarea.value +=
        (textarea.value ? "\n" : "") + "- " + text;
    }
  };
}

function toggleVoice(textareaId, statusElId) {
  if (isRecording) {
    recognition.stop();
    return;
  }

  // 🔁 Create NEW instance every time (important)
  initVoiceDictation(textareaId, statusElId);

  try {
    recognition.start();
  } catch (e) {
    console.error("Failed to start recognition:", e);
  }
}


// -------------------------------
// 🧠 Natural date parsing
// -------------------------------
function normalizeNaturalDates(text) {
  const today = new Date();

  const addDays = (n) => {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  };

  return text
    .replace(/\btomorrow\b/i, `(due ${addDays(1)})`)
    .replace(/\bnext week\b/i, `(due ${addDays(7)})`);
}
