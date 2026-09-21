(() => {
"use strict";

let token = localStorage.getItem("codeforge_token") || "";
let currentProjectId = localStorage.getItem("codeforge_project_id") || "";
let projects = [];
let editor = null;
let diffEditor = null;
let editorReady = false;
let currentFilePath = "";
let tabs = new Map();
let activeTab = "";
let pendingDiffs = [];
let activeDiff = null;
let agentRunning = false;
let resizeState = null;

const $ = id => document.getElementById(id);
const authOverlay = $("auth-overlay");
const fileTree = $("file-tree");
const chatHistory = $("chat-history");
const chatInput = $("chat-input");
const sendBtn = $("send-chat-btn");
const terminalOutput = $("terminal-output");
const agentOutput = $("agent-output");
const workspaceStatus = $("workspace-status");
const projectModal = $("project-modal");
const settingsModal = $("settings-modal");
const commandPalette = $("command-palette");
const diffModal = $("diff-modal");

const defaultSettings = { fontSize: 13, explorerWidth: 250, chatWidth: 380, minimap: false };
let settings = loadSettings();

function loadSettings() {
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem("codeforge_settings") || "{}") }; }
  catch { return { ...defaultSettings }; }
}

function persistSettings() {
  localStorage.setItem("codeforge_settings", JSON.stringify(settings));
}

function setStatus(text, ok = true) {
  workspaceStatus.textContent = text;
  const dot = workspaceStatus.previousElementSibling;
  if (dot) dot.style.background = ok ? "var(--green)" : "#f59e0b";
}

function setAuthenticatedState(authenticated) {
  authOverlay.style.display = authenticated ? "none" : "flex";
  document.body.classList.toggle("authenticated", authenticated);
  $("logout-btn").disabled = !authenticated;
  $("load-projects-btn").disabled = !authenticated;
  $("project-switcher").disabled = !authenticated;
  $("refresh-tree-btn").disabled = !authenticated;
  $("settings-btn").disabled = !authenticated;
  $("command-palette-btn").disabled = !authenticated;
  if (!authenticated) {
    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatInput.placeholder = "Sign in and select a project to chat...";
  } else if (!currentProjectId) {
    chatInput.disabled = true;
    sendBtn.disabled = true;
    chatInput.placeholder = "Select a project to start chatting...";
  }
}

function setChatEnabled(enabled) {
  const canChat = Boolean(enabled && token && currentProjectId);
  chatInput.disabled = !canChat;
  sendBtn.disabled = !canChat || agentRunning;
  chatInput.placeholder = canChat ? "Ask CodeForge to build..." : "Select a project to start chatting...";
  chatInput.setAttribute("aria-disabled", String(!canChat));
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", "Bearer " + token);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    logout(false);
    throw new Error("Your session has expired. Please sign in again.");
  }
  return response;
}

async function readError(response, fallback) {
  try {
    const data = await response.json();
    return data.detail || data.message || fallback;
  } catch { return fallback; }
}

function showAuthError(message) { $("auth-error").textContent = message || ""; }

function logout(showOverlay = true) {
  token = "";
  currentProjectId = "";
  currentFilePath = "";
  activeTab = "";
  tabs.clear();
  localStorage.removeItem("codeforge_token");
  localStorage.removeItem("codeforge_project_id");
  projects = [];
  $("current-project").textContent = "No Project Selected";
  $("editor-tabs").innerHTML = "";
  fileTree.innerHTML = "";
  if (editorReady) editor.setValue("// Welcome to CodeForge\n// Sign in and select a project to start.\n");
  chatHistory.innerHTML = '<div class="welcome-msg"><div class="welcome-icon">✦</div><h2>What are we building?</h2><p>Sign in and select a project to start.</p></div>';
  setAuthenticatedState(false);
  if (showOverlay) $("email-input").focus();
}

async function login() {
  const email = $("email-input").value.trim();
  const password = $("password-input").value;
  if (!email || !password) return showAuthError("Enter your email and password.");

  const button = $("login-btn");
  button.disabled = true;
  button.innerHTML = "Signing in…";
  showAuthError("");

  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    if (!response.ok) return showAuthError(await readError(response, "Login failed."));
    const data = await response.json();
    if (!data.access_token) return showAuthError("Login succeeded but no access token was returned.");
    token = data.access_token;
    localStorage.setItem("codeforge_token", token);
    setAuthenticatedState(true);
    await loadProjects(true);
  } catch (error) {
    showAuthError(error.message || "Unable to connect to CodeForge.");
  } finally {
    button.disabled = false;
    button.innerHTML = 'Sign in <span>→</span>';
  }
}

function handleAuthKeydown(event) {
  if (event.key === "Enter") {
    event.preventDefault();
    login();
  }
}

async function loadProjects(openModal = false) {
  if (!token) return;
  setStatus("Loading projects…");
  try {
    const response = await api("/api/projects/", { cache: "no-store" });
    if (!response.ok) {
      const message = await readError(response, "Could not load projects.");
      setStatus("Project load failed", false);
      if (openModal) {
        $("project-error").textContent = message;
        openProjectModal();
      }
      appendSysMsg(message);
      return;
    }
    projects = await response.json();
    if (!Array.isArray(projects)) projects = [];

    if (!projects.length) {
      currentProjectId = "";
      localStorage.removeItem("codeforge_project_id");
      $("current-project").textContent = "No Project Selected";
      chatInput.disabled = true;
      sendBtn.disabled = true;
      if (openModal) $("project-error").textContent = "No projects yet — create your first project below.";
      setStatus("No project selected");
      if (openModal) openProjectModal();
      return;
    }

    const saved = projects.find(p => String(p.id) === String(currentProjectId));
    await selectProject(saved || projects[0], false);
    if (openModal) {
      renderProjectList();
      openProjectModal();
    }
  } catch (error) {
    setStatus("Project load failed", false);
    if (openModal) {
      $("project-error").textContent = error.message;
      openProjectModal();
    }
    appendSysMsg(error.message || "Could not load projects.");
  }
}

async function createProject() {
  const input = $("new-project-name");
  const name = input.value.trim();
  if (!name) { $("project-error").textContent = "Enter a project name."; input.focus(); return; }

  const button = $("create-project-btn");
  button.disabled = true;
  $("project-error").textContent = "";
  try {
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 50) || "project";
    const response = await api("/api/projects/", {
      method: "POST",
      body: JSON.stringify({ name, slug, description: "" })
    });
    if (!response.ok) {
      $("project-error").textContent = await readError(response, "Could not create project.");
      return;
    }
    const project = await response.json();
    if (!project || !project.id) throw new Error("Project was created but the server returned no project ID.");
    projects = [project, ...projects.filter(p => String(p.id) !== String(project.id))];
    currentProjectId = String(project.id);
    localStorage.setItem("codeforge_project_id", currentProjectId);
    input.value = "";
    renderProjectList();
    await selectProject(project, true);
  } catch (error) {
    $("project-error").textContent = error.message || "Could not create project.";
  } finally {
    button.disabled = false;
  }
}

async function selectProject(project, closeModal = true) {
  if (!project || !project.id) return;
  currentProjectId = String(project.id);
  localStorage.setItem("codeforge_project_id", currentProjectId);
  $("current-project").textContent = project.name || "Untitled Project";
  currentFilePath = "";
  activeTab = "";
  tabs.clear();
  renderTabs();
  chatHistory.innerHTML = '<div class="welcome-msg"><div class="welcome-icon">✦</div><h2>What are we building?</h2><p>Ask me to create features, debug code, refactor files, or run commands in your workspace.</p><div class="suggestions"><button type="button" data-prompt="Explain this project structure">Explain this project</button><button type="button" data-prompt="Review the current code for issues">Review current code</button></div></div>';
  bindSuggestionButtons();
  setChatEnabled(true);
  setStatus("Loading workspace…");
  await refreshFileTree();
  if (closeModal) closeProjectModal();
}

function openProjectModal() { renderProjectList(); projectModal.classList.remove("hidden"); $("new-project-name").focus(); }
function closeProjectModal() { projectModal.classList.add("hidden"); $("project-error").textContent = ""; }

function renderProjectList() {
  const list = $("project-list");
  list.innerHTML = "";
  if (!projects.length) {
    list.innerHTML = '<div class="empty-projects">No projects yet.</div>';
    return;
  }
  projects.forEach(project => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "project-row" + (String(project.id) === String(currentProjectId) ? " selected" : "");
    row.innerHTML = '<span class="project-icon">⌘</span><span class="project-copy"><strong></strong><small></small></span><span class="project-check">✓</span>';
    row.querySelector("strong").textContent = project.name || "Untitled Project";
    row.querySelector("small").textContent = project.description || project.slug || "CodeForge workspace";
    row.onclick = () => selectProject(project, true);
    list.appendChild(row);
  });
}

function buildFileTree(paths) {
  const root = {};
  paths.forEach(path => {
    let node = root;
    path.split("/").filter(Boolean).forEach((part, index, parts) => {
      node[part] ||= { __children: {}, __file: index === parts.length - 1 };
      node = node[part].__children;
    });
  });

  fileTree.innerHTML = "";
  let count = 0;

  const render = (node, container, prefix = "") => {
    Object.keys(node).sort((a, b) => {
      const af = node[a].__file, bf = node[b].__file;
      return af === bf ? a.localeCompare(b) : af ? 1 : -1;
    }).forEach(name => {
      const item = node[name];
      const fullPath = prefix ? prefix + "/" + name : name;
      if (item.__file) {
        count++;
        const d = document.createElement("div");
        d.className = "file-item";
        d.dataset.path = fullPath;
        d.innerHTML = '<span class="file-symbol">▱</span><span class="file-name"></span><span class="dirty-dot"></span>';
        d.querySelector(".file-name").textContent = name;
        d.onclick = () => openFile(fullPath);
        container.appendChild(d);
      } else {
        const wrap = document.createElement("div");
        const folder = document.createElement("button");
        folder.type = "button";
        folder.className = "folder-row";
        folder.innerHTML = '<span class="folder-chevron">▾</span><span class="folder-name"></span>';
        folder.querySelector(".folder-name").textContent = name;
        const children = document.createElement("div");
        children.className = "folder-children";
        folder.onclick = () => {
          children.classList.toggle("collapsed");
          folder.querySelector(".folder-chevron").textContent = children.classList.contains("collapsed") ? "▸" : "▾";
        };
        wrap.append(folder, children);
        container.appendChild(wrap);
        render(item.__children, children, fullPath);
      }
    });
  };
  render(root, fileTree);
  $("file-count").textContent = count;
}

function updateDirtyUI(path) {
  const tab = tabs.get(path);
  document.querySelectorAll(".file-item").forEach(item => {
    if (item.dataset.path === path) item.querySelector(".dirty-dot").style.opacity = tab?.dirty ? "1" : "0";
  });
  renderTabs();
}

async function refreshFileTree() {
  if (!currentProjectId) {
    fileTree.innerHTML = '<div class="empty-tree">Select a project to view files.</div>';
    $("file-count").textContent = "0";
    return;
  }
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/tree");
    if (!response.ok) {
      setStatus("Workspace load failed", false);
      appendSysMsg(await readError(response, "Could not load workspace files."));
      return;
    }
    const data = await response.json();
    buildFileTree(Array.isArray(data.files) ? data.files : []);
    setStatus("Workspace ready");
    filterFiles($("file-search").value);
    updateAllDirtyDots();
  } catch (error) {
    setStatus("Workspace unavailable", false);
    appendSysMsg(error.message || "Could not load workspace files.");
  }
}

function filterFiles(query) {
  const q = query.toLowerCase().trim();
  document.querySelectorAll(".file-item").forEach(item => {
    item.style.display = item.dataset.path.toLowerCase().includes(q) ? "flex" : "none";
  });
  document.querySelectorAll(".folder-row").forEach(row => {
    const parent = row.parentElement;
    const hasVisible = [...parent.querySelectorAll(".file-item")].some(x => x.style.display !== "none");
    parent.style.display = !q || hasVisible ? "block" : "none";
    if (q && hasVisible) parent.querySelector(".folder-children")?.classList.remove("collapsed");
  });
}

function updateAllDirtyDots() {
  tabs.forEach((tab, path) => {
    const item = document.querySelector('.file-item[data-path="' + CSS.escape(path) + '"]');
    if (item) item.querySelector(".dirty-dot").style.opacity = tab.dirty ? "1" : "0";
  });
}

function languageFor(path) {
  const ext = path.includes(".") ? path.split(".").pop().toLowerCase() : "";
  return {py:"python",js:"javascript",jsx:"javascript",ts:"typescript",tsx:"typescript",html:"html",css:"css",json:"json",md:"markdown",sql:"sql",java:"java",cpp:"cpp",c:"c",cs:"csharp",go:"go",rs:"rust",sh:"shell",yaml:"yaml",yml:"yaml"}[ext] || "plaintext";
}

async function openFile(path) {
  if (!currentProjectId) return;
  if (!editorReady) {
    setStatus("Editor is still loading…", false);
    appendSysMsg("The Monaco editor is still loading. Please try opening the file again in a moment.");
    return;
  }
  if (tabs.has(path)) return activateTab(path);

  setStatus("Opening " + path + "…");
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file?path=" + encodeURIComponent(path));
    if (!response.ok) return appendSysMsg(await readError(response, "Could not open file."));
    const data = await response.json();
    const uri = monaco.Uri.parse("codeforge://workspace/" + currentProjectId + "/" + path);
    const model = monaco.editor.createModel(data.content || "", languageFor(path), uri);
    const tab = { path, model, dirty: false, savedContent: data.content || "" };
    tabs.set(path, tab);
    renderTabs();
    activateTab(path);
    setStatus("Opened " + path);
  } catch (error) {
    appendSysMsg(error.message || "Could not open file.");
  }
}

function activateTab(path) {
  const tab = tabs.get(path);
  if (!tab || !editorReady) return;
  activeTab = path;
  currentFilePath = path;
  editor.setModel(tab.model);
  monaco.editor.setModelLanguage(tab.model, languageFor(path));
  $("active-file").textContent = path;
  $("save-state").textContent = tab.dirty ? "Unsaved" : "";
  document.querySelectorAll(".file-item").forEach(x => x.classList.toggle("active", x.dataset.path === path));
  renderTabs();
}

function closeTab(path) {
  const tab = tabs.get(path);
  if (!tab) return;
  if (tab.dirty && !confirm("Discard unsaved changes in " + path + "?")) return;
  tab.model.dispose();
  tabs.delete(path);
  if (activeTab === path) {
    const next = [...tabs.keys()][Math.max(0, [...tabs.keys()].indexOf(path) - 1)];
    activeTab = "";
    currentFilePath = "";
    if (next) activateTab(next);
    else {
      editor.setModel(null);
      $("active-file").textContent = "Welcome";
      $("save-state").textContent = "";
    }
  }
  renderTabs();
}

function renderTabs() {
  const host = $("editor-tabs");
  host.innerHTML = "";
  tabs.forEach((tab, path) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "editor-tab" + (path === activeTab ? " active" : "");
    button.innerHTML = '<span class="tab-file-icon">●</span><span class="tab-label"></span><span class="tab-dirty"></span><span class="tab-close">×</span>';
    button.querySelector(".tab-label").textContent = path.split("/").pop();
    button.title = path;
    button.querySelector(".tab-dirty").style.opacity = tab.dirty ? "1" : "0";
    button.onclick = e => e.target.classList.contains("tab-close") ? closeTab(path) : activateTab(path);
    host.appendChild(button);
  });
}

async function saveCurrentFile() {
  const tab = tabs.get(activeTab);
  if (!tab || !currentProjectId || !editorReady) return;
  const content = tab.model.getValue();
  $("save-state").textContent = "Saving…";
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file", {
      method: "PUT",
      body: JSON.stringify({ path: tab.path, content })
    });
    if (!response.ok) {
      $("save-state").textContent = "Save failed";
      appendSysMsg(await readError(response, "Could not save file."));
      return;
    }
    tab.savedContent = content;
    tab.dirty = false;
    updateDirtyUI(tab.path);
    $("save-state").textContent = "Saved";
    setStatus("Saved " + tab.path);
    setTimeout(() => { if (!tab.dirty) $("save-state").textContent = ""; }, 1600);
  } catch (error) {
    $("save-state").textContent = "Save failed";
    appendSysMsg(error.message || "Could not save file.");
  }
}

function bindSuggestionButtons() {
  document.querySelectorAll(".suggestions button").forEach(button => {
    button.onclick = () => {
      chatInput.value = button.dataset.prompt || "";
      sendChatMessage();
    };
  });
}

function addTimeline(type, title, detail = "", status = "running") {
  const card = document.createElement("div");
  card.className = "timeline-card " + type + " " + status;
  card.innerHTML = '<div class="timeline-icon"></div><div class="timeline-copy"><strong></strong><span></span></div><div class="timeline-status"></div>';
  card.querySelector("strong").textContent = title;
  card.querySelector("span").textContent = detail;
  card.querySelector(".timeline-status").textContent = status === "running" ? "…" : status === "done" ? "✓" : "!";
  agentOutput.appendChild(card);
  agentOutput.scrollTop = agentOutput.scrollHeight;
  return card;
}

function setAgentState(running, label = "") {
  agentRunning = running;
  $("agent-state").textContent = running ? (label || "Working") : "Idle";
  $("agent-state").classList.toggle("working", running);
}

async function sendChatMessage() {
  const message = chatInput.value.trim();
  if (!message || !currentProjectId || sendBtn.disabled) return;
  document.querySelector(".welcome-msg")?.remove();

  const mode = $("agent-mode").value;
  const model = $("model-select").value;
  const contextualMessage = "[CodeForge context: agent mode=" + mode + ", model preference=" + model + "]\n\n" + message;

  chatInput.value = "";
  appendMsg(message, "user");
  sendBtn.disabled = true;
  chatInput.disabled = true;
  setStatus("Agent working…");
  setAgentState(true, mode.charAt(0).toUpperCase() + mode.slice(1));
  agentOutput.innerHTML = "";
  pendingDiffs = [];
  activeDiff = null;

  try {
    const response = await api("/api/agent/" + encodeURIComponent(currentProjectId) + "/chat", {
      method: "POST",
      body: JSON.stringify({ message: contextualMessage, mode, model })
    });
    if (!response.ok) {
      appendSysMsg(await readError(response, "Agent request failed."));
      return;
    }
    if (!response.body) {
      appendSysMsg("The agent returned no stream.");
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      chunks.forEach(processSseChunk);
    }
    if (buffer.trim()) processSseChunk(buffer);
  } catch (error) {
    appendSysMsg(error.message || "Error communicating with AI agent.");
  } finally {
    sendBtn.disabled = false;
    chatInput.disabled = false;
    chatInput.focus();
    setAgentState(false);
    setStatus("Workspace ready");
  }
}

function processSseChunk(chunk) {
  const dataLines = chunk.split("\n").filter(line => line.startsWith("data:"));
  if (!dataLines.length) return;
  try {
    const payload = dataLines.map(line => line.slice(5).trim()).join("");
    handleAgentEvent(JSON.parse(payload));
  } catch {
    appendSysMsg("Received an invalid agent event.");
  }
}

async function handleAgentEvent(data) {
  if (!data) return;
  if (data.type === "message") {
    appendMsg(data.content || "", "ai");
    return;
  }

  if (data.type === "tool_call") {
    const args = data.args || {};
    const tool = data.tool || "tool";
    const detail = Object.keys(args).length ? JSON.stringify(args) : "Agent invoked tool";
    addTimeline("tool", tool, detail, "running");
    agentOutput.querySelectorAll(".timeline-card.running").forEach(card => {
      if (card.querySelector("strong")?.textContent === tool) {
        card.classList.remove("running");
        card.classList.add("done");
        card.querySelector(".timeline-status").textContent = "✓";
      }
    });
    if (tool === "run_command") {
      const command = args.command || "";
      terminalOutput.textContent += "\n$ " + command + "\n… running";
      addTimeline("command", "Command", command, "done");
    }
    return;
  }

  if (data.type === "tool_result") {
    const label = data.tool || "tool";
    const output = data.result || "";
    addTimeline(data.success ? "success" : "error", label + (data.success ? " completed" : " failed"), output, data.success ? "done" : "error");
    if (label === "run_command") {
      terminalOutput.textContent += "\n" + (data.success ? "✓ " : "✗ ") + output + "\n";
      terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }
    return;
  }

  if (data.type === "file_change") {
    const path = data.path || "";
    addTimeline("file", "File changed", path, "done");
    if (path && data.before !== undefined && data.after !== undefined && data.before !== data.after) {
      enqueueDiff({ path, before: data.before || "", after: data.after || "", created: Boolean(data.created) });
    } else if (path && tabs.has(path)) {
      await reloadTabFromWorkspace(path);
    }
    await refreshFileTree();
    return;
  }

  if (data.type === "done") {
    addTimeline("success", "Agent finished", "Workspace synchronized", "done");
    refreshFileTree();
    return;
  }

  if (data.type === "error") {
    addTimeline("error", "Agent error", data.message || "Unknown error", "error");
    appendSysMsg("Error: " + (data.message || "Unknown agent error"));
  }
}

async function reloadTabFromWorkspace(path) {
  if (!tabs.has(path)) return;
  const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file?path=" + encodeURIComponent(path));
  if (!response.ok) return;
  const data = await response.json();
  const tab = tabs.get(path);
  tab.model.setValue(data.content || "");
  tab.savedContent = data.content || "";
  tab.dirty = false;
  updateDirtyUI(path);
}

function enqueueDiff(diff) {
  pendingDiffs.push(diff);
  if (!activeDiff) showNextDiff();
}

function showNextDiff() {
  if (activeDiff || !pendingDiffs.length) return;
  activeDiff = pendingDiffs.shift();
  openDiffModal(activeDiff);
}

function openDiffModal(diff) {
  if (!diffEditor) {
    diffEditor = monaco.editor.createDiffEditor($("diff-container"), {
      automaticLayout: true,
      theme: "vs-dark",
      minimap: { enabled: false },
      renderSideBySide: true,
      fontSize: settings.fontSize
    });
  }
  const oldModel = diffEditor.getModel();
  if (oldModel) {
    oldModel.original.dispose();
    oldModel.modified.dispose();
  }
  const original = monaco.editor.createModel(diff.before || "", languageFor(diff.path));
  const modified = monaco.editor.createModel(diff.after || "", languageFor(diff.path));
  diffEditor.setModel({ original, modified });
  $("diff-subtitle").textContent = diff.path + " — review the AI-generated change.";
  diffModal.classList.remove("hidden");
}

function closeDiffModal() {
  diffModal.classList.add("hidden");
  if (diffEditor) {
    const model = diffEditor.getModel();
    if (model) {
      model.original.dispose();
      model.modified.dispose();
      diffEditor.setModel(null);
    }
  }
}

async function finishCurrentDiff(accepted) {
  if (!activeDiff) return;
  const diff = activeDiff;
  try {
    if (!accepted) {
      const response = diff.created
        ? await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file?path=" + encodeURIComponent(diff.path), { method: "DELETE" })
        : await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file", {
            method: "PUT",
            body: JSON.stringify({ path: diff.path, content: diff.before })
          });
      if (!response.ok) throw new Error(await readError(response, "Could not reject the change."));
      if (tabs.has(diff.path)) {
        const tab = tabs.get(diff.path);
        tab.model.setValue(diff.before);
        tab.savedContent = diff.before;
        tab.dirty = false;
        updateDirtyUI(diff.path);
      }
      setStatus("Rejected " + diff.path);
    } else {
      if (tabs.has(diff.path)) {
        const tab = tabs.get(diff.path);
        tab.model.setValue(diff.after);
        tab.savedContent = diff.after;
        tab.dirty = false;
        updateDirtyUI(diff.path);
      }
      setStatus("Accepted " + diff.path);
    }
  } catch (error) {
    appendSysMsg(error.message || "Could not process the AI change.");
    return;
  }
  activeDiff = null;
  closeDiffModal();
  await refreshFileTree();
  showNextDiff();
}

async function acceptDiff() {
  await finishCurrentDiff(true);
}

async function rejectDiff() {
  await finishCurrentDiff(false);
}

function appendMsg(text, sender) {
  const d = document.createElement("div");
  d.className = "chat-msg msg-" + sender;
  d.textContent = text;
  chatHistory.appendChild(d);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendSysMsg(text) { appendMsg(text, "sys"); }

function initEditor() {
  if (typeof require !== "function") return appendSysMsg("Monaco editor loader did not initialize.");
  require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs" } });
  require(["vs/editor/editor.main"], () => {
    editor = monaco.editor.create($("editor-container"), {
      value: "// Welcome to CodeForge\n// Select a file or ask the AI agent to build something.\n",
      language: "javascript",
      theme: "vs-dark",
      automaticLayout: true,
      minimap: { enabled: Boolean(settings.minimap) },
      fontSize: Number(settings.fontSize) || 13,
      lineHeight: 21,
      padding: { top: 16 },
      smoothScrolling: true,
      scrollBeyondLastLine: false
    });
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveCurrentFile);
    editor.onDidChangeModelContent(() => {
      if (!activeTab) return;
      const tab = tabs.get(activeTab);
      if (!tab) return;
      tab.dirty = tab.model.getValue() !== tab.savedContent;
      $("save-state").textContent = tab.dirty ? "Unsaved" : "";
      updateDirtyUI(activeTab);
    });
    editorReady = true;
    setStatus("Editor ready");
    if (activeTab) activateTab(activeTab);
  }, () => appendSysMsg("Could not load Monaco editor."));
}

function openSettings() {
  $("setting-font-size").value = settings.fontSize;
  $("setting-explorer-width").value = settings.explorerWidth;
  $("setting-chat-width").value = settings.chatWidth;
  $("setting-minimap").value = settings.minimap ? "on" : "off";
  settingsModal.classList.remove("hidden");
}

function closeSettings() { settingsModal.classList.add("hidden"); }

function applySettings() {
  settings.fontSize = Math.min(24, Math.max(10, Number($("setting-font-size").value) || 13));
  settings.explorerWidth = Math.min(420, Math.max(180, Number($("setting-explorer-width").value) || 250));
  settings.chatWidth = Math.min(600, Math.max(300, Number($("setting-chat-width").value) || 380));
  settings.minimap = $("setting-minimap").value === "on";
  persistSettings();
  applyPanelWidths();
  if (editor) {
    editor.updateOptions({ fontSize: settings.fontSize, minimap: { enabled: settings.minimap } });
  }
  closeSettings();
  setStatus("Settings applied");
}

function resetSettings() {
  settings = { ...defaultSettings };
  persistSettings();
  openSettings();
  applySettings();
}

function applyPanelWidths() {
  const shell = $("app-shell");
  shell.style.gridTemplateColumns = settings.explorerWidth + "px 5px minmax(0,1fr) 5px " + settings.chatWidth + "px";
}

function startResize(event) {
  const type = event.currentTarget.dataset.resize;
  resizeState = { type, startX: event.clientX, startExplorer: settings.explorerWidth, startChat: settings.chatWidth };
  document.body.classList.add("resizing");
  event.preventDefault();
}

function onResize(event) {
  if (!resizeState) return;
  if (resizeState.type === "explorer") settings.explorerWidth = Math.min(420, Math.max(180, resizeState.startExplorer + event.clientX - resizeState.startX));
  if (resizeState.type === "chat") settings.chatWidth = Math.min(600, Math.max(300, resizeState.startChat - (event.clientX - resizeState.startX)));
  applyPanelWidths();
}

function stopResize() {
  if (!resizeState) return;
  resizeState = null;
  document.body.classList.remove("resizing");
  persistSettings();
}

const commands = [
  { name: "Save current file", key: "Ctrl S", run: saveCurrentFile },
  { name: "Refresh explorer", key: "Ctrl R", run: refreshFileTree },
  { name: "Open projects", key: "", run: openProjectModal },
  { name: "Open settings", key: "", run: openSettings },
  { name: "Focus AI chat", key: "", run: () => chatInput.focus() },
  { name: "Clear terminal", key: "", run: () => { terminalOutput.textContent = ""; agentOutput.innerHTML = ""; } },
  { name: "Close active tab", key: "Ctrl W", run: () => activeTab && closeTab(activeTab) }
];
let commandSelection = 0;

function renderCommands(query = "") {
  const q = query.toLowerCase();
  const list = $("command-list");
  list.innerHTML = "";
  const filtered = commands.filter(c => c.name.toLowerCase().includes(q));
  commandSelection = Math.min(commandSelection, Math.max(0, filtered.length - 1));
  filtered.forEach((command, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "command-row" + (index === commandSelection ? " selected" : "");
    row.innerHTML = '<span class="command-name"></span><kbd></kbd>';
    row.querySelector(".command-name").textContent = command.name;
    row.querySelector("kbd").textContent = command.key;
    row.onclick = () => { closeCommandPalette(); command.run(); };
    list.appendChild(row);
  });
}

function openCommandPalette() {
  commandPalette.classList.remove("hidden");
  $("command-input").value = "";
  commandSelection = 0;
  renderCommands();
  $("command-input").focus();
}

function closeCommandPalette() { commandPalette.classList.add("hidden"); }

function handleCommandKey(event) {
  if (commandPalette.classList.contains("hidden")) return;
  const rows = $("command-list").querySelectorAll(".command-row");
  if (event.key === "ArrowDown") { event.preventDefault(); commandSelection = Math.min(rows.length - 1, commandSelection + 1); renderCommands($("command-input").value); }
  if (event.key === "ArrowUp") { event.preventDefault(); commandSelection = Math.max(0, commandSelection - 1); renderCommands($("command-input").value); }
  if (event.key === "Enter") { event.preventDefault(); rows[commandSelection]?.click(); }
  if (event.key === "Escape") { event.preventDefault(); closeCommandPalette(); }
}

function init() {
  $("login-btn").onclick = login;
  $("email-input").addEventListener("keydown", handleAuthKeydown);
  $("password-input").addEventListener("keydown", handleAuthKeydown);
  $("logout-btn").onclick = () => logout(true);
  $("refresh-tree-btn").onclick = refreshFileTree;
  $("save-btn").onclick = saveCurrentFile;
  $("clear-terminal").onclick = () => { terminalOutput.textContent = ""; agentOutput.innerHTML = ""; };
  $("load-projects-btn").onclick = () => loadProjects(true);
  $("project-switcher").onclick = () => loadProjects(true);
  $("command-palette-btn").onclick = openCommandPalette;
  $("settings-btn").onclick = openSettings;
  $("close-projects-btn").onclick = closeProjectModal;
  $("create-project-btn").onclick = createProject;
  $("new-project-name").addEventListener("keydown", e => { if (e.key === "Enter") createProject(); });
  projectModal.addEventListener("click", e => { if (e.target === projectModal) closeProjectModal(); });
  $("close-settings-btn").onclick = closeSettings;
  $("save-settings-btn").onclick = applySettings;
  $("reset-settings-btn").onclick = resetSettings;
  settingsModal.addEventListener("click", e => { if (e.target === settingsModal) closeSettings(); });
  $("close-diff-btn").onclick = closeDiffModal;
  $("accept-diff-btn").onclick = acceptDiff;
  $("reject-diff-btn").onclick = rejectDiff;
  diffModal.addEventListener("click", e => { if (e.target === diffModal) closeDiffModal(); });
  $("file-search").addEventListener("input", e => filterFiles(e.target.value));
  sendBtn.onclick = sendChatMessage;
  chatInput.addEventListener("input", () => {
    if (token && currentProjectId && !agentRunning) sendBtn.disabled = !chatInput.value.trim();
  });
  chatInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
  });
  $("command-input").addEventListener("input", e => { commandSelection = 0; renderCommands(e.target.value); });
  $("command-input").addEventListener("keydown", handleCommandKey);

  document.querySelectorAll(".terminal-tab").forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll(".terminal-tab").forEach(x => x.classList.remove("active"));
      tab.classList.add("active");
      const showAgent = tab.dataset.terminalTab === "agent";
      terminalOutput.classList.toggle("hidden-output", showAgent);
      agentOutput.classList.toggle("hidden-output", !showAgent);
    };
  });

  document.querySelectorAll(".resize-handle").forEach(handle => handle.addEventListener("mousedown", startResize));
  window.addEventListener("mousemove", onResize);
  window.addEventListener("mouseup", stopResize);
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openCommandPalette(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "p" && document.activeElement !== chatInput) { e.preventDefault(); $("file-search").focus(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "w" && activeTab) { e.preventDefault(); closeTab(activeTab); }
    if (e.key === "Escape") {
      closeProjectModal();
      closeSettings();
      closeDiffModal();
      if (!commandPalette.classList.contains("hidden")) closeCommandPalette();
    }
  });

  bindSuggestionButtons();
  applyPanelWidths();
  setAuthenticatedState(Boolean(token));
  if (token && currentProjectId) setChatEnabled(true);
  initEditor();

  if (token) loadProjects(false);
  else {
    setAuthenticatedState(false);
    setTimeout(() => $("email-input").focus(), 50);
  }
}

window.addEventListener("beforeunload", event => {
  const dirty = [...tabs.values()].some(tab => tab.dirty);
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
})();