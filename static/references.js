window.tagifyInstance = null;

let currentPage = 1;
let selectedTags = [];
let searchQuery = "";
let sortOption = "created_at_desc";
let isLoading = false;
let hasMore = true;

const referenceCache = {};
async function saveReference() {

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

  if (!payload.url) return;

  const container = document.getElementById("referenceList");

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

    if (!res.ok) throw new Error();

  tempItem.classList.remove("saving");

  // Clear form
  document.getElementById("ref-title").value = "";
  document.getElementById("ref-description").value = "";
  document.getElementById("ref-url").value = "";
  document.getElementById("ref-category").value = "";
  document.getElementById("new-category").value = "";
  if (window.tagifyInstance) window.tagifyInstance.removeAllTags();

  // Clear cache
  Object.keys(referenceCache).forEach(k => delete referenceCache[k]);

  // Optional: reload first page fresh
  resetAndReload();
  loadTagCloud();

    // 🔥 Clear cache after save
    Object.keys(referenceCache).forEach(k => delete referenceCache[k]);
    loadTagCloud();
  } catch (err) {
    tempItem.remove();
    alert("Save failed");
  }
}
function showSkeletonLoader() {
  const container = document.getElementById("referenceList");

  // Prevent duplicates
  if (container.querySelector(".ref-skeleton")) return;

  for (let i = 0; i < 5; i++) {
    const skeleton = document.createElement("div");
    skeleton.className = "ref-skeleton";
    container.appendChild(skeleton);
  }
}



function removeSkeletonLoader() {
  document.querySelectorAll(".ref-skeleton").forEach(el => el.remove());
}
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
  // URL AUTO METADATA
  // -----------------------------
  const refUrlInput = document.getElementById("ref-url");
  if (refUrlInput) {
    refUrlInput.addEventListener("change", autoFetchMetadata);
  }

  // -----------------------------
  // LOAD INITIAL DATA
  // -----------------------------
  loadTagCloud();
  loadReferences();

  
 let searchTimeout = null;

document.getElementById("searchInput").addEventListener("input", function () {

  clearTimeout(searchTimeout);

  searchTimeout = setTimeout(() => {
    searchQuery = this.value.trim();
    currentPage = 1;
    hasMore = true;
    document.getElementById("referenceList").innerHTML = "";
    loadReferences();
  }, 400); // 400ms delay

});

document.getElementById("sortSelect").addEventListener("change", function () {
  sortOption = this.value;
  currentPage = 1;
  hasMore = true;
  document.getElementById("referenceList").innerHTML = "";
  loadReferences();
});

document.getElementById("resetFilterBtn").addEventListener("click", function () {
  selectedTags = [];
  searchQuery = "";
  sortOption = "created_at_desc";
  currentPage = 1;
  hasMore = true;

  document.getElementById("searchInput").value = "";
  document.getElementById("sortSelect").value = "created_at_desc";

  document.querySelectorAll(".tag-cloud-item")
    .forEach(el => el.classList.remove("active"));

  document.getElementById("referenceList").innerHTML = "";
  loadReferences();
});
});
async function loadReferences() {

  if (isLoading || !hasMore) return;
  isLoading = true;

  const container = document.getElementById("referenceList");

  const cacheKey = `${currentPage}-${selectedTags.join(",")}-${searchQuery}-${sortOption}`;

  // ✅ Use cache if exists
  if (referenceCache[cacheKey]) {
    renderReferences(referenceCache[cacheKey]);
    isLoading = false;
    return;
  }

  let url = `/references/list?page=${currentPage}&sort=${sortOption}`;

  if (selectedTags.length > 0) {
    url += `&tags=${selectedTags.join(",")}`;
  }

  if (searchQuery) {
    url += `&search=${encodeURIComponent(searchQuery)}`;
  }

  showSkeletonLoader();

  try {
    const res = await fetch(url);
    const data = await res.json();

    removeSkeletonLoader();

    referenceCache[cacheKey] = data;

    renderReferences(data);

  } catch (err) {
    removeSkeletonLoader();
    console.error("Load failed", err);
  }

  isLoading = false;
}

function renderReferences(data) {

  const container = document.getElementById("referenceList");

  if (!data.items || data.items.length === 0) {
    hasMore = false;
    if (currentPage === 1) {
      container.innerHTML = "<div class='empty-state'>No results found.</div>";
    }
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
  });

  hasMore = data.has_more;

  // 🔥 Live Count Update
  document.getElementById("resultCount").innerText =
    `Showing ${document.querySelectorAll(".ref-item").length} results`;
}
function resetAndReload() {
  currentPage = 1;
  hasMore = true;
  document.getElementById("referenceList").innerHTML = "";
  loadReferences();
}
async function loadTagCloud() {

  const res = await fetch("/references/tags");
  const tags = await res.json();

  const container = document.getElementById("tagCloud");
  container.innerHTML = "";

  Object.keys(tags).sort().forEach(tag => {

    const span = document.createElement("span");
    span.className = "tag-cloud-item";
    span.innerText = `# ${tag} (${tags[tag]})`;

    span.onclick = function () {

      span.classList.toggle("active");

      if (selectedTags.includes(tag)) {
        selectedTags = selectedTags.filter(t => t !== tag);
      } else {
        selectedTags.push(tag);
      }

      span.classList.add("pulse");
      setTimeout(() => span.classList.remove("pulse"), 300);

      resetAndReload();
    };

    container.appendChild(span);
  });
}
let scrollTimeout = null;

window.addEventListener("scroll", function () {

  if (scrollTimeout) clearTimeout(scrollTimeout);

  scrollTimeout = setTimeout(() => {

    if (isLoading || !hasMore) return;

    const scrollPosition = window.innerHeight + window.scrollY;
    const threshold = document.documentElement.scrollHeight - 250;

    if (scrollPosition >= threshold) {
      currentPage++;
      loadReferences();
    }

  }, 120);

});