(() => {
"use strict";

let token = localStorage.getItem("codeforge_token") || "";
let refreshToken = localStorage.getItem("codeforge_refresh_token") || "";
let refreshInFlight = null;
let sessionRestoreInFlight = null;
let fileTreeRefreshInFlight = null;
let currentProjectId = localStorage.getItem("codeforge_project_id") || "";
let projects = [];
let currentUser = null;
let editor = null;
let editorReady = false;
let tabs = new Map();
let activeTab = "";
let agentRunning = false;
let activeAiMessage = null;
let thinkingMessage = null;
let streamHadError = false;
let resizeDrag = null;
let activeDragPath = "";
let contextMenuPath = "";
let contextMenuIsFolder = false;
let contextMenuParent = "";
let terminalBusy = false;
let attachedContext = "";
let pendingActionMode = "build";
let notifications = JSON.parse(localStorage.getItem("codeforge_notifications") || "[]");
const collapsedFolders = new Set(JSON.parse(localStorage.getItem("codeforge_collapsed_folders") || "[]"));
let profileData = null;
const saveTimers = new Map();

const $ = id => document.getElementById(id);
const fileTree = $("file-tree");
const chatHistory = $("chat-history");
const chatInput = $("chat-input");
const sendBtn = $("send-chat-btn");
const terminalOutput = $("terminal-output");
const agentOutput = $("agent-output");
const projectModal = $("project-modal");
const settingsModal = $("settings-modal");
const fileCreateModal = $("file-create-modal");

const defaultSettings = { fontSize: 13, explorerWidth: 230, chatWidth: 470, terminalHeight: 275, minimap: true, terminalOpen: false, explorerOpen: true, theme: "dark" };
let settings = loadSettings();

function loadSettings() {
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem("codeforge_settings") || "{}") }; }
  catch { return { ...defaultSettings }; }
}
function persistSettings() { localStorage.setItem("codeforge_settings", JSON.stringify(settings)); }
function applyTheme(theme, persist = true) {
  const next = theme === "light" ? "light" : "dark";
  settings.theme = next;
  document.documentElement.dataset.theme = next;
  document.body.dataset.theme = next;
  const toggle = $("theme-toggle");
  if (toggle) {
    toggle.textContent = next === "dark" ? "☀" : "☾";
    toggle.title = next === "dark" ? "Switch to light theme" : "Switch to dark theme";
    toggle.setAttribute("aria-label", toggle.title);
  }
  const select = $("setting-theme");
  if (select) select.value = next;
  if (editorReady && window.monaco && editor) {
    monaco.editor.setTheme(next === "dark" ? "codeforge-dark" : "codeforge-light");
  }
  if (persist) persistSettings();
}
function toggleTheme() {
  applyTheme(settings.theme === "dark" ? "light" : "dark");
}

function setStatus(text, ok = true) {
  const el = $("workspace-status");
  if (el) el.textContent = text;
  const dot = document.querySelector(".exact-footer .online-dot");
  if (dot) dot.style.background = ok ? "#22e88c" : "#f59e0b";
}
function timeGreeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  if (hour < 21) return "Good evening";
  return "Good night";
}
function updateGreeting() {
  const greeting = document.querySelector(".hero-greeting");
  if (greeting) greeting.innerHTML = timeGreeting() + ", " + escapeHtml(currentUser?.display_name || currentUser?.email?.split("@")[0] || "Developer") + ' <span>👋</span>';
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function setAuthenticatedState(authenticated) {
  const landing=$("auth-overlay");
  const shell=$("app-shell");
  if (landing) landing.style.display=authenticated ? "none" : "block";
  if (shell) shell.style.display=authenticated ? "grid" : "none";
  if (!authenticated) {
    setChatEnabled(false);
    $("current-project").textContent = "No Project Selected";
    return;
  }
  updateGreeting();
}
function openLoginDialog(){
  $("login-dialog")?.classList.remove("hidden");
  setTimeout(()=>$("email-input")?.focus(),60);
}
function closeLoginDialog(){$("login-dialog")?.classList.add("hidden");showAuthError("");}
function openContactDialog(){$("contact-dialog")?.classList.remove("hidden");}
function closeContactDialog(){$("contact-dialog")?.classList.add("hidden");}


function setChatEnabled(enabled) {
  const canChat = Boolean(enabled && token && currentProjectId);
  chatInput.disabled = !canChat || agentRunning;
  sendBtn.disabled = !canChat || agentRunning || !chatInput.value.trim();
  chatInput.placeholder = canChat ? "Describe what you want to build, modify, debug, or learn..." : "Select a project to start chatting...";
}

async function refreshSession() {
  if (!refreshToken) return false;
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({refresh_token: refreshToken})
      });
      if (!response.ok) return false;
      const data = await response.json();
      if (!data.access_token) return false;
      token = data.access_token;
      refreshToken = data.refresh_token || refreshToken;
      localStorage.setItem("codeforge_token", token);
      localStorage.setItem("codeforge_refresh_token", refreshToken);
      return true;
    } catch { return false; }
    finally { refreshInFlight = null; }
  })();
  return refreshInFlight;
}
async function api(path, options = {}) {
  const requestOptions = {...options};
  const headers = new Headers(requestOptions.headers || {});
  if (token) headers.set("Authorization", "Bearer " + token);
  if (requestOptions.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response = await fetch(path, {...requestOptions, headers});
  if (response.status === 401 && !requestOptions.__skipRefresh && await refreshSession()) {
    const retryHeaders = new Headers(requestOptions.headers || {});
    retryHeaders.set("Authorization", "Bearer " + token);
    if (requestOptions.body && !retryHeaders.has("Content-Type")) retryHeaders.set("Content-Type", "application/json");
    response = await fetch(path, {...requestOptions, headers: retryHeaders, __skipRefresh: true});
  }
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
function appendMsg(text, sender) {
  const d = document.createElement("article");
  d.className = "chat-msg msg-" + sender;
  const head = document.createElement("div");
  head.className = "chat-msg-head";
  const avatar = document.createElement("span");
  avatar.className = "chat-role-avatar";
  avatar.textContent = sender === "user" ? "Y" : sender === "ai" ? "F" : "i";
  const role = document.createElement("span");
  role.className = "chat-role-name";
  role.textContent = sender === "user" ? "You" : sender === "ai" ? "CodeForge" : "System";
  const time = document.createElement("time");
  time.className = "chat-time";
  time.textContent = new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"});
  head.append(avatar,role,time);
  if(sender === "ai"){
    const copy = document.createElement("button");
    copy.type = "button"; copy.className = "chat-copy-btn"; copy.textContent = "Copy";
    copy.onclick = async () => {
      const body = d.querySelector(".chat-msg-body");
      try { await navigator.clipboard.writeText(body?.textContent || ""); copy.textContent="Copied"; setTimeout(()=>copy.textContent="Copy",1200); }
      catch { copy.textContent="Unavailable"; setTimeout(()=>copy.textContent="Copy",1200); }
    };
    head.append(copy);
  }
  const body = document.createElement("div");
  body.className = "chat-msg-body";
  body.textContent = text || "";
  d.append(head,body);
  chatHistory.appendChild(d);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return body;
}
function appendSysMsg(text) { return appendMsg(text, "sys"); }

function showThinkingMessage(text = "CodeForge is working on it…") {
  if (thinkingMessage) {
    const label = thinkingMessage.querySelector(".thinking-label");
    if (label) label.textContent = text;
    return thinkingMessage;
  }
  const d = document.createElement("div");
  d.className = "chat-msg msg-ai ai-thinking";
  d.innerHTML = '<div class="chat-msg-body"><span class="thinking-icon">✦</span><span class="thinking-copy"><strong class="thinking-label"></strong><span class="typing-dots"><i></i><i></i><i></i></span></span></div>';
  d.querySelector(".thinking-label").textContent = text;
  chatHistory.appendChild(d);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  thinkingMessage = d;
  return d;
}
function clearThinkingMessage() {
  if (thinkingMessage) thinkingMessage.remove();
  thinkingMessage = null;
}
function showAuthError(message) { $("auth-error").textContent = message || ""; }

async function login() {
  const email = $("email-input").value.trim();
  const password = $("password-input").value;
  if (!email || !password) { showAuthError("Enter your email and password."); return; }
  const button = $("login-btn");
  button.disabled = true;
  button.textContent = "Signing in…";
  showAuthError("");
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    if (!response.ok) { showAuthError(await readError(response, "Login failed.")); return; }
    const data = await response.json();
    token = data.access_token || "";
    if (!token) { showAuthError("No access token was returned."); return; }
    localStorage.setItem("codeforge_token", token);
    refreshToken = data.refresh_token || "";
    if (refreshToken) localStorage.setItem("codeforge_refresh_token", refreshToken);
    await loadMe();
    setAuthenticatedState(true);
    await loadProjects();
  } catch (error) {
    showAuthError(error.message || "Unable to connect to CodeForge.");
  } finally {
    button.disabled = false;
    button.textContent = "Sign in →";
  }
}
async function loadMe() {
  if (!token) return false;
  try {
    const response = await api("/api/auth/me", { cache: "no-store" });
    if (!response.ok) return false;
    currentUser = await response.json();
    await loadProfile();
    updateGreeting();
    syncAccountUi();
    return true;
  } catch { return false; }
}
async function restoreSession() {
  if (sessionRestoreInFlight) return sessionRestoreInFlight;
  sessionRestoreInFlight = (async () => {
  // Do not briefly expose the IDE with an expired access token after a refresh.
  if (!token && !refreshToken) {
    setAuthenticatedState(false);
    return false;
  }
  if (!token && refreshToken) {
    if (!await refreshSession()) {
      logout(false);
      return false;
    }
  }
  if (await loadMe()) {
    setAuthenticatedState(true);
    await loadProjects(false);
    return true;
  }
  // The access token may have expired between page loads. Give the refresh
  // token one final chance before clearing the local session.
  if (refreshToken && await refreshSession() && await loadMe()) {
    setAuthenticatedState(true);
    await loadProjects(false);
    return true;
  }
  logout(false);
  return false;
  })().finally(() => { sessionRestoreInFlight = null; });
  return sessionRestoreInFlight;
}
async function loadProfile() {
  if (!token) return;
  try {
    const response = await api("/api/profile", { cache: "no-store" });
    if (!response.ok) return;
    profileData = await response.json();
    currentUser = { ...(currentUser || {}), ...profileData };
  } catch {}
}
function displayUserName() {
  return profileData?.display_name || currentUser?.display_name || currentUser?.email?.split("@")[0] || "Developer";
}
function userInitials(name = displayUserName()) {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0,2).map(p=>p[0]).join("") || "D").toUpperCase();
}
function syncAvatar(el, name = displayUserName(), url = profileData?.avatar_url) {
  if (!el) return;
  if (url) {
    el.textContent = "";
    el.style.backgroundImage = "url(" + JSON.stringify(url) + ")";
    el.style.backgroundSize = "cover";
    el.style.backgroundPosition = "center";
  } else {
    el.style.backgroundImage = "";
    el.textContent = userInitials(name);
  }
}
function syncAccountUi() {
  const name = displayUserName();
  const email = profileData?.email || currentUser?.email || "—";
  ["account-name","popover-name","settings-account-name"].forEach(id=>{const el=$(id);if(el)el.textContent=name;});
  ["popover-email","settings-account-email"].forEach(id=>{const el=$(id);if(el)el.textContent=email;});
  ["account-avatar","popover-avatar","settings-avatar"].forEach(id=>syncAvatar($(id),name));
  const plan=$("account-plan"); if(plan) plan.textContent="CodeForge";
  updateGreeting();
}
function logout(showOverlay = true) {
  token = "";
  currentProjectId = "";
  projects = [];
  currentUser = null;
  profileData = null;
  tabs.forEach(t => t.model?.dispose());
  tabs.clear();
  activeTab = "";
  localStorage.removeItem("codeforge_token");
  localStorage.removeItem("codeforge_refresh_token");
  localStorage.removeItem("codeforge_project_id");
  $("current-project").textContent = "No Project Selected";
  fileTree.innerHTML = "";
  renderEditorTabs();
  chatHistory.innerHTML = "";
  showHome();
  setAuthenticatedState(false);
  if (showOverlay) $("email-input").focus();
}

async function loadProjects(openModal = false) {
  if (!token) return;
  setStatus("Loading projects…");
  try {
    const response = await api("/api/projects/", { cache: "no-store" });
    if (!response.ok) throw new Error(await readError(response, "Could not load projects."));
    projects = await response.json();
    if (!Array.isArray(projects)) projects = [];
    if (!projects.length) {
      currentProjectId = "";
      localStorage.removeItem("codeforge_project_id");
      $("current-project").textContent = "No Project Selected";
      fileTree.innerHTML = '<div class="empty-tree">Create a project to begin.</div>';
      setChatEnabled(false);
      setStatus("Create your first project");
      if (openModal) openProjectModal();
      return;
    }
    const saved = projects.find(p => String(p.id) === String(currentProjectId));
    await selectProject(saved || projects[0], false);
    if (openModal) openProjectModal();
  } catch (error) {
    setStatus("Project load failed", false);
    appendSysMsg(error.message || "Could not load projects.");
    if (openModal) openProjectModal();
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
    const response = await api("/api/projects/", { method:"POST", body:JSON.stringify({ name, slug, description:"" }) });
    if (!response.ok) throw new Error(await readError(response, "Could not create project."));
    const project = await response.json();
    if (!project?.id) throw new Error("The server did not return a project ID.");
    projects = [project, ...projects.filter(p => String(p.id) !== String(project.id))];
    await selectProject(project, true);
  } catch (error) {
    $("project-error").textContent = error.message || "Could not create project.";
  } finally {
    button.disabled = false;
  }
}
async function selectProject(project, closeModal = true) {
  if (!project?.id) return;
  currentProjectId = String(project.id);
  localStorage.setItem("codeforge_project_id", currentProjectId);
  $("current-project").textContent = project.name || "Untitled Project";
  tabs.forEach(t => t.model?.dispose());
  tabs.clear();
  activeTab = "";
  renderEditorTabs();
  clearChat();
  setChatEnabled(true);
  if (closeModal) closeProjectModal();
  setStatus("Loading workspace…");
  await refreshFileTree();
  await refreshStorage();
  const hasHistory = await loadChatHistory();
  updateSettingsDashboard();
  if (hasHistory) showChat(); else showHome();
}
function clearChat() {
  chatHistory.innerHTML = "";
  activeAiMessage = null;
}
async function loadChatHistory() {
  if (!currentProjectId) return false;
  try {
    const response = await api("/api/conversations/"+encodeURIComponent(currentProjectId)+"/history", { cache: "no-store" });
    if (!response.ok) throw new Error(await readError(response, "Could not load chat history."));
    const data = await response.json();
    clearChat();
    const messages = Array.isArray(data.messages) ? data.messages : [];
    messages.forEach(message => {
      if (!message?.content) return;
      const role = message.role === "assistant" ? "ai" : message.role === "user" ? "user" : "sys";
      appendMsg(message.content, role);
    });
    return messages.length > 0;
  } catch (error) {
    appendSysMsg("Chat history could not be loaded: " + (error.message || "unknown error"));
    return false;
  }
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
    row.querySelector("strong").textContent = project.name || "Untitled";
    row.querySelector("small").textContent = project.description || project.slug || "CodeForge workspace";
    row.onclick = () => selectProject(project, true);
    list.appendChild(row);
  });
}
function openProjectModal() {
  renderProjectList();
  $("project-error").textContent = "";
  projectModal.classList.remove("hidden");
  $("new-project-name").focus();
}
function closeProjectModal() { projectModal.classList.add("hidden"); }

function workspacePath(path) {
  return String(path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
}
function persistCollapsedFolders() {
  localStorage.setItem("codeforge_collapsed_folders", JSON.stringify([...collapsedFolders]));
}
async function moveWorkspaceItem(sourcePath, destinationFolder = "") {
  if (!currentProjectId || !sourcePath) return;
  const source = workspacePath(sourcePath);
  const destination = workspacePath(destinationFolder);
  try {
    const response = await api("/api/workspace/" + encodeURIComponent(currentProjectId) + "/move", {
      method: "POST",
      body: JSON.stringify({source, destination})
    });
    if (!response.ok) throw new Error(await readError(response, "Could not move the item."));
    const data = await response.json();
    const movedPath = workspacePath(data.destination || ((destination ? destination + "/" : "") + source.split("/").pop()));

    const affectedTabs = [...tabs.entries()].filter(([path]) => path === source || path.startsWith(source + "/"));
    if (affectedTabs.length) {
      const nextTabs = new Map();
      for (const [path, tab] of tabs.entries()) {
        const affected = path === source || path.startsWith(source + "/");
        if (!affected) { nextTabs.set(path, tab); continue; }
        const nextPath = movedPath + path.slice(source.length);
        clearTimeout(saveTimers.get(path));
        saveTimers.delete(path);
        tab.path = nextPath;
        nextTabs.set(nextPath, tab);
        if (activeTab === path) activeTab = nextPath;
      }
      tabs = nextTabs;
      renderEditorTabs();
      if (activeTab) activateTab(activeTab);
    }

    if (destination) {
      collapsedFolders.delete(destination);
      persistCollapsedFolders();
    }
    await refreshFileTree();
    setStatus("Moved " + source + (destination ? " → " + destination : " to workspace root"));
    pushNotification("Item moved", source + " was moved successfully.", "success");
  } catch (error) {
    appendSysMsg(error.message || "Could not move the item.");
  }
}
function clearTreeDragState() {
  activeDragPath = "";
  document.querySelectorAll(".tree-drop-target").forEach(el => el.classList.remove("tree-drop-target"));
  fileTree.classList.remove("tree-root-drop-target");
  document.querySelectorAll(".is-dragging").forEach(el => el.classList.remove("is-dragging"));
}
function bindTreeDragSource(row, path) {
  row.draggable = true;
  row.addEventListener("dragstart", event => {
    activeDragPath = workspacePath(path);
    row.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", activeDragPath);
    event.dataTransfer.setData("application/x-codeforge-path", activeDragPath);
    try { event.dataTransfer.setDragImage(row, Math.min(24, row.offsetWidth / 4), 14); } catch {}
  });
  row.addEventListener("dragend", clearTreeDragState);
}
function canDropInto(source, destination) {
  const src = workspacePath(source);
  const dst = workspacePath(destination);
  if (!src || src === dst) return false;
  if (itemParent(src) === dst) return false;
  // A folder cannot be dropped into itself or one of its descendants.
  return !(dst && dst.startsWith(src + "/"));
}
function bindFolderDropTarget(row, folderPath) {
  const enter = event => {
    if (!activeDragPath || !canDropInto(activeDragPath, folderPath)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    row.classList.add("tree-drop-target");
  };
  const leave = event => {
    if (!event.relatedTarget || !row.contains(event.relatedTarget)) row.classList.remove("tree-drop-target");
  };
  const drop = async event => {
    if (!activeDragPath || !canDropInto(activeDragPath, folderPath)) return;
    event.preventDefault();
    event.stopPropagation();
    const source = activeDragPath;
    clearTreeDragState();
    await moveWorkspaceItem(source, folderPath);
  };
  row.addEventListener("dragenter", enter);
  row.addEventListener("dragover", enter);
  row.addEventListener("dragleave", leave);
  row.addEventListener("drop", drop);
}
function bindTreeRootDropTarget() {
  fileTree.addEventListener("dragover", event => {
    if (!activeDragPath) return;
    const target = event.target?.closest?.(".folder-row,.file-item");
    if (target) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    fileTree.classList.add("tree-root-drop-target");
  });
  fileTree.addEventListener("dragleave", event => {
    if (event.target === fileTree || !fileTree.contains(event.relatedTarget)) {
      fileTree.classList.remove("tree-root-drop-target");
    }
  });
  fileTree.addEventListener("drop", async event => {
    const target = event.target?.closest?.(".folder-row,.file-item");
    if (target || !activeDragPath) return;
    event.preventDefault();
    const source = activeDragPath;
    clearTreeDragState();
    await moveWorkspaceItem(source, "");
  });
}

function buildFileTree(paths, folders = []) {
  const root = {};
  const ensureFolder = path => {
    let node = root;
    workspacePath(path).split("/").filter(Boolean).forEach(part => {
      node[part] ||= {__children:{},__file:false,__folder:true};
      node[part].__folder = true;
      node = node[part].__children;
    });
  };
  folders.filter(Boolean).forEach(ensureFolder);
  paths.filter(Boolean).forEach(path => {
    let node = root;
    const parts = workspacePath(path).split("/").filter(Boolean);
    parts.forEach((part,i) => {
      node[part] ||= {__children:{},__file:false,__folder:i < parts.length-1};
      if(i === parts.length-1) node[part].__file = true;
      node = node[part].__children;
    });
  });

  fileTree.innerHTML = "";
  const fileCount = $("file-count");
  if(fileCount) fileCount.textContent = String(paths.length);
  if(!paths.length && !folders.length){
    fileTree.innerHTML = '<div class="empty-tree"><strong>Workspace is empty</strong><span>Create a file or folder to start.</span></div>';
    return;
  }

  const render = (node,parent,prefix="") => {
    Object.keys(node).sort((a,b) => {
      const af=node[a].__file,bf=node[b].__file;
      return af===bf ? a.localeCompare(b) : af ? 1 : -1;
    }).forEach(name => {
      const item=node[name];
      const full=prefix ? prefix+"/"+name : name;

      if(item.__folder || Object.keys(item.__children).length){
        const wrap=document.createElement("div");
        wrap.className="folder-wrap"; wrap.dataset.path=full;
        const head=document.createElement("button");
        head.type="button"; head.className="folder-row"; head.dataset.path=full;
        const open=!collapsedFolders.has(full);
        head.innerHTML='<span class="folder-chevron"></span><span class="folder-icon">▸</span><span class="folder-name"></span><span class="folder-count"></span>';
        head.querySelector(".folder-name").textContent=name;
        const children=document.createElement("div");
        children.className="folder-children"+(open?"":" collapsed");
        let openState=open;
        head.querySelector(".folder-count").textContent=Object.keys(item.__children).length || "";
        const syncChevron=()=>{
          head.querySelector(".folder-chevron").textContent=openState?"⌄":"›";
          head.querySelector(".folder-icon").textContent=openState?"▾":"▸";
          head.setAttribute("aria-expanded",String(openState));
        };
        syncChevron();
        head.onclick=()=>{
          openState=!openState;
          children.classList.toggle("collapsed",!openState);
          if(openState) collapsedFolders.delete(full); else collapsedFolders.add(full);
          persistCollapsedFolders(); syncChevron();
        };
        bindTreeDragSource(head,full);
        bindFolderDropTarget(head,full);
        wrap.append(head,children); parent.appendChild(wrap);
        render(item.__children,children,full);
      }

      if(item.__file){
        const row=document.createElement("button");
        row.type="button"; row.className="file-item"; row.dataset.path=full; row.title=full;
        row.innerHTML='<span class="file-symbol">▱</span><span class="file-name"></span><span class="dirty-dot"></span><span class="file-download" title="Download file">⇩</span>';
        row.querySelector(".file-name").textContent=name;
        row.onclick=()=>openFile(full);
        row.querySelector(".file-download").onclick=event=>{event.preventDefault();event.stopPropagation();downloadFile(full);};
        bindTreeDragSource(row,full);
        parent.appendChild(row);
      }
    });
  };
  render(root,fileTree); updateDirtyDots();
}
async function refreshFileTree() {
  if (!currentProjectId) return;
  if (fileTreeRefreshInFlight) return fileTreeRefreshInFlight;
  fileTreeRefreshInFlight = (async () => {
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/tree",{cache:"no-store"});
    if(!response.ok) throw new Error(await readError(response,"Could not load workspace files."));
    const data=await response.json();
    const serverFiles = Array.isArray(data.files) ? data.files : [];
    const serverFolders = Array.isArray(data.folders) ? data.folders : [];
    // Keep files that are currently open visible even if a transient storage
    // listing is incomplete during an AI write/sync cycle.
    const openFiles = [...tabs.keys()];
    const visibleFiles = [...new Set([...serverFiles, ...openFiles])];
    const visibleFolders = [...new Set([...serverFolders, ...openFiles.map(path => path.split("/").slice(0,-1).join("/")).filter(Boolean)])];
    buildFileTree(visibleFiles, visibleFolders);
    setStatus("Workspace ready");
  } catch(error) {
    setStatus("Workspace unavailable",false);
    appendSysMsg(error.message||"Could not load workspace files.");
  } finally {
    fileTreeRefreshInFlight = null;
  }
  })();
  return fileTreeRefreshInFlight;
}
function filterFiles(query) {
  const q=(query||"").toLowerCase().trim();
  document.querySelectorAll(".file-item").forEach(item=>item.style.display=item.dataset.path.toLowerCase().includes(q)?"flex":"none");
  document.querySelectorAll(".folder-wrap").forEach(wrap=>{
    const visible=[...wrap.querySelectorAll(".file-item")].some(x=>x.style.display!=="none");
    wrap.style.display=!q||visible?"block":"none";
    if(q&&visible) wrap.querySelector(".folder-children")?.classList.remove("collapsed");
  });
}
function updateDirtyDots() {
  tabs.forEach((tab,path)=>{
    const el=document.querySelector('.file-item[data-path="'+CSS.escape(path)+'"] .dirty-dot');
    if(el) el.style.opacity=tab.dirty?"1":"0";
  });
}
function languageFor(path) {
  const ext=path.includes(".")?path.split(".").pop().toLowerCase():"";
  return {py:"python",js:"javascript",jsx:"javascript",ts:"typescript",tsx:"typescript",html:"html",css:"css",json:"json",md:"markdown",sql:"sql",java:"java",cpp:"cpp",c:"c",cs:"csharp",go:"go",rs:"rust",sh:"shell",yaml:"yaml",yml:"yaml",xml:"xml"}[ext]||"plaintext";
}
async function openFile(path) {
  if(!currentProjectId) return;
  if(tabs.has(path)){activateTab(path);return;}
  if(!editorReady){appendSysMsg("Editor is still loading.");return;}
  setStatus("Opening "+path+"…");
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file?path="+encodeURIComponent(path));
    if(!response.ok) throw new Error(await readError(response,"Could not open file."));
    const data=await response.json();
    const model=monaco.editor.createModel(data.content||"",languageFor(path),monaco.Uri.parse("codeforge://"+currentProjectId+"/"+path));
    tabs.set(path,{path,model,savedContent:data.content||"",dirty:false});
    renderEditorTabs(); activateTab(path); setStatus("Opened "+path);
  } catch(error){appendSysMsg(error.message||"Could not open file.");}
}
function activateTab(path) {
  const tab=tabs.get(path); if(!tab||!editorReady)return;
  activeTab=path; editor.setModel(tab.model);
  monaco.editor.setModelLanguage(tab.model,languageFor(path));
  $("editor-preview").classList.add("has-file");
  $("right-editor-tabs").querySelectorAll(".right-file-tab").forEach(x=>x.classList.toggle("active",x.dataset.path===path));
  document.querySelectorAll(".file-item").forEach(x=>x.classList.toggle("active",x.dataset.path===path));
  renderEditorTabs(); updateRightPreview();
}
function renderEditorTabs() {
  const host=$("right-editor-tabs"); host.innerHTML="";
  tabs.forEach((tab,path)=>{
    const b=document.createElement("button"); b.type="button"; b.className="right-file-tab"+(path===activeTab?" active":""); b.dataset.path=path;
    b.innerHTML='<span></span><span class="right-file-label"></span><i data-action="download" title="Download file">⇩</i><i data-action="close" title="Close file">×</i>';
    b.querySelector(".right-file-label").textContent=path.split("/").pop();
    b.title=path;
    b.onclick=e=>{
      const action=e.target?.dataset?.action;
      if(action==="download"){e.stopPropagation();downloadFile(path);}
      else if(action==="close"){e.stopPropagation();closeTab(path);}
      else activateTab(path);
    };
    host.appendChild(b);
  });
}
function updateRightPreview() {
  const preview=$("editor-preview");
  if(!activeTab){ preview.classList.remove("has-file"); return; }
  const tab=tabs.get(activeTab); if(!tab)return;
  let mini=$("right-code-status");
  if(!mini){
    mini=document.createElement("div"); mini.id="right-code-status"; mini.className="right-code-status";
    preview.appendChild(mini);
  }
  mini.textContent=activeTab+(tab.dirty?" • Unsaved":"");
}
async async function closeTab(path) {
  const tab=tabs.get(path); if(!tab)return;
  clearTimeout(saveTimers.get(path)); saveTimers.delete(path);
  if(tab.dirty){
    const saved=await saveFilePath(path);
    if(!saved && !confirm("The file could not be saved. Close it anyway?"))return;
  }
  tab.model.dispose(); tabs.delete(path);
  if(activeTab===path){
    const next=[...tabs.keys()].pop()||"";
    activeTab=""; if(next)activateTab(next); else if(editor)editor.setModel(null);
  }
  renderEditorTabs(); updateRightPreview();
}
function scheduleAutoSave(path) {
  if (!path) return;
  clearTimeout(saveTimers.get(path));
  const timer = setTimeout(async () => {
    saveTimers.delete(path);
    const tab = tabs.get(path);
    if (!tab?.dirty || !currentProjectId) return;
    await saveFilePath(path);
  }, 1200);
  saveTimers.set(path, timer);
}
async function saveFilePath(path) {
  const tab=tabs.get(path); if(!tab||!currentProjectId)return false;
  const content=tab.model.getValue();
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file",{method:"PUT",body:JSON.stringify({path:tab.path,content})});
    if(!response.ok) throw new Error(await readError(response,"Could not save file."));
    tab.savedContent=content;tab.dirty=false;updateDirtyDots();updateRightPreview();pushNotification("File saved",path+" was saved to the project workspace.","success");
    return true;
  } catch(error) {
    setStatus("Auto-save failed",false);
    appendSysMsg("Could not save "+path+": "+(error.message||"unknown error"));
    return false;
  }
}

async function saveCurrentFile() {
  const tab=tabs.get(activeTab); if(!tab||!currentProjectId)return;
  clearTimeout(saveTimers.get(activeTab)); saveTimers.delete(activeTab);
  setStatus("Saving "+tab.path+"…");
  const saved=await saveFilePath(activeTab);
  if(saved)setStatus("Saved "+tab.path);
}
function itemParent(path) {
  const normalized = workspacePath(path);
  const parts = normalized.split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}
function openFileCreateAtFolder(folderPath = "") {
  if(!currentProjectId){appendSysMsg("Create or select a project first.");return;}
  $("new-file-path").value = folderPath ? folderPath + "/" : "";
  $("new-file-content").value = "";
  $("file-create-error").textContent = "";
  fileCreateModal.classList.remove("hidden");
  $("new-file-path").focus();
}
function openFolderCreateAtFolder(folderPath = "") {
  if(!currentProjectId){appendSysMsg("Create or select a project first.");return;}
  $("new-folder-path").value = folderPath ? folderPath + "/" : "";
  $("folder-create-error").textContent = "";
  $("folder-create-modal").classList.remove("hidden");
  $("new-folder-path").focus();
}
async function renameWorkspaceItem(path) {
  const current = workspacePath(path);
  if (!current) return;
  const currentName = current.split("/").pop();
  $("rename-item-name").value = currentName;
  $("rename-item-error").textContent = "";
  $("rename-item-modal").dataset.path = current;
  $("rename-item-modal").classList.remove("hidden");
  $("rename-item-name").focus();
  $("rename-item-name").select();
}
function closeRenameItem(){ $("rename-item-modal").classList.add("hidden"); }
async function submitRenameItem() {
  const modal = $("rename-item-modal");
  const path = workspacePath(modal.dataset.path || "");
  const name = $("rename-item-name").value.trim();
  if (!path || !name || name.includes("/") || name.includes("\\") || name === "." || name === "..") {
    $("rename-item-error").textContent = "Enter a valid name.";
    return;
  }
  const button = $("confirm-rename-item-btn");
  button.disabled = true;
  try {
    const response = await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/rename", {
      method:"POST", body:JSON.stringify({path,name})
    });
    if(!response.ok) throw new Error(await readError(response,"Could not rename the item."));
    const data = await response.json();
    const nextPath = workspacePath(data.destination || itemParent(path)+"/"+name);
    const nextTabs = new Map();
    for (const [tabPath, tab] of tabs.entries()) {
      if (tabPath !== path && !tabPath.startsWith(path + "/")) { nextTabs.set(tabPath, tab); continue; }
      const updatedPath = nextPath + tabPath.slice(path.length);
      clearTimeout(saveTimers.get(tabPath)); saveTimers.delete(tabPath);
      tab.path = updatedPath;
      nextTabs.set(updatedPath, tab);
      if(activeTab === tabPath) activeTab = updatedPath;
    }
    tabs = nextTabs;
    closeRenameItem();
    renderEditorTabs();
    if(activeTab) activateTab(activeTab);
    await refreshFileTree();
    setStatus("Renamed "+path+" → "+nextPath);
    pushNotification("Item renamed",path+" was renamed successfully.","success");
  } catch(error) {
    $("rename-item-error").textContent = error.message || "Could not rename the item.";
  } finally { button.disabled = false; }
}
async function deleteWorkspaceItem(path) {
  const target = workspacePath(path);
  if(!target || !currentProjectId) return;
  const isFolder = contextMenuIsFolder;
  const label = isFolder ? "folder" : "file";
  if(!confirm("Delete "+label+" '"+target+"'?"+(isFolder?"\n\nEverything inside this folder will be deleted.":""))) return;
  try {
    const response = await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/item?path="+encodeURIComponent(target),{method:"DELETE"});
    if(!response.ok) throw new Error(await readError(response,"Could not delete the item."));
    const affected=[...tabs.keys()].filter(p=>p===target||p.startsWith(target+"/"));
    for(const p of affected){
      const tab=tabs.get(p);
      clearTimeout(saveTimers.get(p)); saveTimers.delete(p);
      tab?.model?.dispose(); tabs.delete(p);
      if(activeTab===p) activeTab="";
    }
    if(!activeTab && tabs.size){activeTab=[...tabs.keys()].pop();activateTab(activeTab);}
    else if(!activeTab && editor) editor.setModel(null);
    renderEditorTabs(); updateRightPreview();
    await refreshFileTree(); await refreshStorage();
    setStatus("Deleted "+target);
    pushNotification("Item deleted",target+" was removed from the workspace.","success");
  } catch(error) { appendSysMsg(error.message || "Could not delete the item."); }
}
function showExplorerContextMenu(event, path="", isFolder=false) {
  event.preventDefault();
  event.stopPropagation();
  const menu=$("explorer-context-menu");
  if(!menu) return;
  contextMenuPath=workspacePath(path);
  contextMenuIsFolder=Boolean(isFolder);
  contextMenuParent=isFolder?contextMenuPath:itemParent(contextMenuPath);
  const hasItem=Boolean(contextMenuPath);
  menu.querySelector("[data-context-action='open']").hidden=!hasItem||isFolder;
  menu.querySelector("[data-context-action='download']").hidden=!hasItem||isFolder;
  menu.querySelector("[data-context-action='new-file']").hidden=false;
  menu.querySelector("[data-context-action='new-folder']").hidden=false;
  menu.querySelector("[data-context-action='rename']").hidden=!hasItem;
  menu.querySelector("[data-context-action='delete']").hidden=!hasItem;
  menu.querySelector(".context-item-label").textContent=hasItem?contextMenuPath:"Workspace";
  menu.classList.remove("hidden");
  const rect=menu.getBoundingClientRect();
  const x=Math.min(event.clientX,window.innerWidth-rect.width-8);
  const y=Math.min(event.clientY,window.innerHeight-rect.height-8);
  menu.style.left=Math.max(8,x)+"px";
  menu.style.top=Math.max(8,y)+"px";
}
function closeExplorerContextMenu(){
  $("explorer-context-menu")?.classList.add("hidden");
}
function handleExplorerContextAction(action){
  const path=contextMenuPath, folder=contextMenuIsFolder, parent=contextMenuParent;
  closeExplorerContextMenu();
  if(action==="open" && path) openFile(path);
  else if(action==="download" && path) downloadFile(path);
  else if(action==="new-file") openFileCreateAtFolder(folder?path:parent);
  else if(action==="new-folder") openFolderCreateAtFolder(folder?path:parent);
  else if(action==="rename" && path) renameWorkspaceItem(path);
  else if(action==="delete" && path) deleteWorkspaceItem(path);
}

function openFileCreate() {
  if(!currentProjectId){appendSysMsg("Create or select a project first.");return;}
  $("new-file-path").value="";$("new-file-content").value="";$("file-create-error").textContent="";
  fileCreateModal.classList.remove("hidden");$("new-file-path").focus();
}
function closeFileCreate(){fileCreateModal.classList.add("hidden");}
async function createFile() {
  const path=$("new-file-path").value.trim().replace(/\\/g,"/");
  const content=$("new-file-content").value;
  if(!path||path.startsWith("/")||path.includes("..")){$("file-create-error").textContent="Enter a safe relative path.";return;}
  if(path.endsWith("/")){$("file-create-error").textContent="Enter a filename.";return;}
  const button=$("confirm-file-create-btn");button.disabled=true;
  try{
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file",{method:"PUT",body:JSON.stringify({path,content})});
    if(!response.ok)throw new Error(await readError(response,"Could not create file."));
    closeFileCreate();await refreshFileTree();await openFile(path);setStatus("Created "+path);pushNotification("File created",path+" was added to the project.","success");
  }catch(error){$("file-create-error").textContent=error.message||"Could not create file.";}
  finally{button.disabled=false;}
}
function openFolderCreate() {
  if(!currentProjectId){appendSysMsg("Create or select a project first.");return;}
  $("new-folder-path").value="";
  $("folder-create-error").textContent="";
  $("folder-create-modal").classList.remove("hidden");
  $("new-folder-path").focus();
}
function closeFolderCreate(){$("folder-create-modal").classList.add("hidden");}
async function createFolder() {
  const path=$("new-folder-path").value.trim().replace(/\\/g,"/").replace(/^\/+|\/+$/g,"");
  if(!path||path.startsWith(".")||path.includes("..")||path.split("/").some(part=>part.startsWith("."))){
    $("folder-create-error").textContent="Enter a safe relative folder path.";
    return;
  }
  const button=$("confirm-folder-create-btn");button.disabled=true;
  try{
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/folder",{method:"POST",body:JSON.stringify({path})});
    if(!response.ok)throw new Error(await readError(response,"Could not create folder."));
    closeFolderCreate();await refreshFileTree();setStatus("Created "+path);pushNotification("Folder created",path+" was added to the project.","success");
  }catch(error){$("folder-create-error").textContent=error.message||"Could not create folder.";}
  finally{button.disabled=false;}
}

async async function deleteActiveFile() {
  if(!activeTab||!currentProjectId)return;
  const path=activeTab;
  if(!confirm("Delete "+path+" permanently?"))return;
  const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/item?path="+encodeURIComponent(path),{method:"DELETE"});
  if(!response.ok){appendSysMsg(await readError(response,"Could not delete file."));return;}
  closeTab(path);await refreshFileTree();setStatus("Deleted "+path);pushNotification("File deleted",path+" was removed from the project.","warning");
}

async function downloadBlob(path, filename) {
  if(!currentProjectId) return;
  try {
    const response=await api(path);
    if(!response.ok) throw new Error(await readError(response,"Download failed."));
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement("a");
    link.href=url; link.download=filename || "download";
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch(error) { appendSysMsg(error.message || "Download failed."); }
}
async function downloadFile(path) {
  await downloadBlob("/api/workspace/"+encodeURIComponent(currentProjectId)+"/download?path="+encodeURIComponent(path),path.split("/").pop());
  setStatus("Downloaded "+path);pushNotification("Download ready",path+" was downloaded.","success");
}
async function downloadAllFiles() {
  if(!currentProjectId){appendSysMsg("Select a project before downloading.");return;}
  await downloadBlob("/api/workspace/"+encodeURIComponent(currentProjectId)+"/download-all","codeforge-project.zip");
  setStatus("Downloaded project ZIP");pushNotification("Project ZIP ready","The complete project archive was downloaded.","success");
}
async function refreshStorage() {
  if(!currentProjectId)return;
  try{
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/storage",{cache:"no-store"});
    if(!response.ok)return;
    const data=await response.json();
    const used=Number(data.used_bytes)||0, limit=Number(data.project_limit_bytes)||1;
    const pct=Math.min(100,used/limit*100);
    const bar=document.querySelector(".storage-bar span");
    const text=document.querySelector(".storage-text");
    if(bar)bar.style.width=Math.max(1,pct)+"%";
    if(text)text.textContent=formatBytes(used)+" of "+formatBytes(limit)+" used • "+(data.file_count||0)+" files";
  }catch{}
}
function formatBytes(bytes){
  if(bytes<1024)return bytes+" B";
  const units=["KB","MB","GB","TB"];let n=bytes/1024,i=0;
  while(n>=1024&&i<units.length-1){n/=1024;i++;}
  return n>=100?Math.round(n)+" "+units[i]:n.toFixed(1)+" "+units[i];
}

function showHome() {
  $("home-view").classList.remove("hidden");
  $("chat-view").classList.add("hidden");
  $("terminal-panel").classList.add("hidden");
}
function showChat() {
  $("home-view").classList.add("hidden");
  $("chat-view").classList.remove("hidden");
  $("terminal-panel").classList.add("hidden");
  chatInput.focus();
}
function toggleRightTerminal(force) {
  const next = typeof force === "boolean" ? force : !Boolean(settings.terminalOpen);
  settings.terminalOpen = next;
  persistSettings();
  applyPanelWidths();
  if(next) {
    setRail("rail-terminal");
    setRightTerminalTab("terminal");
    refreshTerminalStatus();
    setTimeout(() => {
      const input=$("right-terminal-command");
      if(input) input.focus();
    }, 30);
  } else {
    setRail("rail-chat");
    chatInput?.focus();
  }
}
function showTerminal() {
  // The terminal belongs below the right-side code playground, not in the chat pane.
  showChat();
  toggleRightTerminal(true);
}
function setRail(activeId){
  document.querySelectorAll(".rail-item").forEach(x=>x.classList.toggle("active",x.id===activeId));
}
function bindPromptButtons(){
  document.querySelectorAll(".action-card").forEach(button=>{
    button.onclick=()=>{
      const mode=button.dataset.mode||"build";
      const prompt=button.dataset-prompt||"";
      pendingActionMode=mode;
      if($("agent-mode-select"))$("agent-mode-select").value=mode;
      if(!currentProjectId){
        if(mode==="build" && button.dataset.action==="create") {
          openProjectModal();
        } else {
          pushNotification("Project required","Select or create a project before using this workspace action.","warning");
          openProjectModal();
        }
        return;
      }
      chatInput.value=prompt;
      showChat();
      setChatEnabled(true);
      sendChatMessage(mode);
    };
  });
  document.querySelectorAll(".example-prompt,.help-grid [data-prompt]").forEach(button=>{
    button.onclick=()=>{
      if(!currentProjectId){openProjectModal();return;}
      pendingActionMode="build";
      if($("agent-mode-select"))$("agent-mode-select").value="build";
      chatInput.value=button.dataset.prompt||"";
      showChat();setChatEnabled(true);sendChatMessage("build");
    };
  });
}
function pushNotification(title,message,type="info"){
  const item={id:Date.now()+"-"+Math.random().toString(36).slice(2),title,message,type,created_at:new Date().toISOString(),read:false};
  notifications=[item,...notifications].slice(0,30);
  localStorage.setItem("codeforge_notifications",JSON.stringify(notifications));
  renderNotifications();
}
function renderNotifications(){
  const list=$("notification-list"), badge=$("notification-badge");
  if(!list)return;
  const unread=notifications.filter(n=>!n.read).length;
  if(badge){badge.textContent=unread>9?"9+":String(unread);badge.classList.toggle("hidden",unread===0);}
  if(!notifications.length){
    list.innerHTML='<div class="notification-empty"><span>✦</span><strong>You’re all caught up</strong><small>Workspace activity will appear here.</small></div>';
    return;
  }
  list.innerHTML=notifications.map(n=>{
    const icon=n.type==="success"?"✓":n.type==="error"?"!":n.type==="warning"?"⚠":"•";
    return '<button class="notification-item '+(n.read?"":"unread")+'" data-notification-id="'+escapeHtml(n.id)+'" type="button"><span class="notification-icon '+escapeHtml(n.type)+'">'+icon+'</span><span class="notification-copy"><strong>'+escapeHtml(n.title)+'</strong><small>'+escapeHtml(n.message)+'</small><time>'+formatNotificationTime(n.created_at)+'</time></span></button>';
  }).join("");
  list.querySelectorAll(".notification-item").forEach(el=>el.onclick=()=>{
    const n=notifications.find(x=>x.id===el.dataset.notificationId); if(n)n.read=true;
    localStorage.setItem("codeforge_notifications",JSON.stringify(notifications)); renderNotifications();
  });
}
function formatNotificationTime(value){
  const date=new Date(value), diff=Math.max(0,Date.now()-date.getTime());
  const mins=Math.floor(diff/60000); if(mins<1)return "Just now"; if(mins<60)return mins+"m ago";
  const hours=Math.floor(mins/60); if(hours<24)return hours+"h ago"; return date.toLocaleDateString();
}
function openNotifications(){
  const panel=$("notifications-panel");
  if(!panel)return;
  panel.classList.toggle("hidden");
  if(!panel.classList.contains("hidden"))renderNotifications();
}
function markNotificationsRead(){
  notifications=notifications.map(n=>({...n,read:true}));
  localStorage.setItem("codeforge_notifications",JSON.stringify(notifications));
  renderNotifications();
}
function clearNotifications(){
  notifications=[];
  localStorage.setItem("codeforge_notifications","[]");
  renderNotifications();
}


function parseContextDirectives(message){
  const directives=[];
  const re=/@(workspace|selection|file|folder)(?::([^\s]+))?/g; let m;
  while((m=re.exec(message))){
    directives.push(m[1]==="file"?"@file:"+(m[2]||""):m[1]==="folder"?"@folder:"+(m[2]||""):"@"+m[1]);
  }
  return [...new Set(directives)];
}
async function buildAiContext(message){
  const directives=parseContextDirectives(message);
  const selection=editor&&editorReady&&activeTab?(()=>{
    const s=editor.getSelection(), model=editor.getModel();
    if(!s||!model||s.isEmpty())return null;
    return {path:activeTab,startLine:s.startLineNumber,endLine:s.endLineNumber,text:model.getValueInRange(s).slice(0,16000)};
  })():null;
  if(!directives.length&&!selection)return {};
  if(selection&&!directives.includes("@selection"))directives.push("@selection");
  try{
    const response=await api("/api/context/"+encodeURIComponent(currentProjectId)+"/context",{
      method:"POST",body:JSON.stringify({directives:directives.length?directives:["@workspace"],selection,query:message})
    });
    if(!response.ok)throw new Error(await readError(response,"Could not build workspace context."));
    return await response.json();
  }catch(error){
    pushNotification("Context unavailable",error.message||"Workspace context could not be loaded.","warning");
    return {};
  }
}
let inlineEditState=null;
let lastCheckpointId="";
let lastChangeSetId="";
function openInlineAi(){
  if(!editor||!activeTab){pushNotification("Open a file first","Select a file in the editor before using Inline AI.","warning");return;}
  const sel=editor.getSelection(),model=editor.getModel();
  if(!sel||sel.isEmpty()){pushNotification("Select some code","Highlight the code you want Inline AI to edit.","warning");return;}
  inlineEditState={path:activeTab,selection:model.getValueInRange(sel),range:sel};
  $("inline-ai-selection").textContent=inlineEditState.selection;
  $("inline-ai-preview-wrap").classList.add("hidden");
  $("inline-ai-preview").textContent="";
  $("inline-ai-instruction").value="";
  $("inline-ai-error").textContent="";
  $("inline-ai-run").textContent="Generate edit";
  $("inline-ai-run").disabled=false;
  $("inline-ai-modal").classList.remove("hidden");
  setTimeout(()=>$("inline-ai-instruction")?.focus(),50);
}
async function runInlineAi(){
  if(!inlineEditState)return;
  const button=$("inline-ai-run"), instruction=$("inline-ai-instruction").value.trim();
  if(!instruction){$("inline-ai-error").textContent="Describe the change you want.";return;}
  if(inlineEditState.replacement!==undefined){
    const model=editor.getModel();
    model.pushEditOperations([], [{range:inlineEditState.range,text:inlineEditState.replacement}], ()=>null);
    const tab=tabs.get(activeTab);
    if(tab){tab.dirty=true;updateDirtyDots();updateRightPreview();scheduleAutoSave(activeTab);}
    $("inline-ai-modal").classList.add("hidden");
    pushNotification("Inline edit applied",activeTab+" was updated. Review the change before continuing.","success");
    inlineEditState=null;
    return;
  }
  button.disabled=true;button.textContent="Generating…";$("inline-ai-error").textContent="";
  try{
    const response=await api("/api/context/"+encodeURIComponent(currentProjectId)+"/inline-edit",{
      method:"POST",
      body:JSON.stringify({path:inlineEditState.path,selection:inlineEditState.selection,instruction,model:$("model-select").value})
    });
    if(!response.ok)throw new Error(await readError(response,"Inline AI failed."));
    const data=await response.json();
    inlineEditState.replacement=data.replacement||"";
    $("inline-ai-preview").textContent=inlineEditState.replacement;
    $("inline-ai-preview-wrap").classList.remove("hidden");
    button.textContent="Apply edit";button.disabled=false;
  }catch(error){
    $("inline-ai-error").textContent=error.message||"Inline AI failed.";
    button.disabled=false;button.textContent="Generate edit";
  }
}

async function sendChatMessage(mode = pendingActionMode || $("agent-mode-select")?.value || "build") {
  pendingActionMode=mode;
  const message=chatInput.value.trim();
  if(!message||!currentProjectId||agentRunning)return;
  showChat();
  chatInput.value="";
  activeAiMessage=null;
  appendMsg(message,"user");
  showThinkingMessage("CodeForge is analyzing your request…");
  agentRunning=true;streamHadError=false;
  setChatEnabled(true);setStatus("Agent working…");
  pushNotification("AI task started", mode.charAt(0).toUpperCase()+mode.slice(1)+" task started in "+($("current-project").textContent||"your project")+".","info");
  agentOutput.innerHTML="";
  let contextual="[CodeForge context: model="+$("model-select").value+"]\n\n"+message;
  const context=await buildAiContext(message);
  if(context.text)contextual+="\n\nWorkspace context prepared from "+(context.directives||[]).join(", ")+".\n";
  if(attachedContext){contextual+="\n\nAttached file context:\n"+attachedContext;attachedContext="";}
  try{
    const response=await api("/api/agent/"+encodeURIComponent(currentProjectId)+"/chat",{method:"POST",body:JSON.stringify({message:contextual,mode,model:$("model-select").value,context,workflow:$("autopilot-toggle")?.checked?"autopilot":"standard"})});
    if(!response.ok)throw new Error(await readError(response,"Agent request failed."));
    if(!response.body)throw new Error("The agent returned no stream.");
    const reader=response.body.getReader(),decoder=new TextDecoder();
    let buffer="";
    while(true){
      const {value,done}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true});
      const chunks=buffer.split("\n\n");buffer=chunks.pop()||"";
      for(const chunk of chunks)await processSseChunk(chunk);
    }
    if(buffer.trim())await processSseChunk(buffer);
  }catch(error){streamHadError=true;appendSysMsg(error.message||"Error communicating with AI agent.");}
  finally{
    clearThinkingMessage();
    agentRunning=false;activeAiMessage=null;setChatEnabled(true);
    if(!streamHadError){setStatus("Workspace ready");pushNotification("AI task completed","The "+mode+" task finished successfully.","success");}else{pushNotification("AI task failed","The "+mode+" task ended with an error. Check Agent Output.","error");}
    await refreshFileTree();await refreshStorage();
  }
}
async function processSseChunk(chunk){
  const lines=chunk.split(/\r?\n/).filter(x=>x.startsWith("data:"));
  if(!lines.length)return;
  try{await handleAgentEvent(JSON.parse(lines.map(x=>x.slice(5).trim()).join("")));}
  catch{appendSysMsg("Received an invalid agent event.");}
}
async function handleAgentEvent(data){
  if(!data)return;
  if(data.type==="message_delta"){
    clearThinkingMessage();
    if(!activeAiMessage){activeAiMessage=appendMsg("","ai");}
    activeAiMessage.textContent+=(data.content||"");chatHistory.scrollTop=chatHistory.scrollHeight;return;
  }
  if(data.type==="message"){
    clearThinkingMessage();
    if(activeAiMessage){if(data.content&&!activeAiMessage.textContent)activeAiMessage.textContent=data.content;activeAiMessage=null;}
    else appendMsg(data.content||"","ai");
    return;
  }
  if(data.type==="tool_call"){
    showThinkingMessage(data.tool==="run_command" ? "Running a project check…" : "Working with "+(data.tool||"your project")+"…");
    addTimeline("tool",data.tool||"Tool",JSON.stringify(data.args||{}),"running");
    addRightAgentTimeline("tool",data.tool||"Tool",JSON.stringify(data.args||{}),"running");
    if(data.tool==="run_command"){ terminalOutput.textContent+="\n$ "+(data.args?.command||"")+" \n"; appendRightTerminal("\n$ "+(data.args?.command||"")+" \n"); }
    return;
  }
  if(data.type==="tool_result"){
    addTimeline(data.success?"success":"error",(data.tool||"Tool")+(data.success?" completed":" failed"),data.result||"","done");
    addRightAgentTimeline(data.success?"success":"error",(data.tool||"Tool")+(data.success?" completed":" failed"),data.result||"","done");
    if(data.tool==="run_command"){terminalOutput.textContent+="\n"+(data.result||"")+"\n";terminalOutput.scrollTop=terminalOutput.scrollHeight;appendRightTerminal("\n"+(data.result||"")+"\n");}
    return;
  }
  if(data.type==="file_change"){
    showThinkingMessage("Updating "+(data.path||"the workspace")+"…");
    addTimeline("file","File changed",data.path||"","done");
    addRightAgentTimeline("file","File changed",data.path||"","done");
    await refreshFileTree();await refreshStorage();
    if(data.path&&tabs.has(data.path))await reloadTab(data.path);
    return;
  }
  if(data.type==="mode"){ addTimeline("mode","Mode: "+(data.label||data.mode||"Agent"),"Steps "+(data.limits?.max_steps??"—")+" · Tools "+(data.limits?.max_tool_calls??"—")+" · File changes "+(data.limits?.max_file_changes??"—"),"done"); addRightAgentTimeline("mode","Mode: "+(data.label||data.mode||"Agent"),"Execution policy loaded","done"); return; }
  if(data.type==="budget"){ streamHadError=true; addTimeline("error","Agent budget reached",(data.kind||"Budget")+" limit: "+(data.limit??"—"),"error"); addRightAgentTimeline("error","Agent budget reached",(data.kind||"Budget")+" limit: "+(data.limit??"—"),"error"); return; }
  if(data.type==="checkpoint"){lastCheckpointId=data.checkpoint_id||"";$("undo-ai-btn")?.classList.toggle("hidden",!lastCheckpointId);addTimeline("checkpoint","Workspace checkpoint",data.file_count+" files saved before AI changes","done");addRightAgentTimeline("checkpoint","Workspace checkpoint",data.file_count+" files saved before AI changes","done");return;}
  if(data.type==="workflow_phase"){ addTimeline(data.status==="started"?"mode":"success","Autopilot: "+(data.phase||"phase"),(data.mode||"")+" · "+(data.status||""),data.status==="started"?"running":"done"); addRightAgentTimeline("mode","Autopilot: "+(data.phase||"phase"),(data.mode||"")+" · "+(data.status||""),data.status==="started"?"running":"done"); return; }
  if(data.type==="background_job"){ addTimeline("mode","Background indexing queued",data.job_id||"Workspace index","running"); addRightAgentTimeline("mode","Background indexing queued",data.job_id||"Workspace index","running"); return; }
  if(data.type==="test_diagnostics"){ const s=data.summary||{}; const ok=s.status==="pass"; addTimeline(ok?"success":"error","Test diagnostics",((s.errors||0)+" errors · "+(s.warnings||0)+" warnings"),ok?"done":"error"); addRightAgentTimeline(ok?"success":"error","Test diagnostics",((s.errors||0)+" errors · "+(s.warnings||0)+" warnings"),ok?"done":"error"); if(!ok)streamHadError=true; return; }
  if(data.type==="workflow_complete"){ const ok=data.status==="passed"; addTimeline(ok?"success":"error","Autopilot "+(ok?"completed":"stopped"),"Iterations "+(data.iterations??"—"),ok?"done":"error"); addRightAgentTimeline(ok?"success":"error","Autopilot "+(ok?"completed":"stopped"),"Iterations "+(data.iterations??"—"),ok?"done":"error"); if(!ok)streamHadError=true; return; }
  if(data.type==="change_set"){ lastChangeSetId=data.change_set_id||""; openChangeReview(lastChangeSetId); addTimeline("file","AI changes ready for review",(data.file_count||0)+" files · choose Keep all or Reject all","done"); return; }
  if(data.type==="done"){
    clearThinkingMessage();
    if(!activeAiMessage && data.message) appendMsg(data.message,"ai");
    addTimeline("success","Agent finished","Workspace synchronized","done");addRightAgentTimeline("success","Agent finished","Workspace synchronized","done");return;}
  if(data.type==="warning"){
    clearThinkingMessage();
    appendSysMsg(data.message || "Workspace warning.");
    refreshFileTree();
    return;
  }
  if(data.type==="error"){clearThinkingMessage();streamHadError=true;setStatus("Agent failed",false);addTimeline("error","Agent error",data.message||"Unknown error","error");addRightAgentTimeline("error","Agent error",data.message||"Unknown error","error");appendSysMsg(data.message||"Agent error");}
}
async function reloadTab(path){
  const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file?path="+encodeURIComponent(path));
  if(!response.ok)return;
  const data=await response.json(),tab=tabs.get(path);if(!tab)return;
  tab.model.setValue(data.content||"");tab.savedContent=data.content||"";tab.dirty=false;updateDirtyDots();updateRightPreview();
}
function addTimeline(type,title,detail,status){
  const card=document.createElement("div");card.className="timeline-card "+type+" "+status;
  card.innerHTML='<div class="timeline-icon"></div><div class="timeline-copy"><strong></strong><span></span></div><div class="timeline-status"></div>';
  card.querySelector("strong").textContent=title;card.querySelector("span").textContent=detail;card.querySelector(".timeline-status").textContent=status==="done"?"✓":"!";
  agentOutput.appendChild(card);agentOutput.scrollTop=agentOutput.scrollHeight;
}
async function refreshTerminalStatus(){
  const badge=$("terminal-sandbox-status"), run=$("right-terminal-run-btn");
  if(!badge)return;
  if(!currentProjectId){
    badge.textContent="Select a project";
    badge.dataset.state="idle";
    if(run)run.disabled=true;
    return;
  }
  badge.textContent="Checking…"; badge.dataset.state="checking";
  try{
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/terminal/status",{cache:"no-store"});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.detail||"Status unavailable");
    badge.textContent=data.ready ? data.label : data.label;
    badge.dataset.state=data.ready?"ready":"error";
    badge.title=data.detail||"";
    if(run)run.disabled=!data.ready || terminalBusy;
  }catch(error){
    badge.textContent="Unavailable";
    badge.dataset.state="error";
    badge.title=error.message||"Terminal status unavailable";
    if(run)run.disabled=true;
  }
}
function setRightTerminalTab(tab) {
  const terminal = tab === "terminal";
  $("right-terminal-tab-btn")?.classList.toggle("active",terminal);
  $("right-agent-tab")?.classList.toggle("active",!terminal);
  $("right-terminal-view")?.classList.toggle("hidden",!terminal);
  $("right-agent-view")?.classList.toggle("hidden",terminal);
}
function appendRightTerminal(text) {
  const out=$("right-terminal-output"); if(!out)return;
  out.textContent+=(text||"");
  out.scrollTop=out.scrollHeight;
}
function clearRightTerminal() {
  if($("right-terminal-output")) $("right-terminal-output").textContent="";
  if($("right-agent-output")) $("right-agent-output").innerHTML='<div class="right-agent-empty">Agent activity will appear here.</div>';
}
function addRightAgentTimeline(type,title,detail,status) {
  const host=$("right-agent-output"); if(!host)return;
  host.querySelector(".right-agent-empty")?.remove();
  const card=document.createElement("div"); card.className="right-agent-card "+type+" "+status;
  card.innerHTML='<span class="right-agent-dot"></span><div><strong></strong><small></small></div><em></em>';
  card.querySelector("strong").textContent=title;
  card.querySelector("small").textContent=detail || "";
  card.querySelector("em").textContent=status==="done"?"✓":"!";
  host.appendChild(card); host.scrollTop=host.scrollHeight;
}
async function runRightTerminalCommand(){
  const input=$("right-terminal-command"), command=input?.value.trim();
  if(!command || terminalBusy) return;
  if(!currentProjectId){ appendRightTerminal("\nSelect or create a project before running commands.\n"); return; }
  terminalBusy=true; $("right-terminal-run-btn").disabled=true;
  appendRightTerminal("\n$ "+command+"\n…\n");
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/terminal",{method:"POST",body:JSON.stringify({command,timeout:60})});
    const data=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data.detail||data.message||"Terminal command failed.");
    const result=(data.output||"")+(data.error?data.error+"\n":"");
    appendRightTerminal(result+"\n[exit "+(data.code??-1)+"]\n");
    terminalOutput.textContent+=(result+"\n[exit "+(data.code??-1)+"]\n");
    terminalOutput.scrollTop=terminalOutput.scrollHeight;
    await refreshFileTree(); await refreshStorage(); refreshTerminalStatus();
    pushNotification("Terminal command finished",command+" completed with exit code "+(data.code??-1)+".",data.code===0?"success":"warning");
  } catch(error) {
    appendRightTerminal("Error: "+error.message+"\n");pushNotification("Terminal command failed",error.message||"Command failed.","error");
  } finally {
    terminalBusy=false; $("right-terminal-run-btn").disabled=false;
    input.value=""; input.focus();
  }
}

async function runTerminalCommand(){
  const input=$("terminal-command"),command=input.value.trim();
  if(!command||terminalBusy||!currentProjectId)return;
  terminalBusy=true;$("terminal-run-btn").disabled=true;terminalOutput.textContent+="\n$ "+command+"\n…\n";
  try{
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/terminal",{method:"POST",body:JSON.stringify({command,timeout:60})});
    const data=await response.json();
    terminalOutput.textContent+=(data.output||"")+(data.error?data.error+"\n":"")+"\n["+("exit "+(data.code??-1))+"]\n";
    terminalOutput.scrollTop=terminalOutput.scrollHeight;
    await refreshFileTree();await refreshStorage();
    pushNotification("Terminal command finished",command+" completed with exit code "+(data.code??-1)+".",data.code===0?"success":"warning");
  }catch(error){terminalOutput.textContent+="Error: "+error.message+"\n";pushNotification("Terminal command failed",error.message||"Command failed.","error");}
  finally{terminalBusy=false;$("terminal-run-btn").disabled=false;input.value="";input.focus();}
}

async function openProfile() {
  $("account-menu").classList.add("hidden");
  await loadProfile();
  const name=displayUserName(), email=profileData?.email||currentUser?.email||"";
  $("profile-display-name").value=profileData?.display_name||name;
  $("profile-email").value=email;
  $("profile-avatar-url").value=profileData?.avatar_url||"";
  $("profile-account-id").textContent=profileData?.id||currentUser?.id||"—";
  $("profile-created-at").textContent=profileData?.created_at?new Date(profileData.created_at).toLocaleDateString():"—";
  $("profile-heading").textContent=name; $("profile-email-label").textContent=email;
  syncAvatar($("profile-avatar"),name,profileData?.avatar_url);
  $("profile-error").textContent="";
  $("profile-modal").classList.remove("hidden");
}
function closeProfile(){ $("profile-modal").classList.add("hidden"); }
async function saveProfile() {
  const button=$("save-profile-btn"); button.disabled=true; $("profile-error").textContent="";
  try {
    const response=await api("/api/profile",{method:"PATCH",body:JSON.stringify({
      display_name:$("profile-display-name").value.trim(),
      avatar_url:$("profile-avatar-url").value.trim() || null
    })});
    if(!response.ok) throw new Error(await readError(response,"Could not save profile."));
    profileData=await response.json(); currentUser={...(currentUser||{}),...profileData}; syncAccountUi();
    $("profile-heading").textContent=displayUserName(); $("profile-email-label").textContent=profileData.email||"";
    syncAvatar($("profile-avatar"),displayUserName(),profileData.avatar_url);
    closeProfile(); setStatus("Profile updated");
  } catch(error) { $("profile-error").textContent=error.message||"Could not save profile."; }
  finally { button.disabled=false; }
}
function updateSettingsDashboard() {
  const storage=$("settings-storage-summary");
  const project=$("settings-project-summary");
  if(project) project.textContent=$("current-project")?.textContent||"No project selected";
  if(storage) storage.textContent=document.querySelector(".storage-text")?.textContent||"Select a project to view usage.";
  syncAccountUi();
}

function openModelModal(){
  const list=$("model-options");list.innerHTML="";
  [...$("model-select").options].forEach(option=>{
    const b=document.createElement("button");b.type="button";b.innerHTML="<strong></strong><br><small></small>";
    b.querySelector("strong").textContent=option.textContent;
    b.querySelector("small").textContent=option.value==="gpt-5.5"?"Codex • Responses API":"Claude • Chat Completions";
    b.onclick=()=>{ $("model-select").value=option.value;updateModelPill();$("model-modal").classList.add("hidden"); };
    list.appendChild(b);
  });
  $("model-modal").classList.remove("hidden");
}
function updateModelPill(){ $("model-pill-label").textContent=$("model-select").selectedOptions[0]?.textContent||"Auto"; }
function openHelp(){ $("help-modal").classList.remove("hidden"); }
function closeModal(id){$(id)?.classList.add("hidden");}
function toggleAccount(){ $("account-menu").classList.toggle("hidden"); }
function openSettings(){
  $("setting-font-size").value=settings.fontSize;
  $("setting-explorer-width").value=settings.explorerWidth;
  $("setting-chat-width").value=settings.chatWidth;
  if($("setting-terminal-height"))$("setting-terminal-height").value=settings.terminalHeight;
  $("setting-minimap").value=settings.minimap?"on":"off";
  if($("setting-theme"))$("setting-theme").value=settings.theme;
  updateSettingsDashboard();
  settingsModal.classList.remove("hidden");
}
function applySettings(){
  settings.fontSize=Math.min(24,Math.max(10,Number($("setting-font-size").value)||13));
  settings.explorerWidth=Math.min(420,Math.max(180,Number($("setting-explorer-width").value)||230));
  settings.chatWidth=Math.min(720,Math.max(340,Number($("setting-chat-width").value)||470));
  settings.terminalHeight=Math.min(600,Math.max(160,Number($("setting-terminal-height")?.value)||275));
  settings.minimap=$("setting-minimap").value==="on";settings.theme=$("setting-theme")?.value==="light"?"light":"dark";applyTheme(settings.theme,false);persistSettings();
  if(editor)editor.updateOptions({fontSize:settings.fontSize,minimap:{enabled:settings.minimap}});
  applyPanelWidths();closeModal("settings-modal");setStatus("Settings applied");
}
function applyPanelWidths(){
  const shell=$("app-shell");
  if(shell){
    shell.style.setProperty("--explorer-width",Math.round(settings.explorerWidth)+"px");
    shell.style.setProperty("--right-width",Math.round(settings.chatWidth)+"px");
    shell.classList.toggle("explorer-collapsed", settings.explorerOpen === false);
    const collapse = $("explorer-collapse-btn");
    if(collapse){
      collapse.setAttribute("aria-expanded",String(settings.explorerOpen !== false));
      collapse.title = settings.explorerOpen === false ? "Open Explorer" : "Close Explorer";
      collapse.textContent = settings.explorerOpen === false ? "»" : "«";
    }
    const rail = $("rail-projects");
    if(rail){
      rail.setAttribute("aria-expanded",String(settings.explorerOpen !== false));
      rail.title = settings.explorerOpen === false ? "Open Explorer" : "Close Explorer";
    }
  }
  const terminal=$("right-terminal-mini");
  const toggle=$("right-terminal-toggle");
  if(terminal){
    terminal.style.height=Math.round(settings.terminalHeight)+"px";
    terminal.classList.toggle("is-open",Boolean(settings.terminalOpen));
  }
  if(toggle){
    toggle.classList.toggle("is-open",Boolean(settings.terminalOpen));
    toggle.setAttribute("aria-expanded",String(Boolean(settings.terminalOpen)));
  }
}
function toggleExplorer(force) {
  settings.explorerOpen = typeof force === "boolean" ? force : settings.explorerOpen === false;
  persistSettings();
  applyPanelWidths();
  if(editorReady && editor) setTimeout(() => editor.layout(), 30);
}
function clamp(value,min,max){return Math.min(max,Math.max(min,value));}
function startResize(type,event){
  if(event.button!==0)return;
  event.preventDefault();
  const handle=event.currentTarget;
  try{handle?.setPointerCapture?.(event.pointerId);}catch{}
  resizeDrag={
    type,
    startX:event.clientX,
    startY:event.clientY,
    explorerWidth:settings.explorerWidth,
    chatWidth:settings.chatWidth,
    terminalHeight:settings.terminalHeight,
  };
  document.body.classList.add("is-resizing");
  document.body.style.userSelect="none";
  const move=(e)=>{
    if(!resizeDrag)return;
    if(type==="explorer"){
      settings.explorerWidth=clamp(resizeDrag.explorerWidth+(e.clientX-resizeDrag.startX),190,420);
    }else if(type==="right"){
      settings.chatWidth=clamp(resizeDrag.chatWidth-(e.clientX-resizeDrag.startX),320,720);
    }else if(type==="terminal"){
      settings.terminalHeight=clamp(resizeDrag.terminalHeight-(e.clientY-resizeDrag.startY),160,600);
    }
    applyPanelWidths();
  };
  const stop=()=>{
    if(!resizeDrag)return;
    resizeDrag=null;
    document.body.classList.remove("is-resizing");
    document.body.style.userSelect="";
    persistSettings();
    window.removeEventListener("pointermove",move);
    window.removeEventListener("pointerup",stop);
    window.removeEventListener("pointercancel",stop);
    try{handle?.releasePointerCapture?.(event.pointerId);}catch{}
  };
  window.addEventListener("pointermove",move);
  window.addEventListener("pointerup",stop,{once:true});
  window.addEventListener("pointercancel",stop,{once:true});
}
function resetSettings(){settings={...defaultSettings};persistSettings();openSettings();applySettings();}

function initEditor(){
  if(editorReady || editor) return;
  const loader = window.require;
  if(typeof loader!=="function"){
    appendSysMsg("Editor loader is unavailable. Retrying…");
    setTimeout(initEditor,1200);
    return;
  }
  loader.config({paths:{vs:"https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs"}});
  loader(["vs/editor/editor.main"],()=>{
    const host=$("right-editor-container");host.innerHTML="";
    monaco.editor.defineTheme("codeforge-dark",{base:"vs-dark",inherit:true,rules:[],colors:{"editor.background":"#0f1115","editor.foreground":"#e7eaf0","editorLineNumber.foreground":"#596171","editorLineNumber.activeForeground":"#aab2c0","editorCursor.foreground":"#a89cf7","editor.selectionBackground":"#30344a","editor.lineHighlightBackground":"#171a21","editorIndentGuide.background1":"#252a33","editorIndentGuide.activeBackground1":"#353c49","editorWidget.background":"#171a21","editorWidget.border":"#303642","input.background":"#151820","input.border":"#343b49"}});monaco.editor.defineTheme("codeforge-light",{base:"vs",inherit:true,rules:[],colors:{"editor.background":"#fbfcfe","editor.foreground":"#20242c","editorLineNumber.foreground":"#9aa2b1","editorLineNumber.activeForeground":"#4f5664","editorCursor.foreground":"#5b55c9","editor.selectionBackground":"#dfe2f5","editor.lineHighlightBackground":"#f3f4f7","editorIndentGuide.background1":"#e2e5ea","editorIndentGuide.activeBackground1":"#cbd0d8","editorWidget.background":"#ffffff","editorWidget.border":"#d9dde5","input.background":"#ffffff","input.border":"#cfd4dd"}});editor=monaco.editor.create(host,{value:"",language:"plaintext",theme:settings.theme==="light"?"codeforge-light":"codeforge-dark",automaticLayout:true,minimap:{enabled:settings.minimap},fontSize:settings.fontSize,lineHeight:21,padding:{top:12},smoothScrolling:true,scrollBeyondLastLine:false});
    editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.KeyS,saveCurrentFile);
    editor.onDidChangeModelContent(()=>{
      if(!activeTab)return;const tab=tabs.get(activeTab);if(!tab)return;
      tab.dirty=tab.model.getValue()!==tab.savedContent;updateDirtyDots();updateRightPreview();
      if(tab.dirty) scheduleAutoSave(activeTab);
    });
    editorReady=true;
    if(activeTab)activateTab(activeTab);
  },()=>{ appendSysMsg("Could not load Monaco editor. Check network access and reload the workspace."); setTimeout(initEditor,2000); });
}

function attachLocalFile(){
  const input=document.createElement("input");input.type="file";
  input.onchange=async()=>{
    const file=input.files?.[0];if(!file)return;
    if(file.size>250000) {appendSysMsg("Attached files are limited to 250 KB.");return;}
    attachedContext="--- "+file.name+" ---\n"+await file.text()+"\n--- end "+file.name+" ---";
    chatInput.value+=" [Attached: "+file.name+"]";chatInput.focus();setStatus("File attached");
  };
  input.click();
}
async function openChangeReview(changeSetId){
  if(!changeSetId||!currentProjectId)return;
  try{
    const response=await api("/api/changes/"+encodeURIComponent(currentProjectId)+"/"+encodeURIComponent(changeSetId),{cache:"no-store"});
    if(!response.ok)throw new Error(await readError(response,"Could not load AI changes."));
    renderChangeReview(await response.json());$("change-review-modal")?.classList.remove("hidden");
  }catch(error){pushNotification("Change review unavailable",error.message||"Could not load AI changes.","warning");}
}
function renderChangeReview(data){
  const files=Array.isArray(data.files)?data.files:[]; const summary=$("change-review-summary");
  if(summary)summary.textContent=(data.status||"pending_review").replaceAll("_"," ")+" · "+files.length+" changed file"+(files.length===1?"":"s");
  const host=$("change-review-files"); if(!host)return; host.innerHTML="";
  files.forEach(item=>{
    const card=document.createElement("article"); card.className="change-review-file";
    const head=document.createElement("div"); head.className="change-review-file-head";
    const title=document.createElement("strong"); title.textContent=item.path;
    const state=document.createElement("small"); state.textContent=item.status||"pending";
    const actions=document.createElement("div"); actions.className="change-review-file-actions";
    const keep=document.createElement("button"); keep.type="button"; keep.textContent="Keep"; keep.onclick=()=>resolveChangeFile(item.path,"accept");
    const reject=document.createElement("button"); reject.type="button"; reject.textContent="Reject"; reject.onclick=()=>resolveChangeFile(item.path,"reject");
    actions.append(keep,reject); head.append(title,state,actions);
    const body=document.createElement("div"); body.className="change-review-file-body";
    const before=document.createElement("pre"); before.textContent=item.before||"(file did not exist)";
    const after=document.createElement("pre"); after.className="after"; after.textContent=item.after||"(empty)";
    body.append(before,after); card.append(head,body); host.appendChild(card);
  });
}
async function resolveChangeFile(path,action){
  if(!lastChangeSetId)return;
  try{
    const url="/api/changes/"+encodeURIComponent(currentProjectId)+"/"+encodeURIComponent(lastChangeSetId)+"/files/"+path.split("/").map(encodeURIComponent).join("/")+"/"+action;
    const response=await api(url,{method:"POST"}); if(!response.ok)throw new Error(await readError(response,"Could not update this file."));
    renderChangeReview(await response.json()); await refreshFileTree(); await refreshStorage();
    for(const p of tabs.keys())await reloadTab(p);
  }catch(error){pushNotification("Change review failed",error.message||"Could not update this file.","error");}
}
async function resolveAllChanges(action){
  if(!lastChangeSetId)return;
  try{
    const response=await api("/api/changes/"+encodeURIComponent(currentProjectId)+"/"+encodeURIComponent(lastChangeSetId)+"/action",{method:"POST",body:JSON.stringify({action})});
    if(!response.ok)throw new Error(await readError(response,"Could not update AI changes."));
    renderChangeReview(await response.json()); await refreshFileTree(); await refreshStorage();
    for(const p of tabs.keys())await reloadTab(p); if(action==="reject")setStatus("AI changes rejected");
  }catch(error){pushNotification("Change review failed",error.message||"Could not update AI changes.","error");}
}
async function undoLastAiChanges(){
  if(!lastCheckpointId||!currentProjectId)return;
  const button=$("undo-ai-btn"); if(button)button.disabled=true;
  try{
    const response=await api("/api/context/"+encodeURIComponent(currentProjectId)+"/checkpoint",{method:"POST",body:JSON.stringify({action:"restore",checkpoint_id:lastCheckpointId})});
    if(!response.ok)throw new Error(await readError(response,"Could not restore the checkpoint."));
    lastCheckpointId="";button?.classList.add("hidden");
    await refreshFileTree();await refreshStorage();
    for(const path of tabs.keys())await reloadTab(path);
    pushNotification("AI changes undone","The workspace was restored to the checkpoint created before the last AI task.","success");
    setStatus("Workspace restored");
  }catch(error){pushNotification("Restore failed",error.message||"Could not restore checkpoint.","error");}
  finally{if(button)button.disabled=false;}
}
function mentionWorkspace(){chatInput.value="@workspace "+chatInput.value;chatInput.focus();}
function notify(){
  const message=currentProjectId?"Workspace "+($("current-project").textContent||"")+" is active.":"Select a project to begin.";
  appendSysMsg(message);
}
function profile(){openProfile();}

function init(){
  $("landing-login-btn").onclick=openLoginDialog;
  $("landing-hero-login").onclick=openLoginDialog;
  $("landing-access-login").onclick=openLoginDialog;
  $("landing-contact-btn").onclick=openContactDialog;
  $("landing-hero-contact").onclick=openContactDialog;
  $("landing-access-contact").onclick=openContactDialog;
  $("dialog-contact-btn").onclick=()=>{closeLoginDialog();openContactDialog();};
  $("contact-back-login").onclick=()=>{closeContactDialog();openLoginDialog();};
  $("login-dialog-close").onclick=closeLoginDialog;
  $("contact-dialog-close").onclick=closeContactDialog;
  document.querySelectorAll(".landing-dialog-backdrop").forEach(el=>el.onclick=e=>{if(e.target===el)el.classList.add("hidden");});
  $("login-btn").onclick=login;
  $("email-input").onkeydown=e=>{if(e.key==="Enter")login();};
  $("password-input").onkeydown=e=>{if(e.key==="Enter")login();};

  $("file-tree").addEventListener("contextmenu", e => {
    const row=e.target.closest(".file-item,.folder-row");
    if(row){
      showExplorerContextMenu(e,row.dataset.path,row.classList.contains("folder-row"));
    } else {
      showExplorerContextMenu(e,"",false);
    }
  });
  $("explorer-context-menu").querySelectorAll("[data-context-action]").forEach(item=>{
    item.onclick=()=>handleExplorerContextAction(item.dataset.contextAction);
  });
  document.addEventListener("click",e=>{
    if(!e.target.closest("#explorer-context-menu")) closeExplorerContextMenu();
  });
  document.addEventListener("scroll",closeExplorerContextMenu,true);
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape") closeExplorerContextMenu();
  });

  $("new-project-hero").onclick=openProjectModal;
  $("new-folder-btn").onclick=openFolderCreate;
  $("explorer-collapse-btn").onclick=()=>toggleExplorer(false);
  $("new-file-sidebar-btn").onclick=openFileCreate;
  $("project-popout-btn").onclick=openProjectModal;
  $("project-switcher").onclick=()=>loadProjects(true);
  $("close-projects-btn").onclick=closeProjectModal;
  $("create-project-btn").onclick=createProject;
  $("new-project-name").onkeydown=e=>{if(e.key==="Enter")createProject();};
  projectModal.onclick=e=>{if(e.target===projectModal)closeProjectModal();};

  $("rail-projects").onclick=()=>{setRail("rail-projects");toggleExplorer();};
  $("rail-chat").onclick=()=>{setRail("rail-chat");showChat();};
  $("rail-terminal").onclick=()=>{setRail("rail-terminal");toggleRightTerminal();};
  $("rail-settings").onclick=()=>{setRail("rail-settings");openSettings();};
  $("promo-card").onclick=()=>{setRail("rail-chat");showChat();};

  $("theme-toggle").onclick=toggleTheme;
  $("setting-theme").onchange=e=>applyTheme(e.target.value);
  $("settings-btn").onclick=openSettings;
  $("close-settings-btn").onclick=()=>closeModal("settings-modal");
  $("save-settings-btn").onclick=applySettings;
  $("reset-settings-btn").onclick=resetSettings;
  settingsModal.onclick=e=>{if(e.target===settingsModal)closeModal("settings-modal");};

  $("model-menu-btn").onclick=openModelModal;
  $("close-model-btn").onclick=()=>closeModal("model-modal");
  $("model-select").onchange=updateModelPill;
  $("agent-mode-select").onchange=()=>{pendingActionMode=$("agent-mode-select").value;};
  $("inline-ai-close").onclick=()=>{$("inline-ai-modal").classList.add("hidden");inlineEditState=null;};
  $("inline-ai-cancel").onclick=()=>{$("inline-ai-modal").classList.add("hidden");inlineEditState=null;};
  $("inline-ai-run").onclick=runInlineAi;
  $("help-btn").onclick=openHelp;
  $("close-help-btn").onclick=()=>closeModal("help-modal");
  $("notifications-btn").onclick=e=>{e.stopPropagation();openNotifications();};
  $("notifications-close-btn").onclick=()=>$("notifications-panel").classList.add("hidden");
  $("notifications-mark-read-btn").onclick=markNotificationsRead;
  $("notifications-clear-btn").onclick=clearNotifications;
  $("notifications-panel").onclick=e=>e.stopPropagation();
  document.addEventListener("click",e=>{
    const panel=$("notifications-panel");
    if(panel && !panel.classList.contains("hidden") && !e.target.closest("#notifications-panel") && !e.target.closest("#notifications-btn")) panel.classList.add("hidden");
  });
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape")$("notifications-panel")?.classList.add("hidden");
  });
  $("account-btn").onclick=toggleAccount;
  $("account-projects-btn").onclick=()=>{toggleAccount();openProjectModal();};
  $("account-logout-btn").onclick=()=>{toggleAccount();logout(true);};
  $("profile-btn").onclick=profile;
  $("account-settings-btn").onclick=()=>{toggleAccount();openSettings();};
  $("settings-profile-btn").onclick=openProfile;
  $("close-profile-btn").onclick=closeProfile;
  $("cancel-profile-btn").onclick=closeProfile;
  $("save-profile-btn").onclick=saveProfile;
  $("profile-modal").onclick=e=>{if(e.target===$("profile-modal"))closeProfile();};

  $("global-search-input").onkeydown=e=>{
    if(e.key==="Enter"){const value=e.currentTarget.value.trim();if(value){chatInput.value=value;sendChatMessage();e.currentTarget.value="";}}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();e.currentTarget.focus();}
  };
  $("file-search").oninput=e=>filterFiles(e.target.value);
  $("create-file-btn").onclick=openFileCreate;
  $("right-more-tab").onclick=()=>activeTab?deleteActiveFile():openFileCreate();
  $("download-all-btn").onclick=downloadAllFiles;
  $("right-terminal-toggle").onclick=()=>toggleRightTerminal();
  $("right-terminal-tab-btn").onclick=()=>setRightTerminalTab("terminal");
  $("right-agent-tab").onclick=()=>setRightTerminalTab("agent");
  $("right-terminal-run-btn").onclick=runRightTerminalCommand;
  $("right-terminal-toggle").addEventListener("dblclick",refreshTerminalStatus);
  $("right-terminal-command").onkeydown=e=>{if(e.key==="Enter")runRightTerminalCommand();};
  $("right-terminal-clear-btn").onclick=clearRightTerminal;
  $("close-file-create-btn").onclick=closeFileCreate;
  $("cancel-file-create-btn").onclick=closeFileCreate;
  $("close-rename-item-btn")?.addEventListener("click",closeRenameItem);
  $("cancel-rename-item-btn")?.addEventListener("click",closeRenameItem);
  $("confirm-rename-item-btn")?.addEventListener("click",submitRenameItem);
  $("rename-item-modal")?.addEventListener("click",e=>{if(e.target===e.currentTarget)closeRenameItem();});
  $("rename-item-name")?.addEventListener("keydown",e=>{if(e.key==="Enter")submitRenameItem();});
  $("confirm-file-create-btn").onclick=createFile;
  fileCreateModal.onclick=e=>{if(e.target===fileCreateModal)closeFileCreate();};
  $("new-file-path").onkeydown=e=>{if(e.key==="Enter")createFile();};
  $("new-file-path").addEventListener("input",e=>{ if(e.target.value.endsWith("/") && e.target.value.split("/").length>1) e.target.value=e.target.value; });
  $("new-folder-path").onkeydown=e=>{if(e.key==="Enter")createFolder();};
  $("close-folder-create-btn").onclick=closeFolderCreate;
  $("cancel-folder-create-btn").onclick=closeFolderCreate;
  $("confirm-folder-create-btn").onclick=createFolder;
  $("folder-create-modal").onclick=e=>{if(e.target===$("folder-create-modal"))closeFolderCreate();};
  bindTreeRootDropTarget();
  $("resize-explorer").onpointerdown=e=>startResize("explorer",e);
  $("resize-right").onpointerdown=e=>startResize("right",e);
  $("resize-terminal").onpointerdown=e=>startResize("terminal",e);

  $("undo-ai-btn").onclick=undoLastAiChanges;
  $("close-change-review-btn").onclick=()=>$("change-review-modal")?.classList.add("hidden");
  $("accept-all-changes-btn").onclick=()=>resolveAllChanges("accept");
  $("reject-all-changes-btn").onclick=()=>resolveAllChanges("reject");
  $("autopilot-toggle").onchange=()=>{if($("autopilot-toggle").checked){$("agent-mode-select").value="build";pendingActionMode="build";}};
  $("attach-btn").onclick=attachLocalFile;
  $("mention-btn").onclick=mentionWorkspace;
  $("send-chat-btn").onclick=sendChatMessage;
  chatInput.oninput=()=>setChatEnabled(true);
  chatInput.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendChatMessage();}};

  $("terminal-run-btn").onclick=runTerminalCommand;
  $("terminal-command").onkeydown=e=>{if(e.key==="Enter")runTerminalCommand();};
  $("terminal-clear-btn").onclick=()=>{terminalOutput.textContent="";agentOutput.innerHTML="";};
  $("terminal-expand-btn").onclick=()=>toggleRightTerminal(false);
  document.querySelectorAll(".terminal-tab").forEach(tab=>tab.onclick=()=>{
    document.querySelectorAll(".terminal-tab").forEach(x=>x.classList.remove("active"));tab.classList.add("active");
    const agent=tab.dataset.terminalTab==="agent";terminalOutput.classList.toggle("hidden-output",agent);agentOutput.classList.toggle("hidden-output",!agent);
  });

  document.querySelectorAll(".modal-backdrop").forEach(m=>m.addEventListener("keydown",e=>{if(e.key==="Escape")m.classList.add("hidden");}));
  document.addEventListener("keydown",e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){
      e.preventDefault();
      if(editorReady && document.activeElement?.closest("#right-editor-container")) openInlineAi();
      else $("global-search-input").focus();
    }
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="p"){e.preventDefault();$("file-search").focus();}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();saveCurrentFile();}
    if(e.key==="`"){e.preventDefault();toggleRightTerminal();}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="n"){e.preventDefault();openFileCreate();}
    if(e.key==="Escape"){document.querySelectorAll(".modal-backdrop").forEach(m=>m.classList.add("hidden"));$("account-menu").classList.add("hidden");}
  });

  bindPromptButtons();
  applyTheme(settings.theme, false);
  renderNotifications();
  updateModelPill();
  setRightTerminalTab("terminal");
  applyPanelWidths();
  initEditor();
  restoreSession();
  setInterval(()=>{updateGreeting();if(token&&currentProjectId){refreshStorage();refreshTerminalStatus();}},30000);
}
window.addEventListener("beforeunload",e=>{
  const dirty=[...tabs.values()].some(t=>t.dirty);
  if(dirty){e.preventDefault();e.returnValue="";}
});
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();