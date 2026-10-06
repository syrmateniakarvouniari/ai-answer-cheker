const form = document.getElementById('checker');
const message = document.getElementById('message');
const get = id => document.getElementById(id);
function resetResults() {
  for (const id of ['claims','coverage','uncertainties','human','queries','sources','evidence','suggestions','search-status','limitations']) get(id).replaceChildren();
  get('corrected').textContent = 'Δεν υπάρχει ακόμη αποτέλεσμα.';
  get('empty').textContent = 'Δεν υπάρχει ολοκληρωμένη αξιολόγηση για τα τρέχοντα δεδομένα.';
  get('search-info').hidden = true;
}
function list(id, values) {
  for (const value of values) { const li=document.createElement('li');li.textContent=value;get(id).append(li); }
}
function link(source) {
  const a=document.createElement('a');
  const url=new URL(source.url);
  if(url.protocol!=='https:') throw new Error('Μη ασφαλής σύνδεσμος πηγής.');
  a.href=url.href;a.textContent=`[${source.id}] ${source.title}`;a.target='_blank';a.rel='noopener noreferrer';return a;
}
function render(result) {
  if(!result.search_attempted) throw new Error('Δεν πραγματοποιήθηκε προσπάθεια αναζήτησης.');
  for(const row of result.claims) {
    const tr=document.createElement('tr');
    for(const text of [row.claim,row.verdict,row.reason]) {const td=document.createElement('td');td.textContent=text;tr.append(td);}
    const td=document.createElement('td');
    if(!row.sources.length) td.textContent='Δεν βρέθηκε επαρκής πηγή';
    for(const source of row.sources) {const p=document.createElement('p');p.append(link(source));td.append(p);}
    if(row.support_ids.length) {const p=document.createElement('p');p.textContent='Τεκμήρια: '+row.support_ids.join(', ');td.append(p);}
    tr.append(td);const correction=document.createElement('td');correction.textContent=row.correction;tr.append(correction);get('claims').append(tr);
  }
  get('empty').textContent=result.claims.length?'Οι εκτιμήσεις είναι αποτελέσματα AI. Έλεγξε αν κάθε πηγή στηρίζει ακριβώς τον ισχυρισμό.':'Δεν εντοπίστηκαν ελέγξιμοι ισχυρισμοί.';
  get('corrected').textContent=result.corrected_answer;
  get('coverage').textContent=result.coverage;
  list('uncertainties',result.uncertainties);list('human',result.human_review);
  get('search-info').hidden=false;
  const searchStatus=result.search_complete?'Επιστράφηκαν αποσπάσματα για όλους τους επιλεγμένους ισχυρισμούς':result.search_verified?'Μερική κάλυψη αναζήτησης — ορισμένοι ισχυρισμοί δεν επαληθεύτηκαν':'Δεν επιστράφηκαν κατάλληλα αποσπάσματα — κανένας ισχυρισμός δεν επαληθεύτηκε';
  get('search-status').textContent=`${searchStatus} • ${result.search_provider} • ${result.model} • ${new Date(result.checked_at).toLocaleString('el-GR')}`;
  list('queries', result.queries);
  for(const source of result.sources) {const li=document.createElement('li');li.append(link(source));get('sources').append(li);}
  for(const [i,item] of result.supports.entries()) {
    const kind=item.kind==='page_text'?'Κείμενο σελίδας':'Απόσπασμα αναζήτησης';
    const p=document.createElement('p');p.textContent=`Τεκμήριο ${i+1} (${kind}${item.truncated?', περικομμένο':''}): ${item.text} `;
    for(const source of result.sources.filter(s=>item.source_ids.includes(s.id))) {p.append(link(source),document.createTextNode(' '));}
    get('evidence').append(p);
  }
  get('limitations').textContent=result.limitations;
  if(result.search_suggestions) {
    // Google's returned Search Suggestions live in an isolated, script-free frame.
    const iframe=document.createElement('iframe');
    iframe.title='Προτάσεις αναζήτησης Google';iframe.setAttribute('sandbox','allow-popups allow-popups-to-escape-sandbox');
    iframe.srcdoc=result.search_suggestions;iframe.style.width='100%';iframe.style.height='220px';iframe.style.border='0';
    get('suggestions').append(iframe);
  }
}
let revision=0;
form.addEventListener('input',()=>{revision++;resetResults();message.textContent='';});
form.addEventListener('submit',async event=>{
  event.preventDefault();resetResults();message.textContent='';
  const data=Object.fromEntries(new FormData(form));
  for(const [key,label] of [['question','Αρχική ερώτηση'],['answer','Απάντηση προς έλεγχο']]) {
    if(!data[key].trim()) {message.textContent=`Συμπλήρωσε το πεδίο «${label}».`;get(key).focus();return;}
  }
  const submittedRevision=revision;
  const button=form.querySelector('button');button.disabled=true;button.textContent='Αναζήτηση και έλεγχος…';
  message.textContent='Γίνεται επιλογή ισχυρισμών, αναζήτηση πηγών και δεύτερος έλεγχος τεκμηρίωσης. Περίμενε έως περίπου 6 λεπτά.';
  try {
    const response=await fetch('/api/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(360000)});
    const result=await response.json();
    if(submittedRevision!==revision) return;
    if(!response.ok) throw new Error(result.error || 'Η υπηρεσία δεν είναι διαθέσιμη.');
    render(result);message.textContent=result.search_complete?'Η αξιολόγηση ολοκληρώθηκε. Διάβασε τις αβεβαιότητες.':'Ο έλεγχος ολοκληρώθηκε με ελλείψεις αναζήτησης. Διάβασε ποιοι ισχυρισμοί δεν επαληθεύτηκαν.';
  } catch(error) {
    if(submittedRevision!==revision) return;
    resetResults();message.textContent=error.name==='TimeoutError'?'Η σύνδεση άργησε να απαντήσει. Ο έλεγχος δεν ολοκληρώθηκε.':error instanceof TypeError?'Δεν ήταν δυνατή η επικοινωνία. Έλεγξε ότι η εφαρμογή τρέχει. Ο έλεγχος δεν ολοκληρώθηκε.':error.message;
  } finally {button.disabled=false;button.textContent='Έλεγχος απάντησης';}
});

get('connection-test').addEventListener('click',async()=>{
 const button=get('connection-test');button.disabled=true;
 get('connection-message').textContent='Γίνεται απλή δοκιμή Gemini, χωρίς αναζήτηση…';
 try {
  const response=await fetch('/api/connection',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(70000)});
  const value=await response.json();
  if(!response.ok) throw new Error(value.error||'Αποτυχία σύνδεσης.');
  get('connection-message').textContent=value.message+' Μοντέλο: '+value.model;
 } catch(error){get('connection-message').textContent=error.message;}
 finally{button.disabled=false;}
});

get('search-test').addEventListener('click',async()=>{
 const button=get('search-test');button.disabled=true;
 get('search-message').textContent='Γίνεται μία δοκιμαστική αναζήτηση, χωρίς κλήση Gemini…';
 try {
  const response=await fetch('/api/search-connection',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(70000)});
  const value=await response.json();
  if(!response.ok) throw new Error(value.error||'Αποτυχία αναζήτησης.');
  get('search-message').textContent=value.message+` Κείμενο σελίδας σε ${value.page_text_count} αποτελέσματα.`;
 } catch(error){get('search-message').textContent=error.message;}
 finally{button.disabled=false;}
});
