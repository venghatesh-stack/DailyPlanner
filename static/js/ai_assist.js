const AIAssist = (() => {

  let tagifyInstance = null;

  const queryInput = () => document.getElementById("ai-query");
  const modeSelect = () => document.getElementById("ai-mode");
  const previewBox = () => document.getElementById("ai-preview");
  const primaryBtn = () => document.getElementById("ai-primary-btn");
  const voiceBtn = () => document.getElementById("voiceBtn");

  /* ---------------- Toast ---------------- */

  function showToast(message, duration = 3000) {
    const container = document.getElementById("toast-container");
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

  /* ---------------- API Mode ---------------- */

  async function generateViaAPI(query) {
    try {
      showToast("Generating...");

      const res = await fetch("/generate-ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: query })
      });

      const data = await res.json();
      previewBox().innerHTML = data.content || "";

      const titleInput = document.getElementById("ref-title");
      if (titleInput && !titleInput.value.trim()) {
        titleInput.value = query.substring(0, 80);
      }

      if (tagifyInstance) {
        tagifyInstance.addTags(["ai-generated"]);
      }

      showToast("AI response generated.");
    } catch (err) {
      console.error(err);
      showToast("Error generating response.");
    }
  }

  /* ---------------- Generate Handler ---------------- */

  function handleGenerate() {
    const query = queryInput()?.value.trim();
    if (!query) {
      showToast("Enter a question first.");
      return;
    }

    const mode = modeSelect()?.value;

    if (mode === "manual") {
      openManualMode(query);
    } else {
      generateViaAPI(query);
    }
  }

  /* ---------------- Voice ---------------- */

  function initVoice() {
    const btn = voiceBtn();
    const input = queryInput();
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

      const titleInput = document.getElementById("ref-title");
      if (titleInput && !titleInput.value.trim()) {
        titleInput.value = transcript.substring(0, 80);
      }
    };

    recognition.onend = () => {
      btn.innerText = "🎙";
    };
  }

  /* ---------------- Tagify ---------------- */

  async function initTagify() {
    const input = document.getElementById("ref-tags");
    if (!input) return;

    const res = await fetch("/api/tags");
    const existingTags = await res.json();

    tagifyInstance = new Tagify(input, {
      whitelist: existingTags,
      dropdown: { enabled: 0, maxItems: 10 }
    });
  }

  /* ---------------- Auto Tagging ---------------- */

  function initAutoTagging() {
    const titleInput = document.getElementById("ref-title");
    if (!titleInput) return;

    titleInput.addEventListener("blur", () => {
      if (!tagifyInstance) return;

      const title = titleInput.value.trim();
      if (!title) return;

      const words = title
        .toLowerCase()
        .split(/\s+/)
        .filter(w => w.length > 4);

      const unique = [...new Set(words)];

      tagifyInstance.addTags(unique.slice(0, 3));
    });
  }

  /* ---------------- Init ---------------- */

  async function init() {
    primaryBtn()?.addEventListener("click", handleGenerate);
    initVoice();
    await initTagify();
    initAutoTagging();
  }

  return { init };

})();

document.addEventListener("DOMContentLoaded", AIAssist.init);
document.getElementById("ai-primary-btn")
  .addEventListener("click", async () => {

    const mode = document.getElementById("ai-mode").value;
    const query = document.getElementById("ai-query").value.trim();
    const preview = document.getElementById("ai-preview");

    if (!query) {
      preview.innerHTML = "Please enter a topic.";
      return;
    }

    // Manual Mode (User copies from ChatGPT manually)
    if (mode === "manual") {
      preview.innerHTML = `
        <p>Manual mode selected.</p>
        <p>Copy from ChatGPT and paste into fields below.</p>
      `;
      return;
    }

    // API Mode (Google Gemini)
    preview.innerHTML = "Generating with Google AI...";

    try {
      const res = await fetch("/references/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query })
      });

      const data = await res.json();

      // Show preview
      preview.innerHTML = `
        <h4>${data.title}</h4>
        <p>${data.description}</p>
        <a href="${data.url}" target="_blank">${data.url}</a>
      `;

      // Auto-fill Add Reference form
      document.getElementById("ref-title").value = data.title || "";
      document.getElementById("ref-description").value = data.description || "";
      document.getElementById("ref-url").value = data.url || "";

      // Tags (array → comma string)
      if (Array.isArray(data.tags)) {
        document.getElementById("ref-tags").value =
          data.tags.join(", ");
      }

      if (data.category) {
        document.getElementById("ref-category").value = data.category;
      }

    } catch (err) {
      preview.innerHTML = "AI generation failed.";
      console.error(err);
    }
});