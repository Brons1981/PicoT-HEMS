// Render the real explanation functions with a tiny DOM surface; no device writes.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function el(tag,text='') {return {tag,text,children:[],append(...nodes){this.children.push(...nodes);}};}
function text(node){return [node.text,...node.children.map(text)].join(' ');}
const context={el}; vm.createContext(context);
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../picot_hc/web/heating.js'),'utf8'),context);
const d={basis:'cv_cheaper',selected:['cv'],room_temperature_c:17.3,room_target_c:19,thermostat_temperature_c:19,temperature_difference_c:1.7,
 candidates:{cv:{reason:null},beneden:{reason:null}},execution:{cv:{available:true,mode:'off',target_c:null,activity:'off',pending:true,fault:null,conflicts:[],restart_wait_seconds:0}},
 hems_advice:{status:'unavailable',reason:'Geen actuele energierichtlijn van HEMS.'},
 prices:{electricity_eur_kwh:.679,gas_eur_m3:1.42,gas_valid:true,gas_valid_until:'2027-01-01',interval:null,warnings:[]},
 assumptions:{cop_beneden:3.72,cop_boven:3,gas_kwh_m3:9.769444444444444,cv_efficiency:.9},electricity_break_even_eur_kwh:.6007847597};
module.exports=structuredClone(d);
let panel=el('section');context.renderHeatDecision(panel,d);context.renderHeatPrices(panel,d);
let output=text(panel);
for(const expected of ['CV gekozen omdat','17,3 °C','1,7 °C hoger','apparaat uit','wachten op bevestiging','0,679/kWh','1,420/m³','COP 3,72','90% rendement','0,601/kWh','totale kosten','HEMS-energieadvies'])assert.ok(output.includes(expected),expected);
assert.ok(!output.includes('verwarming gemeld'));
d.execution.cv.command_field='mode';
d.execution.cv.command_value='heat';
panel=el('section');context.renderHeatDecision(panel,d);
assert.ok(text(panel).includes('daarna wordt het temperatuurdoel ingesteld'));
d.basis='blocked';d.selected=[];d.prices.electricity_eur_kwh=null;d.prices.gas_valid=false;d.prices.warnings=['Prijsbron ontbreekt.'];
panel=el('section');context.renderHeatDecision(panel,d);context.renderHeatPrices(panel,d);output=text(panel);
assert.ok(output.includes('geen inzetbare bron'));assert.ok(output.includes('onbekend/kWh'));assert.ok(output.includes('Prijsbron ontbreekt.'));assert.ok(output.includes('niet geldig'));
assert.ok(!output.includes('CV gekozen omdat'));
console.log('Decision UI: cost basis, measured disagreement, pending/off and missing prices passed.');
