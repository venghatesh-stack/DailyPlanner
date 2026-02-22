window.tagifyInstance = null;
let currentTag = null;
let currentPage = 1;
let selectedTags = [];
let searchQuery = "";
let sortOption = "created_at_desc";
let isLoading = false;
let hasMore = true;
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

  if (isLoading) return;

  isLoading = true;

  let url = `/references/list?page=${currentPage}&sort=${sortOption}`;

  if (selectedTags.length > 0) {
    url += `&tags=${selectedTags.join(",")}`;
  }

  if (searchQuery) {
    url += `&search=${encodeURIComponent(searchQuery)}`;
  }

  const res = await fetch(url);
  const data = await res.json();

 

  const container = document.getElementById("referenceList");
   if (data.length === 0) {
    hasMore = false;
    if (currentPage === 1 && data.length === 0) {
        document.getElementById("referenceList").innerHTML =
          "<div class='empty-state'>No results found.</div>";
      }
    isLoading = false;    
    return;
   }
  data.forEach(ref => {

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

  if (selectedTags.includes(tag)) {
    selectedTags = selectedTags.filter(t => t !== tag);
    span.classList.remove("active");
  } else {
    selectedTags.push(tag);
    span.classList.add("active");
  }

  currentPage = 1;
  hasMore = true;
  document.getElementById("referenceList").innerHTML = "";
  loadReferences();
};

    container.appendChild(span);
  });
}
window.addEventListener("scroll", function () {

  if (isLoading || !hasMore) return;

  const scrollPosition = window.innerHeight + window.scrollY;
  const threshold = document.body.offsetHeight - 200;

  if (scrollPosition >= threshold) {
    currentPage++;
    loadReferences();
  }

});