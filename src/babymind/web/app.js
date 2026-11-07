const $ = (selector) => document.querySelector(selector);
const state = { conversationId: null, busy: false, conversations: [] };

const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
}[char]));

function markdown(value) {
  let safe = escapeHTML(value);
  safe = safe.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (_, _lang, code) => `<pre><code>${code.trim()}</code></pre>`);
  safe = safe.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  safe = safe.replace(/^### (.+)$/gm, "<h3>$1</h3>").replace(/^## (.+)$/gm, "<h2>$1</h2>").replace(/^# (.+)$/gm, "<h1>$1</h1>");
  safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>");
  safe = safe.replace(/^\s*[-*] (.+)$/gm, "<li>$1</li>");
  safe = safe.replace(/(?:<li>.*<\/li>\n?)+/g, (list) => `<ul>${list}</ul>`);
  return safe.split(/\n{2,}/).map((part) => part.startsWith("<pre>") || part.startsWith("<h") || part.startsWith("<ul>") ? part : `<p>${part.replace(/\n/g,"<br>")}</p>`).join("");
}

function toast(message) {
  const el=$("#toast");
  if(!el)return;
  el.textContent=message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer=setTimeout(()=>el.classList.remove("show"),2400);
}

async function api(path, options={}) {
  const token=localStorage.getItem("babymind_access_token")||"";
  const response=await fetch(path,{
    ...options,
    headers:{"Content-Type":"application/json",...(token?{"X-BabyMind-Token":token}:{}),...(options.headers||{})}
  });
  const data=await response.json().catch(()=>({error:"Unexpected server response"}));
  if(response.status===401){
    const entered=prompt("Enter the one-time BabyMind access token shown in the terminal:");
    if(!entered)throw new Error("Access token is required.");
    localStorage.setItem("babymind_access_token",entered.trim());
    return api(path,options);
  }
  if(!response.ok)throw new Error(data.error||`Request failed (${response.status})`);
  return data;
}

function setView(name) {
  document.querySelectorAll(".view").forEach(view=>view.classList.toggle("active",view.id===name+"View"));
  document.querySelectorAll(".tab").forEach(tab=>tab.classList.toggle("active",tab.dataset.view===name));
  if(name==="self" && window.babymindLoadSelf)window.babymindLoadSelf();
  if(name==="chat")$("#messageInput").focus();
}

function addMessage(role, content) {
  $("#welcome")?.remove();
  const item=document.createElement("article");
  item.className="message "+role;
  item.innerHTML=`<div class="message-avatar">${role==="user"?"Y":"B"}</div><div class="message-body"><div class="message-meta">${role==="user"?"You":"BabyMind"}</div><div class="message-content">${role==="user"?`<p>${escapeHTML(content).replace(/\n/g,"<br>")}</p>`:markdown(content)}</div></div>`;
  $("#messages").append(item);
  $("#messages").scrollTop=$("#messages").scrollHeight;
  return item;
}

function showTyping() {
  const item=document.createElement("article");
  item.className="message assistant";item.id="typingIndicator";
  item.innerHTML='<div class="message-avatar">B</div><div class="message-body"><div class="message-meta">BabyMind</div><div class="typing"><i></i><i></i><i></i></div></div>';
  $("#messages").append(item);
  $("#messages").scrollTop=$("#messages").scrollHeight;
}

async function loadConversations() {
  try { state.conversations=await api("/api/conversations"); }
  catch (_) { state.conversations=[]; }
}

async function openConversation(id) {
  try {
    const messages=await api("/api/conversations/"+encodeURIComponent(id));
    state.conversationId=id;
    $("#messages").innerHTML="";
    messages.forEach(item=>addMessage(item.role,item.content));
    setView("chat");
  } catch(error) { toast(error.message); }
}

async function newConversation() {
  state.conversationId=null;
  $("#messages").innerHTML='<div class="empty-chat" id="welcome"><div class="welcome-orb">B</div><h2>Hello. I\'m BabyMind.</h2><p>What would you like to talk about?</p></div>';
  $("#messageInput").focus();
}

async function sendMessage(message) {
  const text=message.trim();
  if(!text||state.busy)return;
  state.busy=true;
  $("#sendButton").disabled=true;
  $("#messageInput").value="";
  $("#messageInput").style.height="auto";
  addMessage("user",text);
  showTyping();
  try {
    const result=await api("/api/chat",{method:"POST",body:JSON.stringify({
      message:text,agent_id:"BM-01",conversation_id:state.conversationId||"",
      use_memory:true,remember:false,collaborate:false,deep_research:false,
      document_research:false,teamwork:false
    })});
    state.conversationId=result.conversation_id||state.conversationId;
    $("#typingIndicator")?.remove();
    addMessage("assistant",result.response||"I couldn't produce a response.");
    await loadConversations();
  } catch(error) {
    $("#typingIndicator")?.remove();
    addMessage("assistant",`I couldn't complete that message. ${error.message}`);
    toast(error.message);
  } finally {
    state.busy=false;
    $("#sendButton").disabled=false;
    $("#messageInput").focus();
  }
}

async function checkHealth() {
  try {
    const health=await api("/api/health");
    const online=Boolean(health.model_available);
    $("#statusDot").classList.toggle("online",online);
    $("#statusDot").classList.toggle("offline",!online);
    $("#connectionText").textContent=online?"Local model connected":"Waiting for local model";
  } catch (_) {
    $("#statusDot").classList.add("offline");
    $("#connectionText").textContent="BabyMind unavailable";
  }
}

function init() {
  document.querySelectorAll("[data-view]").forEach(tab=>tab.addEventListener("click",()=>setView(tab.dataset.view)));
  $("#chatForm").addEventListener("submit",event=>{event.preventDefault();sendMessage($("#messageInput").value);});
  $("#messageInput").addEventListener("input",event=>{
    event.target.style.height="auto";
    event.target.style.height=Math.min(event.target.scrollHeight,180)+"px";
  });
  $("#messageInput").addEventListener("keydown",event=>{
    if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("#chatForm").requestSubmit();}
  });
  $("#newChat").addEventListener("click",newConversation);
  loadConversations();
  checkHealth();
  setInterval(checkHealth,30000);
}

init();
