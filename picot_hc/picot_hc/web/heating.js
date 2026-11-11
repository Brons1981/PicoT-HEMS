/* Automatic heating controls; editable assumptions are not learned efficiencies. */
let heatingForm = null;
function renderHeating(data) {
  if (!data) return;
  renderBathroomTimer(data);
  const names = {cv:'Cv · beneden en boven', beneden:'Airco beneden', boven:'Airco boven', badkamer:'Badkamer elektrisch'};
  $('regulation-badge').textContent = data.enabled ? 'Automatische verwarming actief' : data.timer?.active ? 'Badkamertimer actief' : 'Automatische verwarming uit';
  $('heating-status').textContent = data.enabled
    ? 'HC regelt op de actuele temperatuurdoelen. Handmatige keuzes blijven leidend.'
    : 'Automatische verwarming staat uit. De gekozen instelling blijft bij een herstart bewaard.';
  const decisions = $('heating-decisions'); decisions.replaceChildren();
  if (data.decision) renderHeatDecision(decisions, data.decision);
  for (const [zone, state] of Object.entries(data.zones)) {
    const selected = Object.keys(data.desired).filter(s => s === zone || s === 'cv' && zone !== 'badkamer');
    decisions.append(el('p', zone + ': ' + state.reason + (selected.length ? ' Gekozen: ' + selected.map(s=>names[s]).join(', ') + '.' : '')));
  }
  if (data.door_fan && data.door_fan.reason) decisions.append(el('p', data.door_fan.reason));
  const readiness = data.strategy_readiness;
  if (readiness) {
    decisions.append(el('h3', 'Meetbasis voor handhaven, verlagen en uitschakelen'));
    decisions.append(el('p', readiness.reason));
    for (const [name, model] of Object.entries(readiness.models || {})) {
      decisions.append(el('p', name + ': ' + model.matching + '/' + model.required +
        ' passende metingen; ' + model.recent + ' recent, ' + model.stored +
        ' opgeslagen. ' + model.reason));
    }
  }
  const costs = $('heating-costs'); costs.replaceChildren();
  if (data.decision) renderHeatPrices(costs, data.decision);
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

function heatNumber(value, digits=1) {
  return Number.isFinite(value) ? value.toLocaleString('nl-NL', {minimumFractionDigits:digits,maximumFractionDigits:digits}) : 'onbekend';
}

function renderHeatDecision(panel, d) {
  const names={beneden:'Airco beneden',cv:'CV'};
  const reasons={
    cv_cheaper:'CV gekozen omdat de geraamde kosten per kWh warmte lager zijn dan bij de airco.',
    cv_fallback:'CV gekozen omdat de airco op dit moment niet inzetbaar is.',
    airco_preferred:'Airco gekozen: bij gelijke of lagere geraamde warmtekosten heeft de airco voorrang, mits inzetbaar.',
    airco_available:'Airco gekozen omdat CV op dit moment niet voor de bronkeuze beschikbaar is.',
    minimum_run:'Bestaande warmtebron behouden gedurende de minimale looptijd van vijf minuten.',
    room_floor:'Airco gekozen om de kamerondergrens te bewaken; het apparaat gebruikt minimaal 18 °C.',
    energy_start:'Een actief verwarmingsstartplan bepaalt de bron en het startmoment.',
    disabled:'Automatische verwarming staat uit.',
    no_demand:'Geen warmtebron nodig bij het huidige temperatuurdoel.',
    blocked:'Er is warmtevraag, maar op dit moment geen inzetbare bron gekozen.'
  };
  panel.append(el('h3','Waarom deze warmtebron?'),el('p',reasons[d.basis] || d.room_reason));
  if(Number.isFinite(d.costs?.cv) && Number.isFinite(d.costs?.beneden))
    panel.append(el('p','Actuele raming: CV € '+heatNumber(d.costs.cv,3)+' tegenover airco € '+heatNumber(d.costs.beneden,3)+'/kWh warmte; verschil € '+heatNumber(Math.abs(d.costs.cv-d.costs.beneden),3)+'/kWh warmte.'));
  panel.append(el('p','Kamer: '+heatNumber(d.room_temperature_c)+' °C · HC-doel: '+heatNumber(d.room_target_c)+' °C · eTwist/CV-thermostaat: '+heatNumber(d.thermostat_temperature_c)+' °C.'));
  if(Number.isFinite(d.temperature_difference_c) && Math.abs(d.temperature_difference_c)>=.5)
    panel.append(el('p','De thermostaat meet '+heatNumber(Math.abs(d.temperature_difference_c))+' °C '+(d.temperature_difference_c>0?'hoger':'lager')+' dan de kamersensor. Dit kan de warmtelevering beïnvloeden; HC corrigeert dit verschil niet automatisch.'));
  for(const [source,candidate] of Object.entries(d.candidates))
    if(candidate.reason) panel.append(el('p',names[source]+': '+candidate.reason));
  for(const [source,state] of Object.entries(d.execution)) {
    if(!d.selected.includes(source) && !state.fault && !state.pending)continue;
    const mode=state.available ? ({off:'uit',heat:'verwarmen',auto:'automatisch'}[state.mode]||state.mode||'onbekend') : 'niet actueel';
    const activity=state.available ? ({heating:'verwarming gemeld',idle:'rust gemeld',off:'uit gemeld'}[state.activity]||'warmtelevering onbekend') : 'warmtelevering onbekend';
    panel.append(el('p',names[source]+' · '+(d.selected.includes(source)?'gekozen':'niet gekozen')+' · apparaat '+mode+' · instelling '+heatNumber(state.target_c)+' °C · '+activity+'.'));
    if(state.fault)panel.append(el('p',names[source]+' storing: '+state.fault));
    if(state.pending)panel.append(el('p',names[source]+': wachten op bevestiging van '+(source==='cv' && state.command_field==='mode' && state.command_value==='heat'?'de verwarmingsmodus; daarna wordt het temperatuurdoel ingesteld.':'de opdracht.')));
    if(d.selected.includes(source) && state.conflicts.length)panel.append(el('p','Overname wacht op vrijgave van '+state.conflicts.map(s=>names[s]||s).join(', ')+'.'));
    if(d.selected.includes(source) && state.restart_wait_seconds>0)panel.append(el('p','Herstartvertraging: nog '+Math.ceil(state.restart_wait_seconds)+' seconden.'));
  }
  const advice=d.hems_advice;
  panel.append(el('p','HEMS-energieadvies: '+advice.reason+' Dit advies is apart van de HC-bronkeuze; comfort wordt door HC geregeld.'));
}

function renderHeatPrices(panel, d) {
  const p=d.prices, a=d.assumptions;
  panel.append(el('h3',d.basis==='energy_start'?'Actuele referentieprijzen':'Prijzen en aannames voor deze keuze'));
  if(d.basis==='energy_start')panel.append(el('p','Een actief startplan bepaalt deze keuze. Onderstaande actuele prijzen zijn referentieprijzen en vormen niet de volledige kostenvergelijking van dat plan.'));
  const interval=p.interval;
  const time=t=>new Date(t*1000).toLocaleTimeString('nl-NL',{timeZone:'Europe/Amsterdam',hour:'2-digit',minute:'2-digit'});
  panel.append(el('p','Stroom: € '+heatNumber(p.electricity_eur_kwh,3)+'/kWh'+(interval?' · tijdvak '+time(interval.start)+'–'+time(interval.end):'')+'.'));
  panel.append(el('p',p.confirmed?'Tariefbasis bevestigd in HC; de prijs wordt overgenomen uit HA, zonder hier extra belastingen of opslagen toe te voegen.':'Tariefbasis niet bevestigd; deze bronprijs mag nog niet voor automatische bronkeuze worden gebruikt.'));
  panel.append(el('p','Gas: € '+heatNumber(p.gas_eur_m3,3)+'/m³ · '+(p.gas_valid?'geldig tot en met ':'niet geldig; ingestelde einddatum ')+(p.gas_valid_until||'onbekend')+'.'));
  for(const warning of p.warnings)panel.append(el('p',warning));
  panel.append(el('p','Airco beneden: stroomprijs ÷ COP '+heatNumber(a.cop_beneden,2)+'. Airco boven: COP '+heatNumber(a.cop_boven,2)+'.'));
  panel.append(el('p','CV: gasprijs ÷ ('+heatNumber(a.gas_kwh_m3,3)+' kWh/m³ × '+heatNumber(a.cv_efficiency*100,0)+'% rendement).'));
  if(Number.isFinite(d.electricity_break_even_eur_kwh))panel.append(el('p','Bij deze aannames is CV goedkoper boven € '+heatNumber(d.electricity_break_even_eur_kwh,3)+'/kWh stroom, als beide bronnen inzetbaar zijn.'));
  panel.append(el('p','Dit zijn schattingen per kWh warmte met ingestelde rendementen. Opwarmduur, restwarmte, CV-hulpstroom en de totale kosten van de verwarmingsperiode zitten niet in deze vergelijking. Batterij- en PV-kosten worden hierin niet afzonderlijk verrekend.'));
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
