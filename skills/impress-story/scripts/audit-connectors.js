/* Browser expression: evaluate after the page's presentation has initialized.
   Optional window.connectorAuditOptions can adapt selectors and local-unit tolerances.
   Does not mutate presentation layout or navigate the page. */
(async () => {
  const o = Object.assign({sceneSelector:'[data-scene]',connectorSelector:'.connector',shaftSelector:'.connector-shaft',headSelector:'.connector-head',textSelector:'text',clearance:8,sampleSpacing:2,minAlignment:0.995,maxHeadRatio:0.4,maxSamples:250000},window.connectorAuditOptions||{});
  const invalid=[],collisions=[],malformedHeads=[],connectors=[...document.querySelectorAll(o.connectorSelector)];
  const result={ok:false,connectors:connectors.length,checked:0,clearance:o.clearance,sampleSpacing:o.sampleSpacing,collisions,malformedHeads,invalid};
  if(!(o.clearance>=0)||!(o.sampleSpacing>0)||!Number.isFinite(o.sampleSpacing)){invalid.push({reason:'Invalid spacing or clearance'});return result;}
  if(!document.fonts){invalid.push({reason:'Font readiness API unavailable'});return result;}
  await document.fonts.ready;
  if(!connectors.length){invalid.push({reason:'No connectors matched; inspection did not run'});return result;}
  let samples=0;
  for(const [index,connector] of connectors.entries()){
    const scene=connector.closest(o.sceneSelector),shaft=connector.querySelector(o.shaftSelector),head=connector.querySelector(o.headSelector);
    const id={index,scene:scene?.getAttribute('data-scene')||scene?.id||null};
    if(!scene||!shaft||!head){invalid.push({...id,reason:'Missing scene, shaft, or V-shaped arrowhead'});continue;}
    const textBoxes=[...scene.querySelectorAll(o.textSelector)].filter(n=>n.textContent.trim()).map(node=>{
      try{
        const box=node.getBBox(),matrix=scene.getCTM().inverse().multiply(node.getCTM());
        const corners=[[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(matrix));
        const xs=corners.map(p=>p.x),ys=corners.map(p=>p.y);
        if(!box.width||!box.height||corners.some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y)))throw Error('Missing text geometry');
        return {text:node.textContent,x:Math.min(...xs),y:Math.min(...ys),r:Math.max(...xs),b:Math.max(...ys)};
      }catch(e){invalid.push({...id,reason:'Text measurement failed',text:node.textContent});return null;}
    }).filter(Boolean);
    if(!textBoxes.length){invalid.push({...id,reason:'No measurable text; coverage must be checked manually'});continue;}
    try{
      const n=shaft.getTotalLength(),hn=head.getTotalLength();
      if(!(n>0.01&&hn>0.01))throw Error('Degenerate shaft or arrowhead');
      const tip=shaft.getPointAtLength(n),near=shaft.getPointAtLength(Math.max(0,n-Math.min(.1,n/10)));
      const h0=head.getPointAtLength(0),h1=head.getPointAtLength(hn),mid=head.getPointAtLength(hn/2);
      const hm=shaft.getCTM().inverse().multiply(head.getCTM());
      const a=new DOMPoint(h0.x,h0.y).matrixTransform(hm),b=new DOMPoint(h1.x,h1.y).matrixTransform(hm),v=new DOMPoint(mid.x,mid.y).matrixTransform(hm);
      const dx=tip.x-(a.x+b.x)/2,dy=tip.y-(a.y+b.y)/2,tx=tip.x-near.x,ty=tip.y-near.y;
      const alignment=(dx*tx+dy*ty)/(Math.hypot(dx,dy)*Math.hypot(tx,ty)),headRatio=Math.hypot(dx,dy)/n;
      if(!Number.isFinite(alignment)||alignment<o.minAlignment||headRatio>o.maxHeadRatio||Math.hypot(v.x-tip.x,v.y-tip.y)>Math.max(1,n*.001))malformedHeads.push({...id,alignment,headRatio,reason:'Head direction, proportion, or tip does not match shaft'});
      for(const path of [shaft,head]){
        const length=path.getTotalLength(),matrix=scene.getCTM().inverse().multiply(path.getCTM()),hits=new Set();
        const count=Math.ceil(length/o.sampleSpacing)+1;
        samples+=count;if(samples>o.maxSamples)throw Error('Sampling budget exceeded; audit incomplete');
        for(let k=0;k<=count;k++){
          const p=path.getPointAtLength(Math.min(k*o.sampleSpacing,length)),q=new DOMPoint(p.x,p.y).matrixTransform(matrix);
          if(!Number.isFinite(q.x)||!Number.isFinite(q.y))throw Error('Non-finite transform');
          for(const t of textBoxes)if(q.x>t.x-o.clearance&&q.x<t.r+o.clearance&&q.y>t.y-o.clearance&&q.y<t.b+o.clearance)hits.add(t.text);
        }
        if(hits.size)collisions.push({...id,part:path===shaft?'shaft':'head',text:[...hits]});
      }
      result.checked++;
    }catch(e){invalid.push({...id,reason:String(e.message||e)});}
  }
  result.ok=result.checked===connectors.length&&!invalid.length&&!collisions.length&&!malformedHeads.length;
  return result;
})()
