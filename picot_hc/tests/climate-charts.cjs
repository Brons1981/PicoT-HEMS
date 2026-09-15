const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const context={};
vm.createContext(context);
vm.runInContext(readFileSync(path.join(__dirname,'../picot_hc/web/climate-charts.js'),'utf8'),context);
const sample=(value,unit,quality='available')=>({value,unit,quality});
const history=[
  {time:20,zones:[{id:'beneden',samples:{temperature:sample(21,'°C'),humidity:sample(72,'%'),dewpoint:sample(16,'°C')}},{id:'boven',samples:{temperature:sample(30,'°C')}}]},
  {time:10,zones:[{id:'beneden',samples:{temperature:sample(0,'°C'),humidity:sample(0,'%')}}]},
  {time:30,zones:[{id:'beneden',samples:{temperature:sample(22,'°F'),humidity:sample(105,'%'),dewpoint:sample(12,'°C','unavailable')}}]},
];
const rows=JSON.parse(JSON.stringify(context.climateRecords(history,'beneden')));
assert.deepEqual(rows,[
  {time:10,temperature:0,humidity:0,dewpoint:null},
  {time:20,temperature:21,humidity:72,dewpoint:16},
  {time:30,temperature:null,humidity:null,dewpoint:null},
]);
assert.equal(context.climateRecords(history,'boven')[1].temperature,30);
assert.equal(context.climateRecords(history,'badkamer')[0].temperature,null);
assert.equal(history[0].time,20,'Chart preparation must not reorder stored input');
console.log('Climate series: zone separation, time order, old/missing observations, units and genuine zero passed.');
