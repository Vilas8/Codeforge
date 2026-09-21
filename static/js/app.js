(() => {
"use strict";

let token = localStorage.getItem("codeforge_token") || "";
let currentProjectId = localStorage.getItem("codeforge_project_id") || "";
let currentFilePath = "";
let editor = null;
let projects = [];
let editorReady = false;

const $ = (id) => document.getElementById(id);
const authOverlay = $("auth-overlay");
const fileTree = $("file-tree");
const chatHistory = $("chat-history");
const chatInput = $("chat-input");
const sendBtn = $("send-chat-btn");
const terminalOutput = $("terminal-output");
const agentOutput = $("agent-output");
const workspaceStatus = $("workspace-status");
const projectModal = $("project-modal");

const setStatus = (text, ok = true) => {
  workspaceStatus.textContent = text;
  workspaceStatus.previousElementSibling.style.background = ok ? "var(--green)" : "#f59e0b";
};

function setAuthenticatedState(isAuthenticated) {
  authOverlay.style.display = isAuthenticated ? "none" : "flex";
  $("logout-btn").disabled = !isAuthenticated;
  $("load-projects-btn").disabled = !isAuthenticated;
  $("project-switcher").disabled = !isAuthenticated;
  $("refresh-tree-btn").disabled = !isAuthenticated;
  if (!isAuthenticated) {
    chatInput.disabled = true;
    sendBtn.disabled = true;
  }
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
  } catch {
    return fallback;
  }
}

function showAuthError(message) {
  $("auth-error").textContent = message || "";
}

function logout(showOverlay = true) {
  token = "";
  currentProjectId = "";
  currentFilePath = "";
  localStorage.removeItem("codeforge_token");
  localStorage.removeItem("codeforge_project_id");
  projects = [];
  $("current-project").textContent = "No Project Selected";
  $("active-file").textContent = "Welcome";
  fileTree.innerHTML = "";
  if (editorReady) editor.setValue("// Welcome to CodeForge\n// Sign in and select a project to start.\n");
  chatHistory.innerHTML = '<div class="welcome-msg"><div class="welcome-icon">✦</div><h2>What are we building?</h2><p>Sign in and select a project to start.</p></div>';
  setAuthenticatedState(false);
  if (showOverlay) $("email-input").focus();
}

async function login() {
  const email = $("email-input").value.trim();
  const password = $("password-input").value;
  if (!email || !password) {
    showAuthError("Enter your email and password.");
    return;
  }

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
    if (!response.ok) {
      showAuthError(await readError(response, "Login failed."));
      return;
    }
    const data = await response.json();
    if (!data.access_token) {
      showAuthError("Login succeeded but no access token was returned.");
      return;
    }
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

async function loadProjects(openModal = false) {
  if (!token) return;
  setStatus("Loading projects…");
  try {
    const response = await api("/api/projects/");
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

    if (openModal) renderProjectList();
    if (!projects.length) {
      currentProjectId = "";
      localStorage.removeItem("codeforge_project_id");
      $("current-project").textContent = "No Project Selected";
      chatInput.disabled = true;
      sendBtn.disabled = true;
      if (openModal) $("project-error").textContent = "Create your first project below.";
      setStatus("No project selected");
      return;
    }

    const saved = projects.find(p => String(p.id) === String(currentProjectId));
    const selected = saved || projects[0];
    await selectProject(selected, false);
    if (openModal) renderProjectList();
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
  if (!name) {
    $("project-error").textContent = "Enter a project name.";
    input.focus();
    return;
  }

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
    projects = [project, ...projects.filter(p => String(p.id) !== String(project.id))];
    input.value = "";
    await selectProject(project, true);
    renderProjectList();
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
  $("active-file").textContent = "Welcome";
  chatHistory.innerHTML = '<div class="welcome-msg"><div class="welcome-icon">✦</div><h2>What are we building?</h2><p>Ask me to create features, debug code, refactor files, or run commands in your workspace.</p><div class="suggestions"><button type="button" data-prompt="Explain this project structure">Explain this project</button><button type="button" data-prompt="Review the current code for issues">Review current code</button></div></div>';
  bindSuggestionButtons();
  chatInput.disabled = false;
  sendBtn.disabled = false;
  setStatus("Loading workspace…");
  await refreshFileTree();
  if (closeModal) closeProjectModal();
}

function openProjectModal() {
  renderProjectList();
  projectModal.classList.remove("hidden");
  $("new-project-name").focus();
}

function closeProjectModal() {
  projectModal.classList.add("hidden");
  $("project-error").textContent = "";
}

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
  const render = (node, container, prefix = "") => {
    Object.keys(node).sort((a,b) => {
      const af = node[a].__file, bf = node[b].__file;
      return af === bf ? a.localeCompare(b) : af ? 1 : -1;
    }).forEach(name => {
      const item = node[name];
      const fullPath = prefix ? prefix + "/" + name : name;
      if (item.__file) {
        const d = document.createElement("div");
        d.className = "file-item";
        d.dataset.path = fullPath;
        d.innerHTML = '<span class="file-symbol">▱</span><span class="file-name"></span>';
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
}

async function refreshFileTree() {
  if (!currentProjectId) {
    fileTree.innerHTML = '<div class="empty-tree">Select a project to view files.</div>';
    return;
  }
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/tree");
    if (!response.ok) {
      const message = await readError(response, "Could not load workspace files.");
      setStatus("Workspace load failed", false);
      appendSysMsg(message);
      return;
    }
    const data = await response.json();
    buildFileTree(Array.isArray(data.files) ? data.files : []);
    setStatus("Workspace ready");
    filterFiles($("file-search").value);
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
    row.parentElement.style.display = !q || hasVisible ? "block" : "none";
    if (q && hasVisible) parent.querySelector(".folder-children")?.classList.remove("collapsed");
  });
}

async function openFile(path) {
  if (!currentProjectId || !editorReady) return;
  currentFilePath = path;
  $("active-file").textContent = path;
  document.querySelectorAll(".file-item").forEach(x => x.classList.toggle("active", x.dataset.path === path));
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file?path=" + encodeURIComponent(path));
    if (!response.ok) {
      appendSysMsg(await readError(response, "Could not open file."));
      return;
    }
    const data = await response.json();
    editor.setValue(data.content || "");
    const ext = path.includes(".") ? path.split(".").pop().toLowerCase() : "";
    const map = {py:"python",js:"javascript",jsx:"javascript",ts:"typescript",tsx:"typescript",html:"html",css:"css",json:"json",md:"markdown",sql:"sql",java:"java",cpp:"cpp",c:"c",cs:"csharp",go:"go",rs:"rust",sh:"shell"};
    monaco.editor.setModelLanguage(editor.getModel(), map[ext] || "plaintext");
    $("save-state").textContent = "";
  } catch (error) {
    appendSysMsg(error.message || "Could not open file.");
  }
}

async function saveCurrentFile() {
  if (!currentFilePath || !currentProjectId || !editorReady) return;
  $("save-state").textContent = "Saving…";
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/file", {
      method: "PUT",
      body: JSON.stringify({ path: currentFilePath, content: editor.getValue() })
    });
    if (!response.ok) {
      $("save-state").textContent = "Save failed";
      appendSysMsg(await readError(response, "Could not save file."));
      return;
    }
    $("save-state").textContent = "Saved";
    setTimeout(() => { $("save-state").textContent = ""; }, 1800);
    setStatus("Saved " + currentFilePath);
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

async function sendChatMessage() {
  const message = chatInput.value.trim();
  if (!message || !currentProjectId || sendBtn.disabled) return;
  document.querySelector(".welcome-msg")?.remove();
  chatInput.value = "";
  appendMsg(message, "user");
  sendBtn.disabled = true;
  chatInput.disabled = true;
  setStatus("Agent working…");
  agentOutput.textContent = "";
  try {
    const response = await api("/api/agent/" + encodeURIComponent(currentProjectId) + "/chat", {
      method: "POST",
      body: JSON.stringify({ message })
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
    setStatus("Workspace ready");
  }
}

function processSseChunk(chunk) {
  const line = chunk.split("\n").find(x => x.startsWith("data: "));
  if (!line) return;
  try {
    handleAgentEvent(JSON.parse(line.slice(6)));
  } catch {
    appendSysMsg("Received an invalid agent event.");
  }
}

function handleAgentEvent(data) {
  if (!data) return;
  if (data.type === "message") {
    appendMsg(data.content || "", "ai");
  } else if (data.type === "tool_call") {
    const args = data.args || {};
    appendSysMsg("Agent: " + (data.tool || "tool"));
    agentOutput.textContent += "\n[" + (data.tool || "tool") + "] " + JSON.stringify(args) + "\n";
    if (data.tool === "run_command") {
      terminalOutput.textContent += "\n$ " + (args.command || "") + "\n…";
    }
  } else if (data.type === "file_change") {
    agentOutput.textContent += "[file change] " + (data.path || "") + "\n";
    refreshFileTree();
    if (data.path === currentFilePath) openFile(currentFilePath);
  } else if (data.type === "done") {
    appendSysMsg("Agent finished.");
    refreshFileTree();
  } else if (data.type === "error") {
    appendSysMsg("Error: " + (data.message || "Unknown agent error"));
  }
}

function appendMsg(text, sender) {
  const d = document.createElement("div");
  d.className = "chat-msg msg-" + sender;
  d.textContent = text;
  chatHistory.appendChild(d);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendSysMsg(text) {
  appendMsg(text, "sys");
}

function initEditor() {
  if (typeof require !== "function") {
    appendSysMsg("Monaco editor loader did not initialize.");
    return;
  }
  require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs" } });
  require(["vs/editor/editor.main"], () => {
    editor = monaco.editor.create($("editor-container"), {
      value: "// Welcome to CodeForge\n// Select a file or ask the AI agent to build something.\n",
      language: "javascript",
      theme: "vs-dark",
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      lineHeight: 21,
      padding: { top: 16 }
    });
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveCurrentFile);
    editorReady = true;
  }, () => appendSysMsg("Could not load Monaco editor."));
}

function init() {
  $("login-btn").onclick = login;
  $("logout-btn").onclick = () => logout(true);
  $("refresh-tree-btn").onclick = refreshFileTree;
  $("save-btn").onclick = saveCurrentFile;
  $("clear-terminal").onclick = () => {
    terminalOutput.textContent = "";
    agentOutput.textContent = "";
  };
  $("load-projects-btn").onclick = () => loadProjects(true);
  $("project-switcher").onclick = () => loadProjects(true);
  $("close-projects-btn").onclick = closeProjectModal;
  $("create-project-btn").onclick = createProject;
  $("new-project-name").addEventListener("keydown", e => {
    if (e.key === "Enter") createProject();
  });
  projectModal.addEventListener("click", e => {
    if (e.target === projectModal) closeProjectModal();
  });
  $("file-search").addEventListener("input", e => filterFiles(e.target.value));
  sendBtn.onclick = sendChatMessage;
  chatInput.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });
  document.querySelectorAll(".terminal-tab").forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll(".terminal-tab").forEach(x => x.classList.remove("active"));
      tab.classList.add("active");
      const showAgent = tab.dataset.terminalTab === "agent";
      terminalOutput.classList.toggle("hidden-output", showAgent);
      agentOutput.classList.toggle("hidden-output", !showAgent);
    };
  });
  bindSuggestionButtons();
  setAuthenticatedState(Boolean(token));
  initEditor();

  if (token) {
    loadProjects(false);
  } else {
    setAuthenticatedState(false);
    setTimeout(() => $("email-input").focus(), 50);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
})();