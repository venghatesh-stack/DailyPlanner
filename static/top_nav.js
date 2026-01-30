function openSummary() {
  const modal = document.getElementById("summary-modal");
  const content = document.getElementById("summary-content");

  if (!modal || !content) {
    console.warn("Summary modal elements missing");
    return;
  }

  fetch(`/day/summary?date=${document.body.dataset.planDate}`)
    .then(r => r.text())
    .then(html => {
      content.innerHTML = html;
      modal.style.display = "flex";
    })
    .catch(err => {
      console.error(err);
      content.innerHTML = "<p>Failed to load summary</p>";
      modal.style.display = "flex";
    });
}

function closeSummary() {
  const modal = document.getElementById("summary-modal");
  if (modal) modal.style.display = "none";
}
