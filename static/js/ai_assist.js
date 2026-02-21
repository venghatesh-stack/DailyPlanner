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