const form = document.querySelector("#agent-form");
const tokenInput = document.querySelector("#token");
const repoInput = document.querySelector("#repo");
const issueInput = document.querySelector("#issue");
const localPathInput = document.querySelector("#local-path");
const applyFixInput = document.querySelector("#apply-fix");
const useDockerInput = document.querySelector("#use-docker");
const runButton = document.querySelector("#run-button");
const toggleToken = document.querySelector("#toggle-token");
const formError = document.querySelector("#form-error");
const progressPanel = document.querySelector("#progress-panel");
const progressTitle = document.querySelector("#progress-title");
const progressSubtitle = document.querySelector("#progress-subtitle");
const runStatus = document.querySelector("#run-status");
const stepsEl = document.querySelector("#steps");
const resultPanel = document.querySelector("#result-panel");
const logsPanel = document.querySelector("#logs-panel");
const logsEl = document.querySelector("#logs");

let pollTimer = null;

function isReady() {
  return tokenInput.value.trim() && repoInput.value.trim() && Number(issueInput.value) > 0;
}

function updateButtonState() {
  runButton.disabled = !isReady() || runButton.dataset.running === "true";
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderSteps(stages = []) {
  stepsEl.innerHTML = stages
    .map((stage) => {
      let icon = "○";
      if (stage.status === "completed") icon = "✓";
      if (stage.status === "failed") icon = "✗";
      if (stage.status === "active") icon = '<span class="spinner" aria-label="Running"></span>';

      return `
        <div class="step ${stage.status}">
          <span class="status-icon">${icon}</span>
          <span>${escapeHtml(stage.label)}</span>
        </div>
      `;
    })
    .join("");
}

function renderLogs(logs = []) {
  logsPanel.classList.remove("hidden");
  logsEl.textContent = logs.join("\n");
}

function renderResult(job) {
  if (job.status === "failed") {
    resultPanel.innerHTML = `
      <h2 class="error">✗ Agent failed</h2>
      <div class="summary-box">
        <h3>Error</h3>
        <pre>${escapeHtml(job.error || "Unknown error")}</pre>
      </div>
    `;
    resultPanel.classList.remove("hidden");
    return;
  }

  const result = job.result;
  if (!result) return;

  const issue = result.issue || {};
  const candidates = result.candidateFiles || [];
  const relevantFile = result.targetFile || candidates[0]?.relative_path || candidates[0]?.path || "Not identified";
  const patch = result.patch || result.patchResult?.diff || "";
  const proposalPreview = patch || JSON.stringify(result.proposal || {}, null, 2);
  const tests = result.tests;

  const testsHtml = tests
    ? `
      <div class="summary-box">
        <h3>Tests</h3>
        <p class="${tests.passed ? "success" : "error"}">
          ${tests.passed ? "✓" : "✗"} ${tests.passed ? "Tests passed" : "Tests failed"}
        </p>
        <pre>${escapeHtml(formatTestSummary(tests))}</pre>
      </div>
    `
    : `
      <div class="summary-box">
        <h3>Tests</h3>
        <p>No tests were executed. Enable "Apply fix and run tests" to validate the patch.</p>
      </div>
    `;

  resultPanel.innerHTML = `
    <div class="result-grid">
      <div>
        <h2 class="success">✅ Agent completed</h2>
        <p class="issue-title">Issue #${escapeHtml(issue.number || "")}</p>
        <p>${escapeHtml(issue.title || "Untitled issue")}</p>
      </div>

      <div class="summary-box">
        <h3>Relevant file</h3>
        <pre>${escapeHtml(relevantFile)}</pre>
      </div>

      <div class="summary-box">
        <h3>AI proposed fix</h3>
        <pre class="${patch ? "diff" : ""}">${escapeHtml(proposalPreview || "No proposed fix returned.")}</pre>
      </div>

      ${testsHtml}
    </div>
  `;
  resultPanel.classList.remove("hidden");
}

function formatTestSummary(tests) {
  const lines = [];
  if (tests.passedCount !== null && tests.passedCount !== undefined) {
    lines.push(`✓ ${tests.passedCount} tests passed`);
  }
  if (tests.failedCount !== null && tests.failedCount !== undefined) {
    lines.push(`${tests.failedCount > 0 ? "✗" : "✓"} ${tests.failedCount} tests failed`);
  }
  if (!lines.length) {
    lines.push(tests.passed ? "✓ Tests passed" : "✗ Tests failed");
  }
  if (tests.output) {
    lines.push("", tests.output);
  }
  return lines.join("\n");
}

async function pollRun(id) {
  const response = await fetch(`/api/runs/${id}`);
  if (!response.ok) throw new Error("Could not fetch run status.");
  const job = await response.json();

  progressPanel.classList.remove("hidden");
  runStatus.textContent = job.status;
  renderSteps(job.stages);
  renderLogs(job.logs);

  if (job.status === "completed" || job.status === "failed") {
    clearInterval(pollTimer);
    pollTimer = null;
    runButton.dataset.running = "false";
    updateButtonState();
    progressTitle.textContent = job.status === "completed" ? "Agent finished" : "Agent stopped";
    progressSubtitle.textContent =
      job.status === "completed" ? "Review the proposed fix below." : "Check the error and logs below.";
    renderResult(job);
  }
}

form.addEventListener("input", updateButtonState);

toggleToken.addEventListener("click", () => {
  const showing = tokenInput.type === "text";
  tokenInput.type = showing ? "password" : "text";
  toggleToken.setAttribute("aria-label", showing ? "Show token" : "Hide token");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  resultPanel.classList.add("hidden");
  logsPanel.classList.add("hidden");
  progressPanel.classList.remove("hidden");
  progressTitle.textContent = "Running AI Agent...";
  progressSubtitle.textContent = "This can take a minute while the LLM generates a fix.";
  runStatus.textContent = "Queued";
  stepsEl.innerHTML = "";
  logsEl.textContent = "";
  runButton.dataset.running = "true";
  updateButtonState();

  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: tokenInput.value.trim(),
        repo: repoInput.value.trim(),
        issue: Number(issueInput.value),
        localRepoPath: localPathInput.value.trim(),
        applyFix: applyFixInput.checked,
        useDocker: useDockerInput.checked,
      }),
    });

    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not start the agent.");

    await pollRun(payload.id);
    pollTimer = setInterval(() => pollRun(payload.id).catch(showError), 1200);
  } catch (error) {
    showError(error);
  }
});

function showError(error) {
  clearInterval(pollTimer);
  pollTimer = null;
  runButton.dataset.running = "false";
  updateButtonState();
  formError.textContent = error.message || "Something went wrong.";
}

updateButtonState();
