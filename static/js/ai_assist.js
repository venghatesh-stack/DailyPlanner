const AIAssist = (() => {

  const queryInput = () => document.getElementById("ai-query");
  const modeSelect = () => document.getElementById("ai-mode");
  const previewBox = () => document.getElementById("ai-preview");
  const primaryBtn = () => document.getElementById("ai-primary-btn");

  /* ------------------------------
     Toast Notifications
  ------------------------------ */

  function showToast(message, duration = 3000) {
    const container = document.getElementById("toast-container");

    const toast = document.createElement("div");
    toast.className = "toast";
    toast.innerText = message;

    container.appendChild(toast);

    setTimeout(() => {
      toast.remove();
    }, duration);
  }

  /* ------------------------------
     Manual Mode
  ------------------------------ */

  function openManualMode(query) {
    navigator.clipboard.writeText(query);
    window.open("https://chat.openai.com", "_blank");
    showToast("Query copied. Paste in ChatGPT.");
  }

  /* ------------------------------
     API Mode
  ------------------------------ */

  async function generateViaAPI(query) {
    try {
      showToast("Generating...");

      const res = await fetch("/generate-ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: query })
      });

      const data = await res.json();

      previewBox().innerHTML = data.content;

      // Auto-fill reference form
      document.getElementById("ref-title").value = query;
      document.getElementById("ref-url").value = "";
      document.getElementById("ref-tags").value = "ai-generated";

      showToast("AI response generated.");
    } catch (err) {
      console.error(err);
      showToast("Error generating response.");
    }
  }

  /* ------------------------------
     Main Handler
  ------------------------------ */

  function handleGenerate() {
    const query = queryInput().value.trim();

    if (!query) {
      showToast("Enter a question first.");
      return;
    }

    const mode = modeSelect().value;

    if (mode === "manual") {
      openManualMode(query);
    } else {
      generateViaAPI(query);
    }
  }

  function init() {
    primaryBtn().addEventListener("click", handleGenerate);
  }

  return { init };

})();

document.addEventListener("DOMContentLoaded", AIAssist.init);
document.addEventListener("DOMContentLoaded", () => {
  const voiceBtn = document.getElementById("voiceBtn");
  const questionInput = document.getElementById("questionInput");

  if (!('webkitSpeechRecognition' in window)) {
    voiceBtn.style.display = "none";
    return;
  }

  const recognition = new webkitSpeechRecognition();
  recognition.continuous = false;
  recognition.lang = "en-IN";  // since you're in India
  recognition.interimResults = false;

  voiceBtn.addEventListener("click", () => {
    recognition.start();
    voiceBtn.innerText = "🎧 Listening...";
  });

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    questionInput.value = transcript;

    // Auto-copy to title
    autoFillTitle(transcript);
  };

  recognition.onend = () => {
    voiceBtn.innerText = "🎙";
  };
});
function autoFillTitle(questionText) {
  const titleInput = document.getElementById("titleInput");

  if (!titleInput.value.trim()) {
    // First 80 chars as title
    titleInput.value = questionText.substring(0, 80);
  }
}
questionInput.addEventListener("input", (e) => {
  autoFillTitle(e.target.value);
});

document.addEventListener("DOMContentLoaded", async () => {

  const input = document.querySelector("#tagInput");

  // Fetch existing tags from backend
  const res = await fetch("/api/tags");
  const existingTags = await res.json(); 
  // Example response: ["ai", "machine learning", "deep learning"]

  const tagify = new Tagify(input, {
    whitelist: existingTags,   // existing tags for suggestions
    dropdown: {
      maxItems: 10,
      enabled: 0,              // show suggestions on focus
      closeOnSelect: false
    }
  });

});
form.addEventListener("submit", () => {
  const tagifyData = tagify.value;
  const cleanTags = tagifyData.map(tag => tag.value);

  // Put into hidden input
  document.getElementById("hiddenTags").value = JSON.stringify(cleanTags);
});