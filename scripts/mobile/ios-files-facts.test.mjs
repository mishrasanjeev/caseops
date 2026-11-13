import assert from 'node:assert/strict';
import test from 'node:test';
import {findIosFileFact} from '../../apps/mobile/e2e/ios-files.mjs';

const id='files-viewer-unavailable-11111111-1111-4111-8111-111111111111';
const viewportQuery='-ios predicate string:type == "XCUIElementTypeScrollView" AND visible == 1';
function fixture(t,{alwaysOffscreen=false,invisible=false,wrongName=false,wrongType=false,duplicates=false,visibleScrolls=1,lateFinder=false,lateGeometry=false,unknownFrame=false,horizontal=false,outsideViewport=false,keyboard=false}={}){
 let now=0,drags=0,lookups=0,readsAtFirstDrag=null;const waits=[],queries=[],dispatches=[];
 t.mock.method(performance,'now',()=>now);
 const step=value=>{now+=130;return value;};
 const target={elementId:'owned-fact',getAttribute:async key=>step(key==='name'?(wrongName?'different':id):key==='type'?(wrongType?'XCUIElementTypeButton':'XCUIElementTypeStaticText'):null),isDisplayed:async()=>step(!invisible&&drags>0)};
 const scroll={elementId:'owned-scroll',isDisplayed:async()=>step(true)};
 const driver={
  $$:async query=>{queries.push(query);if(query==='~'+id){lookups++;if(lateFinder){now+=1501;return[target];}return step(duplicates?[target,{...target,elementId:'duplicate'}]:[target]);}if(keyboard&&query.includes('XCUIElementTypeKeyboard'))return step([{elementId:'keyboard',isDisplayed:async()=>step(true)}]);if(query.includes('XCUIElementTypeScrollView'))return step(Array.from({length:visibleScrolls},()=>scroll));return step([]);},
  getElementRect:async elementId=>step(elementId===scroll.elementId?{x:0,y:outsideViewport?900:125,width:402,height:638}:{x:horizontal?-1:20,y:alwaysOffscreen||drags===0?1206:410,width:unknownFrame?NaN:362,height:43}),
  getWindowRect:async()=>{if(lateGeometry)now+=1501;return step({x:0,y:0,width:402,height:874});},
  waitUntil:async(condition,options)=>{waits.push(options);const end=now+options.timeout;let last;for(;;){try{if(await condition())return true;}catch(error){last=error;}if(now>=end)throw last??new Error(options.timeoutMsg);now+=options.interval;}},
  performActions:async actions=>{if(readsAtFirstDrag===null)readsAtFirstDrag=lookups;drags++;dispatches.push(actions);now+=650;},
  releaseActions:async()=>{now+=20;},
 };
 return{context:{driver,platform:'ios',record:()=>{}},target,waits,queries,dispatches,stats:()=>({drags,lookups,readsAtFirstDrag})};
}

test('known offscreen iOS file facts scroll after one measured observation within the unchanged window',async t=>{
 const f=fixture(t);const actual=await findIosFileFact(f.context,id,'XCUIElementTypeStaticText');
 assert.equal(actual,f.target);assert.deepEqual(f.stats(),{drags:1,lookups:2,readsAtFirstDrag:1});
 assert.ok(f.waits.every(x=>x.timeout===1500&&x.interval===150));
 assert.ok(f.queries.includes(viewportQuery));
 const actions=f.dispatches[0][0].actions;assert.equal(actions[0].x,8);assert.equal(actions[2].duration,650);
});

test('iOS file facts preserve exact identity, role, unique-match and visible viewport denials',async t=>{
 for(const [options,code]of [[{wrongName:true},'IOS_FILES_FACT_ID_MISMATCH'],[{wrongType:true},'IOS_FILES_FACT_TYPE_MISMATCH'],[{duplicates:true},'IOS_FILES_FACT_ID_NOT_UNIQUE'],[{visibleScrolls:0},'IOS_FILES_VIEWPORT_REQUIRED'],[{visibleScrolls:2},'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR'],[{unknownFrame:true},'IOS_FILES_FACT_GEOMETRY_REQUIRED'],[{outsideViewport:true},'IOS_FILES_FACT_GEOMETRY_REQUIRED'],[{horizontal:true},'IOS_FILES_FACT_HORIZONTAL_BOUNDS_REQUIRED'],[{keyboard:true},'IOS_FILES_KEYBOARD_MUST_BE_ABSENT']]){
  const f=fixture(t,options);await assert.rejects(findIosFileFact(f.context,id,'XCUIElementTypeStaticText'),new RegExp(code));assert.equal(f.stats().drags,0);
 }
});

test('an iOS file fact still refuses a late finder and an in-viewport invisible control',async t=>{
 const late=fixture(t,{lateFinder:true});await assert.rejects(findIosFileFact(late.context,id,'XCUIElementTypeStaticText'),/IOS_FILES_FACT_NOT_VISIBLE/);assert.equal(late.stats().drags,0);
 const lateFrame=fixture(t,{lateGeometry:true});await assert.rejects(findIosFileFact(lateFrame.context,id,'XCUIElementTypeStaticText'),/IOS_FILES_FACT_NOT_VISIBLE/);assert.equal(lateFrame.stats().drags,0);
 const hidden=fixture(t,{invisible:true});await assert.rejects(findIosFileFact(hidden.context,id,'XCUIElementTypeStaticText'),/IOS_FILES_FACT_NOT_VISIBLE/);assert.equal(hidden.stats().drags,1);
});

test('an unreachable iOS file fact retains the existing nine measured-drag limit',async t=>{
 const f=fixture(t,{alwaysOffscreen:true});await assert.rejects(findIosFileFact(f.context,id,'XCUIElementTypeStaticText'),/IOS_FILES_FACT_NOT_VISIBLE/);assert.equal(f.stats().drags,9);assert.ok(f.waits.every(x=>x.timeout===1500));
});
