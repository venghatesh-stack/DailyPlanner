function openSummary() {
  const date = document.body.dataset.planDate;
  window.location.href = `/summary?view=daily&date=${date}`;
}


function closeSummary() {
  const modal = document.getElementById("summary-modal");
  if (modal) modal.style.display = "none";
}
