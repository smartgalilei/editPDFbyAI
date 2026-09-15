const $ = id => document.getElementById(id);
let token = location.hash.slice(1) || sessionStorage.getItem('pdfedit-token') || '';
if (token) sessionStorage.setItem('pdfedit-token', token);
history.replaceState(null, '', '/');
let state = {pages:[], revision:0}, page = 1, preview = null, showingAfter = true, busy = false, imageURL, imageSerial = 0;
async function api(path, data, binary = false) {
  const options = {headers:{'X-PDFedit-Token':token}};
  if (data !== undefined) { options.method='POST'; options.body=binary?data:JSON.stringify(data); options.headers['Content-Type']=binary?'application/pdf':'application/json'; }
  const r=await fetch('/api/'+path, options);
  if (!r.ok) { let message='Request failed.'; try { message=(await r.json()).error; } catch {} throw new Error(message); }
  return r.headers.get('Content-Type').includes('application/json')?r.json():r.blob();
}
function toast(message, error=false) { $('toast').textContent=message; $('toast').className=error?'error':''; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,error?10000:4500); }
function setBusy(value) { busy=value; document.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=value); if(!value) controls(); }
async function run(fn) { if(busy)return; setBusy(true); try { await fn(); } catch(e) { toast(e.message,true); } finally {setBusy(false);$('busyNote').hidden=true;} }
function controls(){ $('undoBtn').disabled=!state.canUndo; $('redoBtn').disabled=!state.canRedo; $('applyBtn').disabled=!preview?.pages; $('prevBtn').disabled=page<=1; $('nextBtn').disabled=page>=visibleCount(); }
function visibleCount(){return preview&&showingAfter?preview.pages:state.pages.length;}
function sync(next) {
  state=next;
  $('approxDocumentNote').hidden=!state.approximateFonts?.length;
  $('approxDocumentNote').textContent='This document contains approximated glyphs: '+(state.approximateFonts||[]).join('; ');
  page=Math.max(1,Math.min(page,state.pages.length)); preview=null;
  $('planBox').hidden=true; $('compareBar').hidden=true;
  $('welcome').hidden=!!state.pages.length; $('editor').hidden=!state.pages.length;
  $('filename').textContent=state.name; $('pagecount').textContent=state.pages.length+' pages';
  $('thumbCount').textContent=state.pages.length;
  $('keyStatus').textContent=state.keyReady?'API key configured (hidden for security).':'No API key configured.';
  if(state.pages.length) draw(); controls();
}
function draw(){
  $('thumbnails').replaceChildren();
  for(let n=1;n<=visibleCount();n++){
    const b=document.createElement('button');b.className='thumb'+(page===n?' active':'');b.title='Go to page '+n;
    const icon=document.createElement('span');icon.className='mini-page';icon.textContent=n;
    b.append(icon,document.createTextNode('Page '+n));b.onclick=()=>{page=n;draw();};$('thumbnails').append(b);
  }
  $('pageLabel').textContent=page+' / '+visibleCount();
  $('viewLabel').textContent=preview?(showingAfter?'After · Not applied':'Before · Current document'):'Current document';
  $('scanNote').hidden=!!state.pages[Math.min(page,state.pages.length)-1]?.lines?.length;
  controls();loadImage();
}
async function loadImage(){const serial=++imageSerial;$('imageError').hidden=true;try{const blob=await api((preview&&showingAfter?'preview-page':'page')+'?page='+page);if(serial!==imageSerial)return;if(imageURL)URL.revokeObjectURL(imageURL);imageURL=URL.createObjectURL(blob);$('pageImage').src=imageURL;setZoom();}catch(e){if(serial===imageSerial){$('pageImage').removeAttribute('src');$('imageError').textContent=e.message;$('imageError').hidden=false;}}}
function setZoom(){const z=$('zoom').value; const w=state.pages[Math.min(page,state.pages.length)-1]?.width||595;$('pageImage').style.maxWidth=z==='fit'?'100%':'none';$('pageImage').style.width=z==='fit'?'':(w*Number(z)/100)+'px';}
function selectedPages(){ if($('scope').value==='all')return state.pages.map(p=>p.page);if($('scope').value==='current')return [Math.min(page,state.pages.length)];const result=new Set();for(const part of $('customPages').value.split(/[,，]/)){const m=part.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);if(!m)throw new Error('Use a page range such as 1, 3-5.');const a=+m[1],b=+(m[2]||m[1]);if(a<1||b<a||b>state.pages.length)throw new Error('Page range is outside this document.');for(let i=a;i<=b;i++)result.add(i);}return [...result];}
function showPlan(result){preview=result.pages?result:null;showingAfter=true;page=Math.min(page,result.pages||state.pages.length);$('planSummary').textContent=result.summary;$('planList').replaceChildren();for(const text of result.summaries){const li=document.createElement('li');li.textContent=text;$('planList').append(li);}$('planBox').hidden=false;$('compareBar').hidden=!preview;$('applyBtn').hidden=!preview;$('beforeBtn').classList.remove('selected');$('afterBtn').classList.add('selected');draw();}
async function upload(file){if(!file)return;await run(async()=>{if(file.size>40*1024*1024)throw new Error('File exceeds the 40 MB limit.');if(state.pages.length&&!confirm('Opening another document clears the current history. Export any changes you want to keep first. Continue?'))return;const next=await api('upload',file,true);state=next;sync(await api('name',{revision:next.revision,name:file.name}));toast('Document opened. Your original is unchanged.');});$('fileInput').value='';}
$('openBtn').onclick=e=>{e.stopPropagation();$('fileInput').click();};$('dropzone').onclick=()=>$('fileInput').click();$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('fileInput').click();}};$('fileInput').onchange=e=>upload(e.target.files[0]);
for(const event of ['dragover','dragleave','drop'])$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.toggle('drag',event==='dragover');if(event==='drop')upload(e.dataTransfer.files[0]);});
$('demoBtn').onclick=()=>run(async()=>sync(await api('demo',{})));
$('settingsBtn').onclick=()=>{$('apiKey').value='';$('modelSelect').value=state.model||'deepseek-flash';$('settings').showModal();};$('closeSettings').onclick=()=>$('settings').close();
$('keyForm').onsubmit=e=>{e.preventDefault();run(async()=>{if(!$('apiKey').value.trim())throw new Error('Enter your API key.');const result=await api('key',{key:$('apiKey').value,model:$('modelSelect').value});state.keyReady=result.keyReady;state.model=$('modelSelect').value;$('apiKey').value='';$('keyStatus').textContent='API key configured (hidden for security).';$('settings').close();toast('API key saved in local service memory.');});};
$('clearKey').onclick=()=>run(async()=>{await api('key',{key:''});state.keyReady=false;$('apiKey').value='';$('keyStatus').textContent='No API key configured.';toast('API key cleared.');});
$('scope').onchange=()=>$('customPages').hidden=$('scope').value!=='custom';
$('planBtn').onclick=()=>run(async()=>{if(!state.keyReady){$('settings').showModal();throw new Error('Connect DeepSeek first.');}if(!$('instruction').value.trim())throw new Error('Describe the change you want to make.');const pages=selectedPages();$('busyNote').hidden=false;await api('discard',{revision:state.revision});preview=null;$('compareBar').hidden=true;$('planBox').hidden=true;draw();const result=await api('plan',{revision:state.revision,instruction:$('instruction').value,pages,approximateDigits:true});showPlan(result);});
for(const b of document.querySelectorAll('[data-prompt]'))b.onclick=()=>{$('instruction').value=b.dataset.prompt.replace('page 1','page '+Math.min(page,state.pages.length));$('instruction').focus();};
$('applyBtn').onclick=()=>run(async()=>{sync(await api('apply',{revision:state.revision,candidateId:preview.candidateId}));toast('Changes applied. You can undo or export a new PDF.');});
$('discardBtn').onclick=()=>run(async()=>sync(await api('discard',{revision:state.revision})));
for(const id of ['undo','redo'])$(id+'Btn').onclick=()=>run(async()=>sync(await api(id,{revision:state.revision})));
$('changeBtn').onclick=()=>run(async()=>{if(confirm('Closing clears this document and its edit history. Export any changes you want to keep first.'))sync(await api('close',{}));});
$('exportBtn').onclick=()=>run(async()=>{if(preview&&!confirm('There are unapplied changes. Export the currently applied version?'))return;const blob=await api('export');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=(state.name.replace(/\.pdf$/i,'')||'document')+'-edited.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);toast('Your PDF download has started.');});
$('prevBtn').onclick=()=>{if(page>1){page--;draw();}};$('nextBtn').onclick=()=>{if(page<visibleCount()){page++;draw();}};$('zoom').onchange=setZoom;
$('beforeBtn').onclick=()=>{showingAfter=false;page=Math.min(page,state.pages.length);$('beforeBtn').classList.add('selected');$('afterBtn').classList.remove('selected');draw();};$('afterBtn').onclick=()=>{showingAfter=true;page=Math.min(page,preview.pages);$('afterBtn').classList.add('selected');$('beforeBtn').classList.remove('selected');draw();};
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)){e.preventDefault();if(!busy)$(e.shiftKey?'redoBtn':'undoBtn').click();}if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&document.activeElement===$('instruction')){e.preventDefault();$('planBtn').click();}});
window.addEventListener('beforeunload',e=>{if(state.canUndo||preview){e.preventDefault();e.returnValue='';}});
run(async()=>sync(await api('state')));
