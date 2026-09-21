(() => {
"use strict";

let token = localStorage.getItem("codeforge_token") || "";
let currentProjectId = localStorage.getItem("codeforge_project_id") || "";
let projects = [];
let currentUser = null;
let editor = null;
let editorReady = false;
let tabs = new Map();
let activeTab = "";
let agentRunning = false;
let activeAiMessage = null;
let streamHadError = false;
let terminalBusy = false;
let attachedContext = "";
let profileData = null;

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

const defaultSettings = { fontSize: 13, explorerWidth: 230, chatWidth: 470, minimap: true };
let settings = loadSettings();

function loadSettings() {
  try { return { ...defaultSettings, ...JSON.parse(localStorage.getItem("codeforge_settings") || "{}") }; }
  catch { return { ...defaultSettings }; }
}
function persistSettings() { localStorage.setItem("codeforge_settings", JSON.stringify(settings)); }

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
  $("auth-overlay").style.display = authenticated ? "none" : "flex";
  if (!authenticated) {
    setChatEnabled(false);
    $("current-project").textContent = "No Project Selected";
    return;
  }
  updateGreeting();
}

function setChatEnabled(enabled) {
  const canChat = Boolean(enabled && token && currentProjectId);
  chatInput.disabled = !canChat || agentRunning;
  sendBtn.disabled = !canChat || agentRunning || !chatInput.value.trim();
  chatInput.placeholder = canChat ? "Describe what you want to build, modify, debug, or learn..." : "Select a project to start chatting...";
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
function appendMsg(text, sender) {
  const d = document.createElement("div");
  d.className = "chat-msg msg-" + sender;
  d.textContent = text || "";
  chatHistory.appendChild(d);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return d;
}
function appendSysMsg(text) { return appendMsg(text, "sys"); }

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
  if (!token) return;
  try {
    const response = await api("/api/auth/me", { cache: "no-store" });
    if (response.ok) currentUser = await response.json();
  } catch {}
  await loadProfile();
  updateGreeting();
  syncAccountUi();
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
  const parts = String(name).trim().split(/\\s+/).filter(Boolean);
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
  updateSettingsDashboard();
  showHome();
}
function clearChat() {
  chatHistory.innerHTML = "";
  activeAiMessage = null;
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

function buildFileTree(paths) {
  const root = {};
  for (const path of paths) {
    let node = root;
    const parts = path.split("/").filter(Boolean);
    parts.forEach((part, i) => {
      node[part] ||= { __children:{}, __file:i === parts.length - 1 };
      node = node[part].__children;
    });
  }
  fileTree.innerHTML = "";
  if (!paths.length) {
    fileTree.innerHTML = '<div class="empty-tree">No files yet. Use + to create one.</div>';
    return;
  }
  const render = (node, parent, prefix = "") => {
    Object.keys(node).sort((a,b) => {
      const af=node[a].__file,bf=node[b].__file;
      return af===bf ? a.localeCompare(b) : af ? 1 : -1;
    }).forEach(name => {
      const item=node[name];
      const full=prefix ? prefix+"/"+name : name;
      if (item.__file) {
        const row=document.createElement("button");
        row.type="button"; row.className="file-item"; row.dataset.path=full;
        row.innerHTML='<span class="file-symbol">▱</span><span class="file-name"></span><span class="dirty-dot"></span><span class="file-download" title="Download file">⇩</span>';
        row.querySelector(".file-name").textContent=name;
        row.onclick=()=>openFile(full); row.querySelector(".file-download").onclick=e=>{e.preventDefault();e.stopPropagation();downloadFile(full);};
        parent.appendChild(row);
      } else {
        const wrap=document.createElement("div"); wrap.className="folder-wrap";
        const head=document.createElement("button"); head.type="button"; head.className="folder-row";
        head.innerHTML='<span class="folder-chevron">▾</span><span class="folder-name"></span>';
        head.querySelector(".folder-name").textContent=name;
        const children=document.createElement("div"); children.className="folder-children";
        head.onclick=()=>{ children.classList.toggle("collapsed"); head.querySelector(".folder-chevron").textContent=children.classList.contains("collapsed")?"▸":"▾"; };
        wrap.append(head,children); parent.appendChild(wrap); render(item.__children,children,full);
      }
    });
  };
  render(root,fileTree);
  updateDirtyDots();
}
async function refreshFileTree() {
  if (!currentProjectId) return;
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/tree",{cache:"no-store"});
    if(!response.ok) throw new Error(await readError(response,"Could not load workspace files."));
    const data=await response.json();
    buildFileTree(Array.isArray(data.files)?data.files:[]);
    setStatus("Workspace ready");
  } catch(error) {
    setStatus("Workspace unavailable",false);
    appendSysMsg(error.message||"Could not load workspace files.");
  }
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
function closeTab(path) {
  const tab=tabs.get(path); if(!tab)return;
  if(tab.dirty&&!confirm("Discard unsaved changes in "+path+"?"))return;
  tab.model.dispose(); tabs.delete(path);
  if(activeTab===path){
    const next=[...tabs.keys()].pop()||"";
    activeTab=""; if(next)activateTab(next); else if(editor)editor.setModel(null);
  }
  renderEditorTabs(); updateRightPreview();
}
async function saveCurrentFile() {
  const tab=tabs.get(activeTab); if(!tab||!currentProjectId)return;
  const content=tab.model.getValue(); setStatus("Saving "+tab.path+"…");
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file",{method:"PUT",body:JSON.stringify({path:tab.path,content})});
    if(!response.ok)throw new Error(await readError(response,"Could not save file."));
    tab.savedContent=content;tab.dirty=false;updateDirtyDots();updateRightPreview();setStatus("Saved "+tab.path);
  }catch(error){setStatus("Save failed",false);appendSysMsg(error.message||"Could not save file.");}
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
    closeFileCreate();await refreshFileTree();await openFile(path);setStatus("Created "+path);
  }catch(error){$("file-create-error").textContent=error.message||"Could not create file.";}
  finally{button.disabled=false;}
}
async function deleteActiveFile() {
  if(!activeTab||!currentProjectId)return;
  const path=activeTab;
  if(!confirm("Delete "+path+" permanently?"))return;
  const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/file?path="+encodeURIComponent(path),{method:"DELETE"});
  if(!response.ok){appendSysMsg(await readError(response,"Could not delete file."));return;}
  closeTab(path);await refreshFileTree();setStatus("Deleted "+path);
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
  setStatus("Downloaded "+path);
}
async function downloadAllFiles() {
  if(!currentProjectId){appendSysMsg("Select a project before downloading.");return;}
  await downloadBlob("/api/workspace/"+encodeURIComponent(currentProjectId)+"/download-all","codeforge-project.zip");
  setStatus("Downloaded project ZIP");
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
function showTerminal() {
  $("home-view").classList.add("hidden");
  $("chat-view").classList.add("hidden");
  $("terminal-panel").classList.remove("hidden");
  $("terminal-command").focus();
}
function setRail(activeId){
  document.querySelectorAll(".rail-item").forEach(x=>x.classList.toggle("active",x.id===activeId));
}
function bindPromptButtons(){
  document.querySelectorAll(".action-card,.example-prompt,.help-grid [data-prompt]").forEach(button=>{
    button.onclick=()=>{
      if(!currentProjectId){openProjectModal();return;}
      chatInput.value=button.dataset.prompt||"";
      showChat();setChatEnabled(true);sendChatMessage();
    };
  });
}

async function sendChatMessage() {
  const message=chatInput.value.trim();
  if(!message||!currentProjectId||agentRunning)return;
  showChat();
  chatInput.value="";
  activeAiMessage=null;
  appendMsg(message,"user");
  agentRunning=true;streamHadError=false;
  setChatEnabled(true);setStatus("Agent working…");
  agentOutput.innerHTML="";
  let contextual="[CodeForge context: model="+$("model-select").value+"]\n\n"+message;
  if(attachedContext){contextual+="\n\nAttached file context:\n"+attachedContext;attachedContext="";}
  try{
    const response=await api("/api/agent/"+encodeURIComponent(currentProjectId)+"/chat",{method:"POST",body:JSON.stringify({message:contextual,mode:"build",model:$("model-select").value})});
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
    agentRunning=false;activeAiMessage=null;setChatEnabled(true);
    if(!streamHadError)setStatus("Workspace ready");
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
    if(!activeAiMessage){activeAiMessage=appendMsg("","ai");}
    activeAiMessage.textContent+=(data.content||"");chatHistory.scrollTop=chatHistory.scrollHeight;return;
  }
  if(data.type==="message"){
    if(activeAiMessage){if(data.content&&!activeAiMessage.textContent)activeAiMessage.textContent=data.content;activeAiMessage=null;}
    else appendMsg(data.content||"","ai");
    return;
  }
  if(data.type==="tool_call"){
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
    addTimeline("file","File changed",data.path||"","done");
    addRightAgentTimeline("file","File changed",data.path||"","done");
    await refreshFileTree();await refreshStorage();
    if(data.path&&tabs.has(data.path))await reloadTab(data.path);
    return;
  }
  if(data.type==="done"){addTimeline("success","Agent finished","Workspace synchronized","done");addRightAgentTimeline("success","Agent finished","Workspace synchronized","done");return;}
  if(data.type==="error"){streamHadError=true;setStatus("Agent failed",false);addTimeline("error","Agent error",data.message||"Unknown error","error");addRightAgentTimeline("error","Agent error",data.message||"Unknown error","error");appendSysMsg(data.message||"Agent error");}
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
  if(!command || terminalBusy || !currentProjectId) return;
  terminalBusy=true; $("right-terminal-run-btn").disabled=true;
  appendRightTerminal("\n$ "+command+"\n…\n");
  try {
    const response=await api("/api/workspace/"+encodeURIComponent(currentProjectId)+"/terminal",{method:"POST",body:JSON.stringify({command,timeout:60})});
    if(!response.ok) throw new Error(await readError(response,"Terminal command failed."));
    const data=await response.json();
    const result=(data.output||"")+(data.error?data.error+"\n":"");
    appendRightTerminal(result+"\n[exit "+(data.code??-1)+"]\n");
    terminalOutput.textContent+=(result+"\n[exit "+(data.code??-1)+"]\n");
    terminalOutput.scrollTop=terminalOutput.scrollHeight;
    await refreshFileTree(); await refreshStorage();
  } catch(error) {
    appendRightTerminal("Error: "+error.message+"\n");
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
  }catch(error){terminalOutput.textContent+="Error: "+error.message+"\n";}
  finally{terminalBusy=false;$("terminal-run-btn").disabled=false;input.value="";input.focus();}
}

async function openProfile() {
  toggleAccount();
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
  $("setting-minimap").value=settings.minimap?"on":"off";
  updateSettingsDashboard();
  settingsModal.classList.remove("hidden");
}
function applySettings(){
  settings.fontSize=Math.min(24,Math.max(10,Number($("setting-font-size").value)||13));
  settings.explorerWidth=Math.min(420,Math.max(180,Number($("setting-explorer-width").value)||230));
  settings.chatWidth=Math.min(600,Math.max(300,Number($("setting-chat-width").value)||470));
  settings.minimap=$("setting-minimap").value==="on";persistSettings();
  if(editor)editor.updateOptions({fontSize:settings.fontSize,minimap:{enabled:settings.minimap}});
  applyPanelWidths();closeModal("settings-modal");setStatus("Settings applied");
}
function applyPanelWidths(){
  const shell=$("app-shell");
  if(shell)shell.style.gridTemplateColumns="72px "+settings.explorerWidth+"px minmax(0,1fr) "+settings.chatWidth+"px";
}
function resetSettings(){settings={...defaultSettings};persistSettings();openSettings();applySettings();}

function initEditor(){
  if(typeof require!=="function"){appendSysMsg("Monaco editor loader did not initialize.");return;}
  require.config({paths:{vs:"https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs"}});
  require(["vs/editor/editor.main"],()=>{
    const host=$("right-editor-container");host.innerHTML="";
    editor=monaco.editor.create(host,{value:"",language:"plaintext",theme:"vs-dark",automaticLayout:true,minimap:{enabled:settings.minimap},fontSize:settings.fontSize,lineHeight:21,padding:{top:12},smoothScrolling:true,scrollBeyondLastLine:false});
    editor.addCommand(monaco.KeyMod.CtrlCmd|monaco.KeyCode.KeyS,saveCurrentFile);
    editor.onDidChangeModelContent(()=>{
      if(!activeTab)return;const tab=tabs.get(activeTab);if(!tab)return;
      tab.dirty=tab.model.getValue()!==tab.savedContent;updateDirtyDots();updateRightPreview();
    });
    editorReady=true;
    if(activeTab)activateTab(activeTab);
  },()=>appendSysMsg("Could not load Monaco editor."));
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
function mentionWorkspace(){chatInput.value="@workspace "+chatInput.value;chatInput.focus();}
function notify(){
  const message=currentProjectId?"Workspace "+($("current-project").textContent||"")+" is active.":"Select a project to begin.";
  appendSysMsg(message);
}
function profile(){openProfile();}

function init(){
  $("login-btn").onclick=login;
  $("email-input").onkeydown=e=>{if(e.key==="Enter")login();};
  $("password-input").onkeydown=e=>{if(e.key==="Enter")login();};

  $("new-project-hero").onclick=openProjectModal;
  $("project-popout-btn").onclick=openProjectModal;
  $("project-switcher").onclick=()=>loadProjects(true);
  $("close-projects-btn").onclick=closeProjectModal;
  $("create-project-btn").onclick=createProject;
  $("new-project-name").onkeydown=e=>{if(e.key==="Enter")createProject();};
  projectModal.onclick=e=>{if(e.target===projectModal)closeProjectModal();};

  $("rail-projects").onclick=()=>{setRail("rail-projects");showHome();};
  $("rail-chat").onclick=()=>{setRail("rail-chat");showChat();};
  $("rail-terminal").onclick=()=>{setRail("rail-terminal");showTerminal();};
  $("rail-settings").onclick=()=>{setRail("rail-settings");openSettings();};
  $("promo-card").onclick=()=>{setRail("rail-chat");showChat();};

  $("settings-btn").onclick=openSettings;
  $("close-settings-btn").onclick=()=>closeModal("settings-modal");
  $("save-settings-btn").onclick=applySettings;
  $("reset-settings-btn").onclick=resetSettings;
  settingsModal.onclick=e=>{if(e.target===settingsModal)closeModal("settings-modal");};

  $("model-menu-btn").onclick=openModelModal;
  $("close-model-btn").onclick=()=>closeModal("model-modal");
  $("model-select").onchange=updateModelPill;
  $("help-btn").onclick=openHelp;
  $("close-help-btn").onclick=()=>closeModal("help-modal");
  $("notifications-btn").onclick=notify;
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
  $("right-terminal-tab-btn").onclick=()=>setRightTerminalTab("terminal");
  $("right-agent-tab").onclick=()=>setRightTerminalTab("agent");
  $("right-terminal-run-btn").onclick=runRightTerminalCommand;
  $("right-terminal-command").onkeydown=e=>{if(e.key==="Enter")runRightTerminalCommand();};
  $("right-terminal-clear-btn").onclick=clearRightTerminal;
  $("close-file-create-btn").onclick=closeFileCreate;
  $("cancel-file-create-btn").onclick=closeFileCreate;
  $("confirm-file-create-btn").onclick=createFile;
  fileCreateModal.onclick=e=>{if(e.target===fileCreateModal)closeFileCreate();};
  $("new-file-path").onkeydown=e=>{if(e.key==="Enter")createFile();};

  $("attach-btn").onclick=attachLocalFile;
  $("mention-btn").onclick=mentionWorkspace;
  $("send-chat-btn").onclick=sendChatMessage;
  chatInput.oninput=()=>setChatEnabled(true);
  chatInput.onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendChatMessage();}};

  $("terminal-run-btn").onclick=runTerminalCommand;
  $("terminal-command").onkeydown=e=>{if(e.key==="Enter")runTerminalCommand();};
  $("terminal-clear-btn").onclick=()=>{terminalOutput.textContent="";agentOutput.innerHTML="";};
  $("terminal-expand-btn").onclick=()=>showChat();
  document.querySelectorAll(".terminal-tab").forEach(tab=>tab.onclick=()=>{
    document.querySelectorAll(".terminal-tab").forEach(x=>x.classList.remove("active"));tab.classList.add("active");
    const agent=tab.dataset.terminalTab==="agent";terminalOutput.classList.toggle("hidden-output",agent);agentOutput.classList.toggle("hidden-output",!agent);
  });

  document.querySelectorAll(".modal-backdrop").forEach(m=>m.addEventListener("keydown",e=>{if(e.key==="Escape")m.classList.add("hidden");}));
  document.addEventListener("keydown",e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$("global-search-input").focus();}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="p"){e.preventDefault();$("file-search").focus();}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();saveCurrentFile();}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="n"){e.preventDefault();openFileCreate();}
    if(e.key==="Escape"){document.querySelectorAll(".modal-backdrop").forEach(m=>m.classList.add("hidden"));$("account-menu").classList.add("hidden");}
  });

  bindPromptButtons();
  updateModelPill();
  setRightTerminalTab("terminal");
  applyPanelWidths();
  initEditor();
  setAuthenticatedState(Boolean(token));
  if(token){loadMe().then(()=>loadProjects(false));}else setTimeout(()=>$("email-input").focus(),50);
  setInterval(()=>{updateGreeting();if(token&&currentProjectId)refreshStorage();},30000);
}
window.addEventListener("beforeunload",e=>{
  const dirty=[...tabs.values()].some(t=>t.dirty);
  if(dirty){e.preventDefault();e.returnValue="";}
});
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();