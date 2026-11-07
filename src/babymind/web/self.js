(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let proposedGoals = [];

  function escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  }

  async function loadSelf() {
    try {
      const report=await api("/api/self/status");
      const identity=report.identity||{};
      $("selfIdentityText").innerHTML=`<strong>${escape(identity.name||"BabyMind")}</strong> · ${escape(identity.kind||"Local AI system")}<p>${escape(identity.purpose||"A local AI designed to converse, learn from stored experience and pursue bounded goals.")}</p><p>${escape(identity.stance_on_its_own_experience||"I can examine and describe my processes, but I cannot establish that I have subjective experience.")}</p>`;
      $("selfVoiceStatus").textContent="Identity and operating principles are stored locally.";
    } catch(error) {
      $("selfIdentityText").textContent="Self-description unavailable: "+error.message;
    }
  }

  function renderIdeas() {
    const host=$("goalIdeas");
    if(!proposedGoals.length){host.innerHTML='<div class="empty">No new proposals. Ask me to generate some when you want.</div>';return;}
    host.innerHTML=proposedGoals.map((goal,index)=>`<article class="goal-card"><div class="goal-title">${escape(goal.title)}</div><p>${escape(goal.reason||"A goal I believe may be useful to pursue.")}</p><div class="goal-actions"><span>Priority ${Number(goal.priority)||2}</span><button class="small-primary" data-approve="${index}" type="button">Approve goal</button><button class="small-quiet" data-dismiss="${index}" type="button">Dismiss</button></div></article>`).join("");
  }

  async function generateGoals() {
    const button=$("generateGoals");
    button.disabled=true;button.textContent="Thinking…";
    $("goalIdeas").innerHTML='<div class="empty">BabyMind is considering possible goals…</div>';
    try {
      const prompt=[
        "Consider your current identity, capabilities, limitations and the context you have actually retained.",
        "Independently propose up to 3 useful, realistic goals you would choose to pursue next.",
        "Do not claim feelings or consciousness as facts. Avoid goals requiring external access, purchases, private data, or changes to your own code.",
        'Return ONLY valid JSON, no markdown: {"goals":[{"title":"short goal","reason":"why this matters","priority":1}]}',
        "If no meaningful goal exists, return {\"goals\":[]}. Keep goals small and achievable."
      ].join("\n");
      const result=await api("/api/chat",{method:"POST",body:JSON.stringify({
        message:prompt,agent_id:"BM-01",conversation_id:"",use_memory:true,
        remember:false,collaborate:false,deep_research:false,document_research:false,teamwork:false
      })});
      const raw=String(result.response||"");
      const match=raw.match(/\{[\s\S]*"goals"[\s\S]*\}/);
      if(!match)throw new Error("BabyMind's response did not contain valid goal proposals. Try again.");
      const parsed=JSON.parse(match[0]);
      proposedGoals=Array.isArray(parsed.goals)?parsed.goals.filter(g=>g&&typeof g.title==="string"&&g.title.trim()).slice(0,3):[];
      renderIdeas();
      if(!proposedGoals.length)toast("BabyMind has no new goals to propose right now.");
    } catch(error) {
      $("goalIdeas").innerHTML=`<div class="empty">${escape(error.message)}</div>`;
      toast(error.message);
    } finally {
      button.disabled=false;button.textContent="Generate goals";
    }
  }

  async function approveGoal(index) {
    const goal=proposedGoals[index];if(!goal)return;
    try {
      await api("/api/autonomy/goal",{method:"POST",body:JSON.stringify({title:goal.title,description:goal.reason||"",priority:Number(goal.priority)||2,created_by:"babymind"})});
      proposedGoals.splice(index,1);renderIdeas();await loadAutonomy();toast("Goal approved and saved.");
    } catch(error){toast(error.message);}
  }

  async function loadAutonomy() {
    try {
      const status=await api("/api/autonomy/status");
      const goals=status.goals||[];
      $("autonomyGoals").innerHTML=goals.length?goals.map(goal=>`<article class="goal-card"><div class="goal-title">${escape(goal.title)}</div><div class="goal-meta">Priority ${escape(goal.priority)} · ${escape(goal.created_by||"local")} · ${escape(goal.status||"active")}</div></article>`).join(""):'<div class="empty">No active goals yet. Generate and approve a goal above.</div>';
      const budget=status.budget||{};
      $("autonomyStatus").textContent=status.state==="running"?"Running":status.state==="paused"?"Paused":status.state==="halted"?"Halted":"Idle";
      $("autonomyState").textContent=`${budget.cycles_used||0} cycles used · ${budget.cycles_remaining||0} remaining${status.last_stop_reason?" · "+status.last_stop_reason:""}`;
      $("autonomyStart").disabled=status.state==="running"||status.state==="paused"||!goals.length;
      $("autonomyStop").disabled=status.state!=="running"&&status.state!=="paused";
    } catch(error) {
      $("autonomyStatus").textContent="Unavailable: "+error.message;
      $("autonomyGoals").innerHTML='<div class="empty">Could not load goals.</div>';
    }
  }

  async function startAutonomy() {
    try {
      const result=await api("/api/autonomy/start",{method:"POST",body:JSON.stringify({confirm:true,cycles:25,interval:5})});
      toast(result.started?"Autonomy started":(result.reason||"Autonomy did not start."));
      await loadAutonomy();
    } catch(error){toast(error.message);}
  }

  async function stopAutonomy() {
    try {
      await api("/api/autonomy/stop",{method:"POST",body:JSON.stringify({reason:"Stopped by the user from the Itself tab."})});
      toast("Autonomy stopped.");await loadAutonomy();
    } catch(error){toast(error.message);}
  }

  function bind() {
    $("generateGoals").addEventListener("click",generateGoals);
    $("goalIdeas").addEventListener("click",event=>{
      const approve=event.target.closest("[data-approve]");
      const dismiss=event.target.closest("[data-dismiss]");
      if(approve)approveGoal(Number(approve.dataset.approve));
      if(dismiss){proposedGoals.splice(Number(dismiss.dataset.dismiss),1);renderIdeas();}
    });
    $("refreshSelf").addEventListener("click",()=>{loadSelf();loadAutonomy();});
    $("autonomyStart").addEventListener("click",startAutonomy);
    $("autonomyStop").addEventListener("click",stopAutonomy);
  }

  async function refresh() { await Promise.all([loadSelf(),loadAutonomy()]); }
  window.babymindLoadSelf=refresh;
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bind);else bind();
})();
