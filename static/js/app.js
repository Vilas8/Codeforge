// Application State
let token = "";
let currentProjectId = "";
let editor = null;

// DOM Elements
const authOverlay = document.getElementById('auth-overlay');
const loginBtn = document.getElementById('login-btn');
const fileTree = document.getElementById('file-tree');
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const sendChatBtn = document.getElementById('send-chat-btn');
const terminalOutput = document.getElementById('terminal-output');

// Init Monaco Editor
require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.38.0/min/vs' }});
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor-container'), {
        value: '// Select a file to edit\n',
        language: 'javascript',
        theme: 'vs-dark',
        automaticLayout: true
    });
    
    // Auto-save on Ctrl+S
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        saveCurrentFile();
    });
});

// Auth
loginBtn.addEventListener('click', async () => {
    const email = document.getElementById('email-input').value.trim();
    const password = document.getElementById('password-input').value.trim();
    
    if (email && password) {
        try {
            const loginRes = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            
            if (loginRes.ok) {
                const data = await loginRes.json();
                token = data.access_token;
                authOverlay.style.display = 'none';
                loadProjects();
            } else {
                const error = await loginRes.json();
                alert("Login failed: " + error.detail);
            }
        } catch (e) {
            console.error(e);
            alert("Error connecting to server.");
        }
    }
});

// Load Projects
async function loadProjects() {
    const res = await fetch('/api/projects/', { headers: { 'Authorization': `Bearer ${token}` }});
    const projects = await res.json();
    
    if (projects.length > 0) {
        currentProjectId = projects[0].id;
        document.getElementById('current-project').innerText = projects[0].name;
        refreshFileTree();
    } else {
        // Create demo project
        const createRes = await fetch('/api/projects/', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({name: "Demo Project", slug: "demo", description: ""})
        });
        const newProj = await createRes.json();
        currentProjectId = newProj.id;
        document.getElementById('current-project').innerText = newProj.name;
        refreshFileTree();
    }
}

// File Tree
document.getElementById('refresh-tree-btn').addEventListener('click', refreshFileTree);

async function refreshFileTree() {
    if(!currentProjectId) return;
    const res = await fetch(`/api/workspace/${currentProjectId}/tree`, { headers: { 'Authorization': `Bearer ${token}` }});
    const data = await res.json();
    
    fileTree.innerHTML = '';
    data.files.forEach(path => {
        const div = document.createElement('div');
        div.className = 'file-item';
        div.innerText = `📄 ${path}`;
        div.onclick = () => openFile(path);
        fileTree.appendChild(div);
    });
}

// Editor
let currentFilePath = "";
async function openFile(path) {
    currentFilePath = path;
    const res = await fetch(`/api/workspace/${currentProjectId}/file?path=${encodeURIComponent(path)}`, { 
        headers: { 'Authorization': `Bearer ${token}` }
    });
    if(res.ok) {
        const data = await res.json();
        editor.setValue(data.content);
        // Simple language detection
        const ext = path.split('.').pop();
        let lang = 'plaintext';
        if(ext === 'py') lang = 'python';
        if(ext === 'js') lang = 'javascript';
        if(ext === 'html') lang = 'html';
        if(ext === 'css') lang = 'css';
        if(ext === 'json') lang = 'json';
        monaco.editor.setModelLanguage(editor.getModel(), lang);
    }
}

async function saveCurrentFile() {
    if(!currentFilePath) return;
    const content = editor.getValue();
    await fetch(`/api/workspace/${currentProjectId}/file`, {
        method: 'PUT',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentFilePath, content: content })
    });
    appendSysMsg(`Saved ${currentFilePath}`);
}

// AI Chat
sendChatBtn.addEventListener('click', sendChatMessage);

async function sendChatMessage() {
    const msg = chatInput.value.trim();
    if(!msg || !currentProjectId) return;
    
    chatInput.value = '';
    appendMsg(msg, 'user');
    
    // Setup SSE Request
    try {
        const response = await fetch(`/api/agent/${currentProjectId}/chat`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (let line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));
                    handleAgentEvent(data);
                }
            }
        }
    } catch (e) {
        console.error(e);
        appendSysMsg("Error communicating with AI agent.");
    }
}

function handleAgentEvent(data) {
    if (data.type === 'message') {
        appendMsg(data.content, 'ai');
    } else if (data.type === 'tool_call') {
        appendSysMsg(`Agent running: ${data.tool}(${JSON.stringify(data.args)})`);
        if(data.tool === 'run_command') {
            terminalOutput.innerText += `\n$ ${data.args.command}\n...`;
        }
    } else if (data.type === 'file_change') {
        refreshFileTree();
        if(data.path === currentFilePath) {
            openFile(currentFilePath); // Reload current file
        }
    } else if (data.type === 'done') {
        appendSysMsg("Agent finished executing.");
        refreshFileTree();
    } else if (data.type === 'error') {
        appendSysMsg(`Error: ${data.message}`);
    }
}

function appendMsg(text, sender) {
    const div = document.createElement('div');
    div.className = `chat-msg msg-${sender}`;
    div.innerText = text;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendSysMsg(text) {
    appendMsg(text, 'sys');
}
