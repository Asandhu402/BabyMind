// Minimal two-tab BabyMind UI test (jsdom).
const fs=require("fs");
const path=require("path");
const {JSDOM}=require("jsdom");
const root=path.join(__dirname,"..","src","babymind","web");
const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
const app=fs.readFileSync(path.join(root,"app.js"),"utf8");
const self=fs.readFileSync(path.join(root,"self.js"),"utf8");
const calls=[];
const json=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>body});
const dom=new JSDOM(html,{url:"http://127.0.0.1:8765/",runScripts:"dangerously",pretendToBeVisual:true});
const w=dom.window;
w.fetch=async(url,options={})=>{
  const method=(options.method||"GET").toUpperCase();
  calls.push({url,method,body:options.body||null});
  if(url==="/api/health")return json({model_available:true});
  if(url==="/api/conversations")return json([]);
  if(url==="/api/self/status")return json({identity:{name:"BabyMind",kind:"local AI",purpose:"Think and learn.",stance_on_its_own_experience:"Subjective experience is unknown."}});
  if(url==="/api/autonomy/status")return json({state:"stopped",goals:[{id:"g1",title:"Keep learning",priority:2,created_by:"user",status:"active"}],budget:{cycles_used:0,cycles_remaining:25}});
  if(url==="/api/chat"){
    const payload=JSON.parse(options.body);
    if(payload.message.includes("Independently propose"))return json({conversation_id:"idea-chat",response:'{"goals":[{"title":"Study a topic deeply","reason":"Expand verified knowledge.","priority":1}]}'});
    return json({conversation_id:"chat-1",response:"Hello from BabyMind.",agent_name:"BabyMind",agents_involved:["BM-01"]});
  }
  if(url==="/api/autonomy/goal")return json({id:"g2",title:JSON.parse(options.body).title},201);
  if(url==="/api/autonomy/start")return json({started:true,state:"running"});
  if(url==="/api/autonomy/stop")return json({state:"stopped"});
  return json({});
};
for(const source of [app,self]){const script=w.document.createElement("script");script.textContent=source;w.document.body.appendChild(script);}
const wait=()=>new Promise(resolve=>setTimeout(resolve,50));
const checks=[];
const check=(name,ok)=>{checks.push([name,!!ok]);console.log((ok?"PASS ":"FAIL ")+name);};
(async()=>{
  await wait();
  const doc=w.document;
  check("exactly two navigation tabs",doc.querySelectorAll(".tab").length===2);
  check("only Chat and Itself views exist",doc.querySelectorAll(".view").length===2&&!!doc.querySelector("#chatView")&&!!doc.querySelector("#selfView"));
  doc.querySelector('[data-view="self"]').click();await wait();
  check("Itself tab loads identity",doc.querySelector("#selfIdentityText").textContent.includes("BabyMind"));
  check("active goals are visible",doc.querySelector("#autonomyGoals").textContent.includes("Keep learning"));
  doc.querySelector("#generateGoals").click();await wait();
  check("goal generator calls the same local chat API",calls.some(c=>c.url==="/api/chat"&&JSON.parse(c.body).message.includes("Independently propose")));
  check("generated goal is presented for approval",doc.querySelector("#goalIdeas").textContent.includes("Study a topic deeply"));
  doc.querySelector("[data-approve]").click();await wait();
  const goalCall=calls.find(c=>c.url==="/api/autonomy/goal");
  check("approval saves the proposed goal",!!goalCall&&JSON.parse(goalCall.body).title==="Study a topic deeply");
  doc.querySelector('[data-view="chat"]').click();
  doc.querySelector("#messageInput").value="Hello";
  doc.querySelector("#chatForm").dispatchEvent(new w.Event("submit",{bubbles:true,cancelable:true}));await wait();
  check("chat sends a normal message",calls.some(c=>c.url==="/api/chat"&&JSON.parse(c.body).message==="Hello"));
  check("chat displays the model response",doc.querySelector("#messages").textContent.includes("Hello from BabyMind."));
  const failed=checks.filter(([,ok])=>!ok);
  console.log("\n"+(checks.length-failed.length)+"/"+checks.length+" checks passed");
  w.close();
  if(failed.length)process.exit(1);
})().catch(error=>{console.error(error);w.close();process.exit(1);});
