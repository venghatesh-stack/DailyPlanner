// ==========================================================
// GLOBAL STATE
// ==========================================================

window.tagifyInstance = null;

const state = {
  currentPage: 1,
  selectedTags: [],
  searchQuery: "",
  sortOption: "created_at_desc",
  isLoading: false,
  hasMore: true,
  totalRendered: 0
};

const referenceCache = {};
let searchTimeout = null;
let scrollTimeout = null;

// ==========================================================
// UTILITIES
// ==========================================================

function $(id) {
  return document.getElementById(id);
}

function showToast(message, type = "info", duration = 2500) {
  const container = $("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerText = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("fade-out");
    setTimeout(() => toast.remove(), 400);
  }, duration);
}

function clearCache() {
  Object.keys(referenceCache).forEach(k => delete referenceCache[k]);
}

function normalizedTagKey() {
  return [...state.selectedTags].sort().join(",");
}

// ==========================================================
// SAVE REFERENCE
// ==========================================================

async function saveReference() {
  const payload = {
    title: $("ref-title")?.value.trim() || null,
    description: $("ref-description")?.value.trim() || null,
    url: $("ref-url")?.value.trim(),
    tags: window.tagifyInstance
      ? window.tagifyInstance.value.map(t => t.value)
      : [],
    category:
      $("new-category")?.value.trim() ||
      $("ref-category")?.value ||
      null
  };

  if (!payload.url) {
    showToast("URL is required", "error");
    return;
  }

  const container = $("referenceList");
  if (!container) return;

  showToast("Saving reference...", "info", 1500);

  const tempItem = document.createElement("div");
  tempItem.className = "ref-item saving";
  tempItem.innerHTML = `
    <h4><a href="${payload.url}" target="_blank">
      ${payload.title || payload.url}
    </a></h4>
    ${payload.description ? `<p>${payload.description}</p>` : ""}
  `;
  container.prepend(tempItem);

  try {
    const res = await fetch("/references/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error("Save failed");

    tempItem.classList.remove("saving");
    showToast("Saved successfully ✓", "success");

    // Clear form
    ["ref-title", "ref-description", "ref-url", "ref-category", "new-category"]
      .forEach(id => { if ($(id)) $(id).value = ""; });

    if (window.tagifyInstance) window.tagifyInstance.removeAllTags();

    resetAIAssist();
    clearCache();
    resetAndReload();
    loadTagCloud();

  } catch (err) {
    tempItem.remove();
    showToast("Save failed. Please try again.", "error");
  }
}

// ==========================================================
// AI RESET
// ==========================================================

function resetAIAssist() {
  const aiInput = $("ai-query");
  const aiPreview = $("ai-preview");

  if (aiInput) {
    aiInput.value = "";
    aiInput.focus();
  }

  if (aiPreview) aiPreview.innerHTML = "";
}

// ==========================================================
// SKELETON
// ==========================================================

function showSkeletonLoader() {
  const container = $("referenceList");
  if (!container || container.querySelector(".ref-skeleton")) return;

  for (let i = 0; i < 5; i++) {
    const skeleton = document.createElement("div");
    skeleton.className = "ref-skeleton";
    container.appendChild(skeleton);
  }
}

function removeSkeletonLoader() {
  document.querySelectorAll(".ref-skeleton").forEach(el => el.remove());
}

// ==========================================================
// LOAD REFERENCES
// ==========================================================

async function loadReferences() {
  if (state.isLoading || !state.hasMore) return;

  state.isLoading = true;

  const container = $("referenceList");
  if (!container) return;

  const cacheKey =
    `${state.currentPage}-${normalizedTagKey()}-${state.searchQuery}-${state.sortOption}`;

  if (referenceCache[cacheKey]) {
    renderReferences(referenceCache[cacheKey]);
    state.isLoading = false;
    return;
  }

  let url = `/references/list?page=${state.currentPage}&sort=${state.sortOption}`;

  if (state.selectedTags.length > 0)
    url += `&tags=${normalizedTagKey()}`;

  if (state.searchQuery)
    url += `&search=${encodeURIComponent(state.searchQuery)}`;

  showSkeletonLoader();

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("Server error");

    const data = await res.json();

    removeSkeletonLoader();
    referenceCache[cacheKey] = data;
    renderReferences(data);

  } catch (err) {
    removeSkeletonLoader();
    console.error("Load failed:", err);
  }

  state.isLoading = false;
}

// ==========================================================
// RENDER
// ==========================================================

function renderReferences(data) {
  const container = $("referenceList");
  if (!container) return;

  if (!data.items || data.items.length === 0) {
    state.hasMore = false;

    if (state.currentPage === 1)
      container.innerHTML = "<div class='empty-state'>No results found.</div>";

    return;
  }

  data.items.forEach(ref => {
    const item = document.createElement("div");
    item.className = "ref-item";

    item.innerHTML = `
      <h4><a href="${ref.url}" target="_blank">
        ${ref.title || ref.url}
      </a></h4>
      ${ref.description ? `<p>${ref.description}</p>` : ""}
      <div class="ref-meta">
        ${(ref.tags || []).map(tag =>
          `<span class="tag">${tag}</span>`
        ).join("")}
        ${ref.category ? `<span class="category">${ref.category}</span>` : ""}
      </div>
    `;

    container.appendChild(item);
    state.totalRendered++;
  });

  state.hasMore = data.has_more;

  const resultCount = $("resultCount");
  if (resultCount)
    resultCount.innerText = `Showing ${state.totalRendered} results`;
}

// ==========================================================
// RESET
// ==========================================================

function resetAndReload() {
  state.currentPage = 1;
  state.hasMore = true;
  state.totalRendered = 0;

  const container = $("referenceList");
  if (container) container.innerHTML = "";

  loadReferences();
}

// ==========================================================
// TAG CLOUD
// ==========================================================

async function loadTagCloud() {
  const container = $("tagCloud");
  if (!container) return;

  const res = await fetch("/references/tags");
  const tags = await res.json();

  container.innerHTML = "";

  Object.keys(tags).sort().forEach(tag => {
    const span = document.createElement("span");
    span.className = "tag-cloud-item";
    span.innerText = `# ${tag} (${tags[tag]})`;

    span.onclick = function () {
      span.classList.toggle("active");

      if (state.selectedTags.includes(tag))
        state.selectedTags = state.selectedTags.filter(t => t !== tag);
      else
        state.selectedTags.push(tag);

      span.classList.add("pulse");
      setTimeout(() => span.classList.remove("pulse"), 300);

      resetAndReload();
    };

    container.appendChild(span);
  });
}

// ==========================================================
// INIT
// ==========================================================

document.addEventListener("DOMContentLoaded", function () {

  const tagInput = $("ref-tags");
  if (tagInput) {
    window.tagifyInstance = new Tagify(tagInput, {
      delimiters: ",",
      dropdown: { enabled: 0 }
    });
  }

  const aiToggle = $("enable-ai");
  if (aiToggle) {
    const saved = localStorage.getItem("ai_enabled");
    if (saved !== null) aiToggle.checked = saved === "true";
    aiToggle.addEventListener("change", () =>
      localStorage.setItem("ai_enabled", aiToggle.checked)
    );
  }

  $("saveRefBtn")?.addEventListener("click", saveReference);

  $("ref-url")?.addEventListener("change", autoFetchMetadata);

  const searchInput = $("searchInput");
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        state.searchQuery = this.value.trim();
        resetAndReload();
      }, 400);
    });
  }

  $("sortSelect")?.addEventListener("change", function () {
    state.sortOption = this.value;
    resetAndReload();
  });

  $("resetFilterBtn")?.addEventListener("click", function () {
    state.selectedTags = [];
    state.searchQuery = "";
    state.sortOption = "created_at_desc";

    if ($("searchInput")) $("searchInput").value = "";
    if ($("sortSelect")) $("sortSelect").value = "created_at_desc";

    document.querySelectorAll(".tag-cloud-item")
      .forEach(el => el.classList.remove("active"));

    resetAndReload();
  });

  loadTagCloud();
  loadReferences();
});

// ==========================================================
// INFINITE SCROLL
// ==========================================================

window.addEventListener("scroll", function () {
  if (scrollTimeout) clearTimeout(scrollTimeout);

  scrollTimeout = setTimeout(() => {
    if (state.isLoading || !state.hasMore) return;

    const scrollPosition = window.innerHeight + window.scrollY;
    const threshold = document.documentElement.scrollHeight - 250;

    if (scrollPosition >= threshold) {
      state.currentPage++;
      loadReferences();
    }
  }, 120);
});