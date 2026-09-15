// Temperature/dewpoint share the left axis; relative humidity always uses 0–100%.
function climateRecords(history, zoneId) {
  return history.filter(row=>Number.isFinite(row.time)).map(row=>{
    const samples=row.zones.find(zone=>zone.id===zoneId)?.samples || {};
    const read=(key,unit)=>{
      const sample=samples[key];
      return sample?.quality==='available' && sample.unit===unit && Number.isFinite(sample.value)
        && (key!=='humidity' || (sample.value>=0 && sample.value<=100)) ? sample.value : null;
    };
    return {time:row.time,temperature:read('temperature','°C'),dewpoint:read('dewpoint','°C'),humidity:read('humidity','%')};
  }).sort((a,b)=>a.time-b.time);
}

function drawZoneClimate(canvas, history, zoneId) {
  const rows=climateRecords(history,zoneId), width=canvas.clientWidth, height=250;
  const dpr=window.devicePixelRatio || 1;
  canvas.width=width*dpr;canvas.height=height*dpr;canvas.style.height=height+'px';
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const left=46,right=width-46,top=26,bottom=height-34;
  const temperatures=rows.flatMap(row=>[row.temperature,row.dewpoint]).filter(v=>v!==null);
  let low=temperatures.length?Math.floor(Math.min(...temperatures)):0;
  let high=temperatures.length?Math.ceil(Math.max(...temperatures)):30;
  if(high===low){low-=1;high+=1;}
  const start=rows[0]?.time || 0, end=Math.max(start+1,rows.at(-1)?.time || 1);
  const X=time=>left+(time-start)/(end-start)*(right-left);
  const Y=(value,humidity)=>bottom-(humidity?value/100:(value-low)/(high-low))*(bottom-top);
  ctx.font='12px system-ui';ctx.fillStyle='#655d70';
  ctx.fillText('°C',3,14);ctx.textAlign='right';ctx.fillText('% RV',width-3,14);ctx.textAlign='left';
  for(let i=0;i<=4;i++){
    const y=bottom-i*(bottom-top)/4;
    ctx.fillStyle='#655d70';ctx.fillText((low+i*(high-low)/4).toLocaleString('nl-NL',{maximumFractionDigits:1}),2,y+4);
    ctx.textAlign='right';ctx.fillStyle='#367cad';ctx.fillText(String(i*25),width-2,y+4);ctx.textAlign='left';
    ctx.strokeStyle='#ede8f2';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
  }
  for(const [key,color,dash] of [['temperature','#8053ac',[]],['dewpoint','#c67c32',[3,3]],['humidity','#367cad',[7,4]]]){
    ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash);
    let previous=null;
    for(const row of rows){
      if(row[key]===null){previous=null;continue;}
      const y=Y(row[key],key==='humidity');
      if(previous && row.time-previous.time<300){
        ctx.beginPath();ctx.moveTo(X(previous.time),Y(previous[key],key==='humidity'));ctx.lineTo(X(row.time),y);ctx.stroke();
      }
      ctx.beginPath();ctx.arc(X(row.time),y,1.4,0,2*Math.PI);ctx.fill();previous=row;
    }
  }
  ctx.setLineDash([]);ctx.fillStyle='#655d70';
  const clock=t=>new Intl.DateTimeFormat('nl-NL',{timeZone:'Europe/Amsterdam',hour:'2-digit',minute:'2-digit'}).format(new Date(t*1000));
  if(rows.length){
    ctx.fillText(clock(start),left,height-8);ctx.textAlign='right';ctx.fillText(clock(end),right,height-8);ctx.textAlign='left';
  }
  if(!rows.some(row=>row.temperature!==null || row.dewpoint!==null || row.humidity!==null)){
    ctx.fillText('Nog geen bruikbare meetgegevens.',left,top+25);
  }
  const readout=document.getElementById(canvas.getAttribute('aria-describedby'));
  const describe=index=>{
    const row=rows[index];
    if(!row){readout.textContent='Nog geen meetgegevens.';return;}
    canvas.selectedTime=row.time;
    const number=(v,unit)=>v===null?'Niet beschikbaar':v.toLocaleString('nl-NL',{maximumFractionDigits:1})+' '+unit;
    const date=new Intl.DateTimeFormat('nl-NL',{timeZone:'Europe/Amsterdam',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(row.time*1000));
    readout.textContent=date+' · Temperatuur '+number(row.temperature,'°C')+' · Luchtvochtigheid '+number(row.humidity,'%')+' · Dauwpunt '+number(row.dewpoint,'°C');
  };
  let selected=Math.max(0,rows.findIndex(row=>row.time===canvas.selectedTime));
  if(!canvas.userSelected)selected=rows.length-1;
  describe(selected);
  const point=event=>{
    if(!rows.length)return;
    const x=(event.clientX-canvas.getBoundingClientRect().left)*width/canvas.getBoundingClientRect().width;
    const time=start+Math.max(0,Math.min(1,(x-left)/(right-left)))*(end-start);
    selected=rows.reduce((best,row,i)=>Math.abs(row.time-time)<Math.abs(rows[best].time-time)?i:best,0);
    canvas.userSelected=true;describe(selected);
  };
  canvas.onpointermove=point;canvas.onpointerdown=point;
  canvas.onkeydown=event=>{
    if(event.key!=='ArrowLeft' && event.key!=='ArrowRight')return;
    event.preventDefault();canvas.userSelected=true;selected=Math.max(0,Math.min(rows.length-1,selected+(event.key==='ArrowLeft'?-1:1)));describe(selected);
  };
}
