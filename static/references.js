let tagifyInstance;
async function saveReference() {
  const btn = document.getElementById("saveRefBtn");
  if (!btn) return;

  btn.disabled = true;
  const originalText = btn.innerText;
  btn.innerText = "Saving...";

  const selectedCategory = document.getElementById("ref-category")?.value;
  const newCategory = document.getElementById("new-category")?.value?.trim();

  const finalCategory = newCategory || selectedCategory || null;

  const payload = {
    title: document.getElementById("ref-title")?.value?.trim() || null,
    description: document.getElementById("ref-description")?.value?.trim() || null,
    url: document.getElementById("ref-url")?.value?.trim(),
    tags: tagifyInstance ? tagifyInstance.value : [],
    category: finalCategory
  };

  if (!payload.url) {
    alert("URL is required");
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

    btn.innerText = "Saved ✓";

    // Clear form fields
    // Clear form fields
    document.getElementById("ref-title").value = "";
    document.getElementById("ref-description").value = "";
    document.getElementById("ref-url").value = "";
    if (tagifyInstance) tagifyInstance.removeAllTags();
    document.getElementById("ref-category").value = "";
    document.getElementById("new-category").value = "";

    setTimeout(() => {
      btn.innerText = originalText;
      btn.disabled = false;
      location.reload();   // optional: remove if you implement live append
    }, 800);

  } catch (err) {
    console.error(err);
    btn.innerText = "Retry";
    btn.disabled = false;
  }
}


document.addEventListener("DOMContentLoaded", async () => {
  const btn = document.getElementById("saveRefBtn");
  if (btn) btn.addEventListener("click", saveReference);

  const tagInput = document.getElementById("ref-tags");
  if (!tagInput) return;

  // Fetch existing tags
  const res = await fetch("/api/tags");
  const existingTags = await res.json();

  tagifyInstance = new Tagify(tagInput, {
    whitelist: existingTags,
    dropdown: {
      enabled: 0,
      maxItems: 10
    }
  });
});
function searchReferences() {
  const query = document.getElementById("searchInput").value.trim();

  if (!query) {
    alert("Enter something to search");
    return;
  }

  fetch(`/search_references?q=${encodeURIComponent(query)}`)
    .then(response => response.json())
    .then(data => {
      const container = document.getElementById("searchResults");

      if (!data.results || data.results.length === 0) {
        container.innerHTML = "<p>No results found.</p>";
        return;
      }

      container.innerHTML = data.results.map(ref => `
        <div class="reference-item">
          <strong>${ref.title}</strong>
          <p>${ref.description || ""}</p>
        </div>
      `).join("");
    })
    .catch(error => {
      console.error("Search error:", error);
    });
}
document.getElementById("ref-url").addEventListener("blur", function() {
  const titleInput = document.getElementById("ref-title");
  if (!titleInput.value && this.value) {
    try {
      const url = new URL(this.value);
      titleInput.value = url.hostname.replace("www.", "");
    } catch (e) {}
  }
});