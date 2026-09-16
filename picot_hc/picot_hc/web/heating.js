/* Automatic heating controls; editable assumptions are not learned efficiencies. */
let heatingForm = null;
function renderHeating(data) {
  if (!data) return;
  const names = {cv:'Cv · beneden en boven', beneden:'Airco beneden', boven:'Airco boven', badkamer:'Badkamer elektrisch'};
  $('regulation-badge').textContent = data.enabled ? 'Automatische verwarming actief' : 'Automatische verwarming uit';
  $('heating-status').textContent = data.enabled
    ? 'HC regelt op de actuele temperatuurdoelen. Handmatige keuzes blijven leidend.'
    : 'Uit. Na een herstart opnieuw activeren. Controleer de apparaatstanden; herstart zet apparaten niet uit.';
  const decisions = $('heating-decisions'); decisions.replaceChildren();
  for (const [zone, state] of Object.entries(data.zones)) {
    const selected = Object.keys(data.desired).filter(s => s === zone || s === 'cv' && zone !== 'badkamer');
    decisions.append(el('p', zone + ': ' + state.reason + (selected.length ? ' Gekozen: ' + selected.map(s=>names[s]).join(', ') + '.' : '')));
  }
  const costs = $('heating-costs'); costs.replaceChildren();
  for (const [key, name] of Object.entries(names)) {
    const cost = data.costs[key];
    costs.append(el('p', name + ': ' + (typeof cost === 'number' ? '€ ' + cost.toLocaleString('nl-NL',{minimumFractionDigits:3,maximumFractionDigits:3}) + '/kWh warmte (schatting)' : 'geen geldige kostenbasis')));
  }
  const faults = $('heating-faults'); faults.replaceChildren();
  for (const [source, reason] of Object.entries(data.faults)) faults.append(el('p', names[source] + ': ' + reason));
  if (!heatingForm) {
    const form = el('form', undefined, 'heating-form'), fields = el('fieldset');
    const enabled = el('input'); enabled.type='checkbox'; enabled.name='enabled';
    const label = el('label','Automatische verwarming inschakelen '); label.append(enabled); fields.append(label);
    const inputs = {}, grid = el('div',undefined,'temperature-fields');
    for (const [key, text, min, max, step] of [
      ['cv_efficiency','Cv-rendement (fractie; 0,90 = 90%)',.5,1,.01],
      ['gas_kwh_m3','Gas bovenwaarde (kWh/m³)',8,13,'any'],
      ['cop_beneden','COP beneden · startschatting',1,8,.01],
      ['cop_boven','COP boven · startaanname',1,8,.01]
    ]) {
      const wrapper=el('label',text), input=el('input');
      Object.assign(input,{type:'number',name:key,min,max,step,required:true});
      inputs[key]=input;wrapper.append(input);grid.append(wrapper);
    }
    const save=el('button','Regeling opslaan');save.type='submit';
    const stop=el('button','Automatische verwarming uit');stop.type='button';
    const reset=el('button','Storingen vrijgeven na controle');reset.type='button';
    fields.append(grid,save,stop,reset);
    const message=el('p','','heating-save-status');message.setAttribute('role','status');
    form.append(fields,message);$('heating-editor').append(form);
    form.dirty=false;form.busy=false;form.revision=-1;form.session=null;
    form.addEventListener('input',()=>{form.dirty=true;message.textContent='Nog niet opgeslagen';});
    const post=async(path,payload)=>{
      if(form.busy)return;
      form.busy=true;fields.disabled=true;message.textContent='Opslaan…';
      try {
        const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-HC-CSRF':current.csrf_token},body:JSON.stringify(payload)});
        if(!response.ok){const failure=await response.json();throw Error(failure.error||'Opslaan mislukt.');}
        const result=await response.json();current.heating=result.heating;
        form.dirty=false;form.busy=false;renderHeating(result.heating);
        message.textContent=path.endsWith('/reset')?'Storingen vrijgegeven; HC beoordeelt opnieuw.':'Regeling opgeslagen.';
      } catch(error) { message.textContent=error.message||'Geen antwoord; controleer de actuele status.'; }
      finally {form.busy=false;fields.disabled=false;}
    };
    form.addEventListener('submit',event=>{
      event.preventDefault();
      post('api/heating',{revision:form.revision,settings:{enabled:enabled.checked,...Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,Number(v.value)]))}});
    });
    stop.addEventListener('click',()=>post('api/heating',{revision:current.heating.revision,settings:{...current.heating.settings,enabled:false}}));
    reset.addEventListener('click',()=>post('api/heating/reset',{}));
    form.sync=value=>{
      if(form.session!==current.csrf_token){form.session=current.csrf_token;form.revision=-1;form.dirty=false;}
      if(!form.dirty&&!form.busy&&value.revision>=form.revision){
        enabled.checked=value.settings.enabled;
        for(const [key,input]of Object.entries(inputs))input.value=value.settings[key];
        form.revision=value.revision;
      }
      reset.disabled=!Object.keys(value.faults).length;
    };
    heatingForm=form;
  }
  heatingForm.sync(data);
}
