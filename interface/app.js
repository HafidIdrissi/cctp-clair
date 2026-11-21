'use strict';
const el=id=>document.getElementById(id);
const statusLabels={queued:'En attente',running:'Analyse en cours',done:'Rapport prêt',error:'Analyse interrompue'};
const stages={reading:'lecture du document',vision:'lecture des images',inventory:'repérage des clauses',legal:'recherche des textes',comparison:'comparaison',report:'rédaction'};
const requested=new URLSearchParams(location.search).get('job');
let highlighted=false;
let activeJob=null;
let sending=false;
let refreshId=0;
let timer;
function updateLaunchButtons(){
  for(const button of [el('demo'),el('form').querySelector('button')])button.disabled=sending || !!activeJob;
}
async function api(path,options){
  const r=await fetch(path,options);const data=await r.json();
  if(!r.ok)throw Error(data.error || 'Service indisponible.');return data;
}
function showReports(jobs){
  const list=el('list');const focused=document.activeElement?.href;
  list.replaceChildren();
  if(!jobs.length)list.textContent='Vos analyses apparaîtront ici.';
  for(const job of jobs){
    const card=document.createElement('article');list.append(card);
    const title=document.createElement('strong');title.textContent=job.filename || 'Document';card.append(title);
    const state=document.createElement('div');card.append(state);
    state.textContent=statusLabels[job.status] || job.status;
    if(job.status==='running')state.textContent+=' · '+(stages[job.stage] || 'préparation');
    const progress=job.progress;
    if(job.status==='running' && job.stage==='comparison' && progress?.total>0)state.textContent+=' ('+progress.done+' / '+progress.total+')';
    if(job.error)state.textContent+=' · '+job.error;
    if(job.status==='done')for(const [path,label] of [['report','Lire le rapport'],['document','Inspecter le CCTP original'],['document-html','Télécharger le CCTP inspecté'],['html','Télécharger le rapport annoté'],['pdf','Télécharger le PDF'],['inspection','Preuves JSON']]){
      const link=document.createElement('a');link.href='/jobs/'+job.id+'/'+path;link.textContent=label;if(path==='report'||path==='document')link.target='_blank';card.append(link);
      if(focused===link.href)link.focus({preventScroll:true});
    }
    if(requested===job.id && !highlighted){card.scrollIntoView();highlighted=true;}
  }
}
async function refresh(){
  const id=++refreshId;
  clearTimeout(timer);
  try{
    const jobs=await api('/jobs');
    if(id!==refreshId)return;
    const previous=activeJob;
    activeJob=jobs.find(j=>['running','queued'].includes(j.status)) || null;
    showReports(jobs);
    if(activeJob){
      el('feedback').textContent='Analyse de '+(activeJob.filename || 'votre document')+' en cours. Suivez son avancement dans Mes rapports.';
    }else if(previous){
      const finished=jobs.find(j=>j.id===previous.id);
      if(finished?.status==='done')el('feedback').textContent='Rapport prêt. Cliquez sur « Lire le rapport » dans Mes rapports.';
      if(finished?.status==='error')el('feedback').textContent='Analyse interrompue. Consultez le détail dans Mes rapports.';
    }
    updateLaunchButtons();
  }catch(e){if(id===refreshId)el('feedback').textContent=e.message;}
  if(id===refreshId && activeJob)timer=setTimeout(refresh,3000);
}
async function send(payload){
  if(sending || activeJob)return;
  sending=true;updateLaunchButtons();
  try{
    activeJob=await api('/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,model:el('model').value})});
    el('reports').scrollIntoView();
  }catch(e){
    el('feedback').textContent=e.message==='Une analyse Core est déjà en cours.'?'Une analyse a déjà été lancée. Consultez Mes rapports.':e.message;
  }finally{
    await refresh();
    sending=false;updateLaunchButtons();
  }
}
el('demo').onclick=()=>send({demo:true});
el('form').onsubmit=async e=>{e.preventDefault();const file=el('file').files[0];
  if(file.size>25*1024*1024){el('feedback').textContent='Choisissez un fichier de 25 Mo maximum.';return;}
  const reader=new FileReader();reader.onload=()=>send({filename:file.name,file_base64:reader.result.split(',')[1],city:el('city').value,date:el('date').value});reader.onerror=()=>el('feedback').textContent='Lecture du fichier impossible.';reader.readAsDataURL(file);};
api('/models').then(names=>{if(names.length){el('model').replaceChildren(...names.map(n=>new Option(n,n)));if(names.includes('ministral-3:3b'))el('model').value='ministral-3:3b';}}).catch(e=>el('feedback').textContent=e.message);
refresh();
window.addEventListener('focus',refresh);
const tour=[['demo','Cliquez ici pour analyser le PDF fictif avec les règles du 1er juillet 2024.'],['form','Pour votre propre essai, choisissez un fichier, indiquez le lieu et la date, puis lancez l’analyse.'],['reports','Quand le rapport est prêt, cliquez sur Inspecter le CCTP original. Survolez un passage encadré pour voir la règle et son lien.']];
let step=0;
function closeGuide(){document.querySelector('.target')?.classList.remove('target');el('coach').hidden=true;el('guide').focus();}
function showStep(){document.querySelector('.target')?.classList.remove('target');const [id,hint]=tour[step];el(id).classList.add('target');el(id).scrollIntoView({block:'center'});el('coach').hidden=false;el('step').textContent='Étape '+(step+1)+' sur '+tour.length;el('hint').textContent=hint;el('next').textContent=step===tour.length-1?'Terminer':'Suivant';el('next').focus({preventScroll:true});}
el('guide').onclick=()=>{step=0;showStep();};el('next').onclick=()=>{if(++step===tour.length)closeGuide();else showStep();};el('close').onclick=closeGuide;document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!el('coach').hidden)closeGuide();});
