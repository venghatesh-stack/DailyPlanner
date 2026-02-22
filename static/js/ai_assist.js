const AIAssist = (() => {

  /* ---------------- Helpers ---------------- */

  const $ = (id) => document.getElementById(id);

  function showToast(message, duration = 2500) {
    const container = $("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.innerText = message;

    container.appendChild(toast);
    setTimeout(() => toast.remove(), duration);
  }

  /* ---------------- Manual Mode ---------------- */

  function openManualMode(query) {
    navigator.clipboard.writeText(query);
    window.open("https://chat.openai.com", "_blank");
    showToast("Query copied. Paste in ChatGPT.");
  }

  /* ---------------- API Mode (Gemini) ---------------- */

  /* ---------------- API Mode Router ---------------- */

async function generateViaAPI(query, mode) {

  const preview = $("ai-preview");

  let endpoint = "";
  let loadingText = "";

  if (mode === "gemini") {
    endpoint = "/references/ai-generate";
    loadingText = "Generating with Gemini...";
  } 
  else if (mode === "groq") {
    endpoint = "/references/ai-generate-groq";
    loadingText = "Generating with Groq...";
  } 
  else {
    return;
  }

  preview.innerHTML = loadingText;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });

    if (!res.ok) {
      preview.innerHTML = "AI request failed.";
      return;
    }

    const data = await res.json();

    preview.innerHTML = `
      <h4>${data.title || ""}</h4>
      <p>${data.description || ""}</p>
      ${data.url ? `<a href="${data.url}" target="_blank">${data.url}</a>` : ""}
    `;

    // Autofill
    $("ref-title").value = data.title || "";
    $("ref-description").value = data.description || "";
    $("ref-url").value = data.url || "";
    $("ref-category").value = data.category || "";

    if (window.tagifyInstance && Array.isArray(data.tags)) {
      window.tagifyInstance.removeAllTags();
      window.tagifyInstance.addTags(data.tags);
    }

    showToast(`${mode === "groq" ? "Groq" : "Gemini"} content generated.`);

  } catch (err) {
    console.error(err);
    preview.innerHTML = "AI generation failed.";
    showToast("Error generating AI content.");
  }
}
  /* ---------------- Voice ---------------- */

  function initVoice() {
    const btn = $("voiceBtn");
    const input = $("ai-query");
    if (!btn || !input) return;

    if (!("webkitSpeechRecognition" in window)) {
      btn.style.display = "none";
      return;
    }

    const recognition = new webkitSpeechRecognition();
    recognition.lang = "en-IN";

    btn.addEventListener("click", () => {
      recognition.start();
      btn.innerText = "🎧";
    });

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      input.value = transcript;

      if (!$("ref-title").value.trim()) {
        $("ref-title").value = transcript.substring(0, 80);
      }
    };

    recognition.onend = () => {
      btn.innerText = "🎙";
    };
  }

  /* ---------------- Generate Button ---------------- */

  function initGenerate() {

    const btn = $("ai-primary-btn");
    if (!btn) return;

   btn.addEventListener("click", async () => {

  const query = $("ai-query")?.value.trim();
  const mode = $("ai-mode")?.value;

  if (!query) {
    $("ai-preview").innerHTML = "Please enter a topic.";
    return;
  }

  btn.disabled = true;
  btn.innerText = "Generating...";

  try {
    if (mode === "manual") {
      openManualMode(query);
    } else {
      await generateViaAPI(query, mode);
    }
  } finally {
    btn.disabled = false;
    btn.innerText = "Generate";
  }

});
}

  /* ---------------- Init ---------------- */

  function init() {
    const modeSelect = $("ai-mode");
    const savedMode = localStorage.getItem("ai_mode");

    if (savedMode) modeSelect.value = savedMode;

    modeSelect.addEventListener("change", function () {
    localStorage.setItem("ai_mode", this.value);
    });
    initGenerate();
    initVoice();
  }

  return { init };

})();

document.addEventListener("DOMContentLoaded", AIAssist.init);