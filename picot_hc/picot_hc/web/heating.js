/* Automatic heating controls; editable assumptions are not learned efficiencies. */
let heatingForm = null;
function renderHeating(data) {
  if (!data) return;
  renderBathroomTimer(data);
  const names = {cv:'Cv · beneden en boven', beneden:'Airco beneden', boven:'Airco boven', badkamer:'Badkamer elektrisch'};
  $('regulation-badge').textContent = data.enabled ? 'Automatische verwarming actief' : data.timer?.active ? 'Badkamertimer actief' : 'Automatische verwarming uit';
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

let bathroomTimerForm = null;
function renderBathroomTimer(data) {
  const timer=data.timer;
  if(!timer)return;
  if(!bathroomTimerForm){
    const panel=el('section',undefined,'panel');panel.id='bathroom-timer';
    const title=el('h2','Badkamer · verwarming met timer');
    const status=el('p');status.setAttribute('role','status');
    const form=el('form',undefined,'heating-form'),fields=el('fieldset');
    const minutes=el('input'),temperature=el('input');
    Object.assign(minutes,{type:'number',name:'minutes',min:1,max:180,step:1,required:true});
    Object.assign(temperature,{type:'number',name:'temperature',min:5,max:35,step:'any',required:true});
    const ml=el('label','Duur (minuten)'),tl=el('label','Temperatuur (°C)');
    ml.append(minutes);tl.append(temperature);
    const start=el('button','Start timer');start.type='submit';
    const stop=el('button','Stop timer');stop.type='button';
    const message=el('p');message.setAttribute('role','status');
    fields.append(ml,tl,start,stop);form.append(fields,message);
    panel.append(title,status,form,el('p','Werkt ook als de algemene regeling uit staat. Na afloop geldt weer het vaste badkamerdoel als de regeling actief is; anders stopt HC zijn badkamerverwarming. Handmatige bediening beëindigt de timer. Na een herstart wordt de timer afgebroken en stopt HC zijn timerverwarming zodra bereikbaar. Controleer de terugmelding.','sub'));
    $('zones').after(panel);
    form.dirty=false;form.busy=false;form.session=null;form.revision=-1;
    form.addEventListener('input',()=>{form.dirty=true;});
    const post=async(action)=>{
      if(form.busy)return;
      form.busy=true;fields.disabled=true;message.textContent='Timer opslaan…';
      const payload={revision:form.revision,action};
      if(action==='start')Object.assign(payload,{minutes:Number(minutes.value),temperature:Number(temperature.value)});
      try{
        const response=await fetch('api/heating/timer',{method:'POST',headers:{'Content-Type':'application/json','X-HC-CSRF':current.csrf_token},body:JSON.stringify(payload)});
        const result=await response.json();if(!response.ok)throw Error(result.error||'Timer opslaan mislukt.');
        current.heating=result.heating;form.dirty=false;form.busy=false;renderHeating(result.heating);
        message.textContent=action==='start'?'Timer gestart; HC controleert de meting en bron.':'Timerdoel vervallen; HC controleert de bron.';
      }catch(error){message.textContent=error.message||'Geen antwoord; controleer de actuele timerstatus.';}
      finally{form.busy=false;fields.disabled=false;}
    };
    form.addEventListener('submit',event=>{event.preventDefault();post('start');});
    stop.addEventListener('click',()=>post('stop'));
    form.sync=(value,zone)=>{
      if(form.session!==current.csrf_token){form.session=current.csrf_token;form.dirty=false;}
      if(!form.busy){
        form.revision=value.revision;
        if(!form.dirty){minutes.value=value.minutes;temperature.value=value.temperature;}
      }
      start.textContent=value.active?'Timer opnieuw starten':'Start timer';
      stop.disabled=!value.active;
      status.textContent=value.active
        ? 'Timer actief: '+value.temperature+' °C · nog '+Math.ceil(value.remaining_seconds/60)+' minuten. '+zone.reason
        : ({idle:'Geen timer actief.',stopped:'Timer gestopt.',expired:'Timer afgelopen.',restart:'Timer afgebroken door herstart.',manual:'Timer beëindigd door handmatige bediening.'}[value.status]||'Timer afgelopen.');
    };
    bathroomTimerForm=form;
  }
  bathroomTimerForm.sync(timer,data.zones.badkamer);
}
