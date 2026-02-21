window.tagifyInstance = null;

document.addEventListener("DOMContentLoaded", function () {

  // -----------------------------
  // INIT TAGIFY
  // -----------------------------
  const tagInput = document.getElementById("ref-tags");
  if (tagInput) {
    window.tagifyInstance = new Tagify(tagInput, {
      delimiters: ",",
      dropdown: { enabled: 0 }
    });
  }
  // -----------------------------
// AI Toggle Persistence
// -----------------------------
const aiToggle = document.getElementById("enable-ai");

if (aiToggle) {
  const saved = localStorage.getItem("ai_enabled");

  if (saved !== null) {
    aiToggle.checked = saved === "true";
  }

  aiToggle.addEventListener("change", function () {
    localStorage.setItem("ai_enabled", this.checked);
  });
}
  // -----------------------------
  // SAVE BUTTON
  // -----------------------------
  const saveBtn = document.getElementById("saveRefBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", saveReference);
  }

  // -----------------------------
  // URL AUTO METADATA FETCH
  // -----------------------------
  const refUrlInput = document.getElementById("ref-url");
  if (refUrlInput) {
    refUrlInput.addEventListener("change", autoFetchMetadata);
  }

});


// =====================================================
// AUTO FETCH METADATA (TITLE + TAGS + CATEGORY)
// =====================================================



// =====================================================
// SAVE REFERENCE
// =====================================================
async function saveReference() {

  const btn = document.getElementById("saveRefBtn");
  btn.disabled = true;
  const originalText = btn.innerText;
  btn.innerText = "Saving...";

  const payload = {
    title: document.getElementById("ref-title").value.trim() || null,
    description: document.getElementById("ref-description").value.trim() || null,
    url: document.getElementById("ref-url").value.trim(),
    tags: window.tagifyInstance
      ? window.tagifyInstance.value.map(t => t.value)
      : [],
    category: document.getElementById("new-category").value.trim() ||
              document.getElementById("ref-category").value || null
  };

  if (!payload.url) {
    showToast("URL is required", "error");
    btn.disabled = false;
    btn.innerText = originalText;
    return;
  }

  try {
    const res = await fetch("/references/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error();

    showToast("Saved successfully ✓", "success");

    // Clear form
    document.getElementById("ref-title").value = "";
    document.getElementById("ref-description").value = "";
    document.getElementById("ref-url").value = "";
    document.getElementById("ref-category").value = "";
    document.getElementById("new-category").value = "";
    if (window.tagifyInstance) window.tagifyInstance.removeAllTags();

  } catch (err) {
    showToast("Save failed", "error");
  }

  btn.disabled = false;
  btn.innerText = originalText;
}


// =====================================================
// SMOOTH TOAST SYSTEM
// =====================================================
function showToast(message, type = "info") {

  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerText = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("show");
  }, 10);

  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

async function autoFetchMetadata() {

  const url = document.getElementById("ref-url").value.trim();
  if (!url) return;

  const aiEnabled = document.getElementById("enable-ai")?.checked;

  showToast("Fetching metadata...", "info");

  try {

    const res = await fetch("/references/metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        use_ai: aiEnabled
      })
    });

    if (!res.ok) throw new Error();

    const data = await res.json();

    // Always fill title
    if (data.title && !document.getElementById("ref-title").value) {
      document.getElementById("ref-title").value = data.title;
    }

    // Only fill tags if AI enabled
    if (aiEnabled && data.tags && window.tagifyInstance) {
      window.tagifyInstance.removeAllTags();
      window.tagifyInstance.addTags(data.tags);
    }

    // Only fill category if AI enabled
    if (aiEnabled && data.category) {
      const categorySelect = document.getElementById("ref-category");
      if (categorySelect) {
        categorySelect.value = data.category;
      }
    }

    showToast("Metadata loaded ✓", "success");

  } catch (err) {
    showToast("Metadata fetch failed", "error");
  }
}