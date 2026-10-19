const form = document.querySelector("#paper-search");
const questionInput = document.querySelector("#research-query");
const submitButton = document.querySelector("#submit-button");
const errorBox = document.querySelector("#search-error");
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;

function readOptions() {
  const year = (selector) => document.querySelector(selector).value ? Number(document.querySelector(selector).value) : null;
  return {
    field: document.querySelector("#research-field").value,
    review_goal: document.querySelector("#review-goal").value,
    filters: {
      year_from: year("#year-from"), year_to: year("#year-to"),
      sources: [...document.querySelectorAll("[name=source-filter]:checked")].map((option) => option.value),
      full_text_only: document.querySelector("#full-text-only").checked,
    },
  };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  errorBox.hidden = true;
  submitButton.disabled = true;
  submitButton.innerHTML = 'Starting research <span class="button-spinner" aria-hidden="true"></span>';
  try {
    const response = await fetch("/research", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken, Accept: "application/json" },
      body: JSON.stringify({ question: questionInput.value.trim(), options: readOptions() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Could not start research (${response.status})`);
    window.location.assign(`${data.result_url}/results`);
  } catch (error) {
    errorBox.textContent = error.message || String(error);
    errorBox.hidden = false;
    submitButton.disabled = false;
    submitButton.innerHTML = 'Search papers <span aria-hidden="true">↗</span>';
  }
});

questionInput.addEventListener("input", () => { errorBox.textContent = ""; errorBox.hidden = true; });
document.querySelector("#get-started").addEventListener("click", () => {
  form.scrollIntoView({ behavior: "smooth", block: "center" });
  questionInput.focus({ preventScroll: true });
});
