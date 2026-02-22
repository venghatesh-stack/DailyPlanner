const AIAssist = (() => {
  let quill;

function autoResizeQuill() {
  if (!quill) return;

  const editor = quill.root;
  if (!editor) return;

  editor.style.height = "auto";
  editor.style.height = editor.scrollHeight + "px";
}
function initEditor() {
  const container = $("ai-preview");
  if (!container) return;

  quill = new Quill("#ai-preview", {
    theme: "snow",
    modules: {
      toolbar: [
        ["bold", "italic", "underline"],
        [{ header: [1, 2, 3, false] }],
        [{ list: "ordered" }, { list: "bullet" }],
        ["link"]
      ]
    }
  });
  
  // Auto resize on text change
  quill.on("text-change", autoResizeQuill);

  // Initial resize
  setTimeout(autoResizeQuill, 0);
}
  /* ---------------- Helpers ---------------- */

  const $ = (id) => document.getElementById(id);

  function showToast(message, type = "info", duration = 2500) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  toast.innerHTML = `
    <div class="toast-message">${message}</div>
    <div class="toast-progress"></div>
  `;

  container.appendChild(toast);

  // Show animation
  setTimeout(() => {
    toast.classList.add("show");
  }, 10);

  // Animate progress bar
  const progress = toast.querySelector(".toast-progress");
  progress.style.animation = `toastProgress ${duration}ms linear forwards`;

  // Hide after duration
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, duration);
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

  let endpoint = "";

  if (mode === "gemini") {
    endpoint = "/references/ai-generate";
  } 
  else if (mode === "groq") {
    endpoint = "/references/ai-generate-groq";
  } 
  else {
    return;
  }

  if (!quill) return;

  // ✅ Show loading inside Quill
  quill.setText(`Generating with ${mode === "groq" ? "Groq" : "Gemini"}...`);

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });

    if (!res.ok) {
      quill.setText("AI request failed.");
      return;
    }

    const data = await res.json();

    const htmlContent = `
      <h2>${data.title || ""}</h2>
      <p>${data.description || ""}</p>
      ${data.url ? `<p><a href="${data.url}" target="_blank">${data.url}</a></p>` : ""}
    `;

    // ✅ Inject formatted HTML safely
    quill.setContents([]);
    quill.clipboard.dangerouslyPasteHTML(htmlContent);
    setTimeout(() => {
        autoResizeQuill();
        }, 50);
    

    // Autofill form
    $("ref-title").value = data.title || "";
    $("ref-url").value = data.url || "";
    $("ref-category").value = data.category || "";

    if (window.tagifyInstance && Array.isArray(data.tags)) {
      window.tagifyInstance.removeAllTags();
      window.tagifyInstance.addTags(data.tags);
    }
    // Autofill form
    $("ref-title").value = data.title || "";
    $("ref-url").value = data.url || "";
    $("ref-category").value = data.category || "";

    // Inject into main reference editor (#ref-editor)
    const mainEditor = document.getElementById("ref-editor");

    if (mainEditor && mainEditor.__quill) {
      const refQuill = mainEditor.__quill;
      refQuill.setContents([]);
      refQuill.clipboard.dangerouslyPasteHTML(htmlContent);
    }
    showToast(`${mode === "groq" ? "Groq" : "Gemini"} content generated.`);

  } catch (err) {
    console.error(err);
    quill.setText("AI generation failed.");
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
    if (quill) quill.setText("Please enter a topic.");
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
    initEditor();   
    initGenerate();
    initVoice();
    
  }

  return { init };

})();

document.addEventListener("DOMContentLoaded", AIAssist.init);