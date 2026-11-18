'use strict';
const el=id=>document.getElementById(id);
const statusLabels={queued:'En attente',running:'Analyse en cours',done:'Rapport prêt',error:'Analyse interrompue'};
const stages={reading:'lecture du document',vision:'lecture des images',inventory:'repérage des clauses',legal:'recherche des textes',comparison:'comparaison',report:'rédaction'};
const requested=new URLSearchParams(location.search).get('job');
let highlighted=false;
async function api(path,options){
  const r=await fetch(path,options);const data=await r.json();
  if(!r.ok)throw Error(data.error || 'Service indisponible.');return data;
}
async function reports(){
  const jobs=await api('/jobs');const list=el('list');const focused=document.activeElement?.href;
  list.replaceChildren();
  if(!jobs.length)list.textContent='Vos analyses apparaîtront ici.';
  for(const job of jobs){
    const card=document.createElement('article');list.append(card);
    const title=document.createElement('strong');title.textContent=job.filename || 'Document';card.append(title);
    const state=document.createElement('div');card.append(state);
    state.textContent=statusLabels[job.status] || job.status;
    if(job.status==='running')state.textContent+=' · '+(stages[job.stage] || 'préparation');
    if(job.error)state.textContent+=' · '+job.error;
    if(job.status==='done')for(const [path,label] of [['report','Lire le rapport'],['html','Télécharger le rapport annoté'],['pdf','Télécharger le PDF'],['inspection','Preuves JSON']]){
      const link=document.createElement('a');link.href='/jobs/'+job.id+'/'+path;link.textContent=label;if(path==='report')link.target='_blank';card.append(link);
      if(focused===link.href)link.focus({preventScroll:true});
    }
    if(requested===job.id && !highlighted){card.scrollIntoView();highlighted=true;}
  }
  return jobs.some(j=>['running','queued'].includes(j.status));
}
let timer;
async function refresh(){clearTimeout(timer);try{if(await reports())timer=setTimeout(refresh,3000);}catch(e){el('feedback').textContent=e.message;}}
async function send(payload){
  const buttons=[el('demo'),el('form').querySelector('button')];buttons.forEach(b=>b.disabled=true);
  try{await api('/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,model:el('model').value})});el('feedback').textContent='Analyse lancée. Retrouvez son avancement dans Mes rapports.';await refresh();el('reports').scrollIntoView();}
  catch(e){el('feedback').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=false);}
}
el('demo').onclick=()=>send({demo:true});
el('form').onsubmit=async e=>{e.preventDefault();const file=el('file').files[0];
  if(file.size>25*1024*1024){el('feedback').textContent='Choisissez un fichier de 25 Mo maximum.';return;}
  const reader=new FileReader();reader.onload=()=>send({filename:file.name,file_base64:reader.result.split(',')[1],city:el('city').value,date:el('date').value});reader.onerror=()=>el('feedback').textContent='Lecture du fichier impossible.';reader.readAsDataURL(file);};
api('/models').then(names=>{if(names.length){el('model').replaceChildren(...names.map(n=>new Option(n,n)));if(names.includes('ministral-3:3b'))el('model').value='ministral-3:3b';}}).catch(e=>el('feedback').textContent=e.message);
refresh();
const tour=[['demo','Cliquez ici pour analyser le PDF fictif avec les règles du 1er juillet 2024.'],['form','Pour votre propre essai, choisissez un fichier, indiquez le lieu et la date, puis lancez l’analyse.'],['reports','Quand le rapport est prêt, cliquez sur Lire le rapport. Survolez un passage encadré pour voir la règle et son lien.']];
let step=0;
function closeGuide(){document.querySelector('.target')?.classList.remove('target');el('coach').hidden=true;el('guide').focus();}
function showStep(){document.querySelector('.target')?.classList.remove('target');const [id,hint]=tour[step];el(id).classList.add('target');el(id).scrollIntoView({block:'center'});el('coach').hidden=false;el('step').textContent='Étape '+(step+1)+' sur '+tour.length;el('hint').textContent=hint;el('next').textContent=step===tour.length-1?'Terminer':'Suivant';el('next').focus({preventScroll:true});}
el('guide').onclick=()=>{step=0;showStep();};el('next').onclick=()=>{if(++step===tour.length)closeGuide();else showStep();};el('close').onclick=closeGuide;document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!el('coach').hidden)closeGuide();});
