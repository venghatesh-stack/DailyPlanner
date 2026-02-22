// ==========================================================
// REFERENCE APP MODULE
// ==========================================================

(function () {

  // ==========================================================
  // GLOBALS
  // ==========================================================

  window.tagifyInstance = null;
  let quillInstance = null;

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

  toast.innerHTML = `
    <div class="toast-message">${message}</div>
    <div class="toast-progress"></div>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("show");
  }, 10);

  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
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
      description: quillInstance
        ? quillInstance.root.innerHTML
        : null,
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
      ${payload.description
        ? `<div class="ref-content">${payload.description}</div>`
        : ""}
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

      if (quillInstance) quillInstance.setContents([]);
      if (window.tagifyInstance) window.tagifyInstance.removeAllTags();
      // Clear input fields
      if ($("ref-title")) $("ref-title").value = "";
      if ($("ref-url")) $("ref-url").value = "";
      if ($("ref-category")) $("ref-category").value = "";
      if ($("new-category")) $("new-category").value = "";
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
    if (state.selectedCategory)
      url += `&category=${encodeURIComponent(state.selectedCategory)}`;
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
        ${ref.description
          ? `<div class="ref-content">${ref.description}</div>`
          : ""}
        <div class="ref-meta">
         ${(ref.tags || []).map(tag =>
            `<span class="tag clickable-tag" data-tag="${tag}">
              ${tag}
            </span>`
          ).join("")}
          ${ref.category
            ? `<span class="category">${ref.category}</span>`
            : ""}
        </div>
      `;

      container.appendChild(item);
      item.querySelectorAll(".clickable-tag").forEach(el => {
      el.addEventListener("click", function () {
        const tag = this.dataset.tag;

        if (!state.selectedTags.includes(tag)) {
          state.selectedTags.push(tag);
        }

        resetAndReload();
      });
    });
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
    const groupedTags = await res.json();

    container.innerHTML = "";

    Object.keys(groupedTags)
      .sort()
      .forEach(groupName => {

        const groupWrapper = document.createElement("div");
        groupWrapper.className = "tag-group";

        const header = document.createElement("div");
        header.className = "tag-group-header";
        header.innerHTML = `📁 ${groupName}`;

        const content = document.createElement("div");
        content.className = "tag-group-content";

        const groupTags = Object.keys(groupedTags[groupName]);

        if (groupTags.some(tag => state.selectedTags.includes(tag))) {
          content.classList.add("open");
        }

        header.addEventListener("click", () => {
          content.classList.toggle("open");
        });

        groupTags.sort().forEach(tag => {

          const span = document.createElement("span");
          span.className = "tag-cloud-item";
          span.innerText = `# ${tag} (${groupedTags[groupName][tag]})`;

          if (state.selectedTags.includes(tag)) {
            span.classList.add("active");
          }

          span.onclick = function (e) {
            e.stopPropagation();

            span.classList.toggle("active");

            if (state.selectedTags.includes(tag)) {
              state.selectedTags =
                state.selectedTags.filter(t => t !== tag);
            } else {
              state.selectedTags.push(tag);
            }

            resetAndReload();
          };

          content.appendChild(span);
        });

        groupWrapper.appendChild(header);
        groupWrapper.appendChild(content);
        container.appendChild(groupWrapper);
      });
  }

  // ==========================================================
  // METADATA
  // ==========================================================

  async function autoFetchMetadata() {
    const urlInput = $("ref-url");
    if (!urlInput || !urlInput.value.trim()) return;

    try {
      const res = await fetch("/references/metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlInput.value.trim() })
      });

      if (!res.ok) return;

      const data = await res.json();

      if ($("ref-title") && data.title) {
        $("ref-title").value = data.title;
      }

      if (quillInstance && data.description) {
        quillInstance.root.innerHTML = data.description;
      }

    } catch (err) {
      console.error("Metadata fetch failed:", err);
    }
  }

  // ==========================================================
  // INIT
  // ==========================================================

  document.addEventListener("DOMContentLoaded", function () {
    const params = new URLSearchParams(window.location.search);

    const initialTag = params.get("tag");
    const initialCategory = params.get("category");

    if (initialTag) {
      state.selectedTags = [initialTag.toLowerCase()];
    }

    if (initialCategory) {
      state.selectedCategory = initialCategory;
    }
    // Quill init (only once)
    const editor = $("ref-editor");
    if (editor) {
      quillInstance = new Quill("#ref-editor", {
        theme: "snow",
        modules: {
          toolbar: [
            [{ header: [1, 2, false] }],
            ["bold", "italic"],
            [{ list: "ordered" }, { list: "bullet" }],
            ["link"]
          ]
        }
      });
    }

    const tagInput = $("ref-tags");
    if (tagInput) {
      window.tagifyInstance = new Tagify(tagInput, {
        delimiters: ",",
        dropdown: { enabled: 0 }
      });
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

})();