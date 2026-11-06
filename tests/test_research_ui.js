// DOM-level integration test for the opt-in research chat route.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const web = path.join(__dirname, '..', 'src', 'babymind', 'web');
const window = new JSDOM(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), {
  url: 'http://127.0.0.1:8765/', runScripts: 'dangerously', pretendToBeVisual: true,
}).window;
const calls = [];
const response = (data) => ({ ok: true, status: 200, json: async () => data });
window.fetch = async (url, options = {}) => {
  calls.push({url, body: options.body});
  if (url === '/api/agents') return response([{id:'BM-01',name:'Coordinator',domain:'core'}]);
  if (url === '/api/conversations') return response([]);
  if (url === '/api/health') return response({status:'ok'});
  if (url === '/api/memory/profile') return response(options.method === 'POST' ? {saved:true} : {content:'Existing preference'});
  if (url === '/api/memory') return response([]);
  if (url === '/api/chat') return response({conversation_id:'id',response:'Observed [1].',agent_name:'Coordinator',agents_involved:['BM-01'],research:{sources:[
    {id:1,title:'<img src=x onerror=alert(1)>',url:'https://example.com/page'},
    {id:2,title:'Unsafe',url:'javascript:alert(1)'},
  ]}});
  return response({});
};
window.eval(fs.readFileSync(path.join(web, 'app.js'), 'utf8'));
const flush = () => new Promise(resolve => setTimeout(resolve, 100));
(async () => {
  await flush();
  const doc = window.document;
  const deep = doc.querySelector('#deepResearchToggle');
  const webToggle = doc.querySelector('#webResearchToggle');
  const collaboration = doc.querySelector('#collaborateToggle');
  webToggle.checked = true; webToggle.dispatchEvent(new window.Event('change'));
  collaboration.checked = true; collaboration.dispatchEvent(new window.Event('change'));
  deep.checked = true; deep.dispatchEvent(new window.Event('change'));
  if (webToggle.checked || collaboration.checked) throw Error('conflicting modes not cleared');
  doc.querySelector('#messageInput').value = 'What is this?';
  doc.querySelector('#chatForm').dispatchEvent(new window.Event('submit', {cancelable:true}));
  await flush();
  const request = calls.find(call => call.url === '/api/chat');
  if (!request || !JSON.parse(request.body).deep_research) throw Error('deep research not routed to chat');
  if (calls.some(call => call.url === '/api/research')) throw Error('legacy research unexpectedly requested');
  const links = doc.querySelectorAll('.message.assistant a');
  if (links.length !== 1 || links[0].href !== 'https://example.com/page' || !links[0].rel.includes('noopener')) throw Error('source links unsafe or absent');
  if (doc.querySelector('.message.assistant img')) throw Error('source title interpreted as HTML');
  if (!links[0].textContent.includes('<img')) throw Error('source title missing');
  doc.querySelector('[data-view="memory"]').click();
  await flush();
  if (doc.querySelector('#memoryProfile').value !== 'Existing preference') throw Error('context card not loaded');
  doc.querySelector('#memoryProfile').value = 'New preference';
  doc.querySelector('#memoryProfileForm').dispatchEvent(new window.Event('submit', {cancelable:true}));
  await flush();
  const profileRequest = calls.find(call => call.url === '/api/memory/profile' && call.body);
  if (!profileRequest || JSON.parse(profileRequest.body).content !== 'New preference') throw Error('context card not saved');
  console.log('Research chat UI checks passed');
  window.close();
})().catch(error => { console.error(error); window.close(); process.exitCode = 1; });
