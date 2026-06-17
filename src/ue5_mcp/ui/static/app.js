const MODE_LABELS = {
  editor: "Live Editor",
  mock: "Mock mode",
  filesystem: "Filesystem scan",
  disconnected: "Disconnected",
};

const STATUS_LABELS = {
  editor: "Connected to editor",
  mock: "Mock mode active",
  filesystem: "Project on disk",
  disconnected: "Not connected",
};

function truncateDescription(text, maxLength = 220) {
  const firstLine = text.split("\n")[0].trim();
  if (firstLine.length <= maxLength) return firstLine;
  return `${firstLine.slice(0, maxLength - 1)}…`;
}

function setStatusPill(mode, connected) {
  const pill = document.getElementById("status-pill");
  const label = document.getElementById("status-label");

  pill.className = "status-pill";
  if (mode === "editor" || mode === "mock") {
    pill.classList.add("connected");
  } else if (mode === "filesystem") {
    pill.classList.add("partial");
  } else {
    pill.classList.add("disconnected");
  }

  label.textContent = STATUS_LABELS[mode] || (connected ? "Connected" : "Not connected");
}

function renderConnection(status) {
  const { project, mode, config } = status;

  document.getElementById("project-name").textContent = project;
  document.getElementById("connection-mode").textContent = MODE_LABELS[mode] || mode;
  document.getElementById("editor-endpoint").textContent = `${config.host}:${config.http_port}`;
  document.getElementById("project-path").textContent = config.project_path || "Not set";

  setStatusPill(mode, status.connected);
}

function renderTools(tools) {
  const container = document.getElementById("tools-container");
  const countEl = document.getElementById("tool-count");

  countEl.textContent = tools.length ? `(${tools.length})` : "";

  if (!tools.length) {
    container.className = "loading";
    container.textContent = "No tools registered.";
    return;
  }

  container.className = "tools-grid";
  container.innerHTML = tools
    .map(
      (tool) => `
    <article class="tool-card">
      <div class="tool-name">${escapeHtml(tool.name)}</div>
      <p class="tool-description">${escapeHtml(truncateDescription(tool.description))}</p>
    </article>
  `
    )
    .join("");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function refresh() {
  try {
    const [statusRes, toolsRes] = await Promise.all([
      fetch("/api/status"),
      fetch("/api/tools"),
    ]);

    if (!statusRes.ok || !toolsRes.ok) {
      throw new Error("Failed to load dashboard data");
    }

    const status = await statusRes.json();
    const toolsPayload = await toolsRes.json();

    renderConnection(status);
    renderTools(toolsPayload.tools);
  } catch (error) {
    const container = document.getElementById("tools-container");
    container.className = "error";
    container.textContent = `Could not reach the server: ${error.message}`;

    setStatusPill("disconnected", false);
    document.getElementById("status-label").textContent = "Server error";
  }
}

refresh();
setInterval(refresh, 10_000);
