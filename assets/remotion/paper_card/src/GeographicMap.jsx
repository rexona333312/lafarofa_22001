import React,{useEffect,useRef,useState} from 'react';
import {AbsoluteFill,useCurrentFrame,delayRender,continueRender,cancelRender,interpolate,Easing,staticFile} from 'remotion';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {useCoolvetica} from './Fonts';

const progress=(f,r)=>interpolate(f,[r.start_frame??0,(r.start_frame??0)+(r.draw_frames??24)],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
const fc=geometry=>({type:'Feature',properties:{},geometry});
const slice=(points,p)=>{
  const lengths=points.slice(1).map((v,i)=>Math.hypot(v[0]-points[i][0],v[1]-points[i][1]));
  let left=lengths.reduce((a,b)=>a+b,0)*p,out=[points[0]];
  for(let i=0;i<lengths.length;i++){
    const t=Math.min(1,left/Math.max(lengths[i],1e-12));
    out.push(points[i].map((v,k)=>v+(points[i+1][k]-v)*t));
    if(t<1)break;left-=lengths[i];
  }
  return out.length===1?[...out,out[0]]:out;
};

export const GeographicMap=({geo:p,tileBase})=>{
  useCoolvetica();
  const f=useCurrentFrame(),container=useRef(),[map,setMap]=useState(),[labels,setLabels]=useState([]);
  const [loading]=useState(()=>delayRender('Loading geographical map',{timeoutInMilliseconds:120000}));
  useEffect(()=>{
    maplibregl.setWorkerUrl(staticFile('maplibre-gl-worker.mjs'));
    const camera=p.camera[0], terrain=p.mode!=='flat';
    const instance=new maplibregl.Map({container:container.current,interactive:false,attributionControl:false,
      center:camera.center,zoom:camera.zoom??6,pitch:terrain?(camera.pitch??0):0,bearing:camera.bearing??0,
      fadeDuration:0,renderWorldCopies:false,maxPitch:65,canvasContextAttributes:{preserveDrawingBuffer:true},
      style:{version:8,transition:{duration:0,delay:0},sources:{
        satellite:{type:'raster',tiles:[`${tileBase}satellite/{z}/{x}/{y}`],tileSize:256,maxzoom:8},
        ...(terrain?{dem:{type:'raster-dem',tiles:[`${tileBase}terrain/{z}/{x}/{y}`],tileSize:256,encoding:'terrarium',maxzoom:12}}:{}),
        borders:{type:'geojson',data:p.countries}},
        layers:[{id:'satellite',type:'raster',source:'satellite',paint:{'raster-fade-duration':0,'raster-brightness-max':.85,'raster-saturation':-.25}},
          {id:'borders',type:'line',source:'borders',paint:{'line-color':'#e5e1cc','line-opacity':.4,'line-width':1}}],
        ...(terrain?{terrain:{source:'dem',exaggeration:1.35}}:{})}});
    instance.on('error',event=>cancelRender(new Error(`Map data unavailable: ${event.error?.message??'tile error'}`)));
    instance.on('load',()=>{
      (p.highlights??[]).forEach((r,i)=>{
        instance.addSource(`area${i}`,{type:'geojson',data:p.features[i]});
        instance.addLayer({id:`fill${i}`,type:'fill',source:`area${i}`,paint:{'fill-color':r.color??'#e5c65f','fill-opacity':0}});
        instance.addLayer({id:`edge${i}`,type:'line',source:`area${i}`,paint:{'line-color':r.color??'#e5c65f','line-width':2.5,'line-opacity':0}});
      });
      (p.routes??[]).forEach((r,i)=>{
        instance.addSource(`route${i}`,{type:'geojson',data:fc({type:'LineString',coordinates:[r.points[0],r.points[0]]})});
        instance.addLayer({id:`line${i}`,type:'line',source:`route${i}`,layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':r.color??'#e54e46','line-width':5}});
      });
      (p.regions??[]).forEach((r,i)=>{
        instance.addSource(`region${i}`,{type:'geojson',data:fc({type:'Polygon',coordinates:[[...r.points,r.points[0]]]})});
        instance.addLayer({id:`regionfill${i}`,type:'fill',source:`region${i}`,paint:{'fill-color':r.color??'#e54e46','fill-opacity':0}});
        instance.addLayer({id:`regionedge${i}`,type:'line',source:`region${i}`,paint:{'line-color':r.color??'#e54e46','line-width':3,'line-opacity':0}});
      });
      instance.once('idle',()=>{setMap(instance);continueRender(loading);});instance.triggerRepaint();
    });
    // Remotion owns this page's lifetime; map.remove() can clear a pending frame.
  },[loading,p,tileBase]);
  useEffect(()=>{
    if(!map)return;
    const handle=delayRender('Updating map frame',{timeoutInMilliseconds:120000});
    const cameras=p.camera;
    let i=0;while(i<cameras.length-2&&f>=cameras[i+1].frame)i++;
    const a=cameras[i],b=cameras[i+1],t=interpolate(f,[a.frame,b.frame],[0,1],{easing:Easing.inOut(Easing.cubic),extrapolateLeft:'clamp',extrapolateRight:'clamp'});
    const mix=(key,def)=> (a[key]??def)+((b[key]??def)-(a[key]??def))*t;
    map.jumpTo({center:a.center.map((v,k)=>v+(b.center[k]-v)*t),zoom:mix('zoom',6),bearing:mix('bearing',0),pitch:p.mode==='flat'?0:mix('pitch',0)});
    (p.highlights??[]).forEach((r,j)=>{const q=progress(f,r);map.setPaintProperty(`fill${j}`,'fill-opacity',q*.28);map.setPaintProperty(`edge${j}`,'line-opacity',q);});
    (p.regions??[]).forEach((r,j)=>{const q=progress(f,r);map.setPaintProperty(`regionfill${j}`,'fill-opacity',q*.28);map.setPaintProperty(`regionedge${j}`,'line-opacity',q);});
    (p.routes??[]).forEach((r,j)=>map.getSource(`route${j}`).setData(fc({type:'LineString',coordinates:slice(r.points,progress(f,r))})));
    map.once('idle',()=>{
      const rows=[...(p.markers??[]).map(r=>({...r,point:true})),...(p.routes??[]).map(r=>({...r,position:r.points.at(-1)})),
        ...(p.regions??[]).map(r=>({...r,position:[0,1].map(k=>r.points.reduce((a,v)=>a+v[k],0)/r.points.length)}))];
      setLabels(rows.map(r=>({...r,xy:map.project(r.position),opacity:progress(f,r)})));
      requestAnimationFrame(()=>continueRender(handle));
    });
    map.triggerRepaint();
  },[f,map,p]);
  return <AbsoluteFill style={{background:'#172120',fontFamily:'coolvetica',overflow:'hidden'}}>
    <AbsoluteFill ref={container}/>
    <AbsoluteFill style={{pointerEvents:'none',background:'radial-gradient(ellipse at center,transparent 40%,#080b0d88)'}}/>
    {labels.map((r,i)=><div key={i} style={{position:'absolute',left:r.xy.x,top:r.xy.y,opacity:r.opacity,transform:'translate(-50%,-50%)',textAlign:'center'}}>
      {r.point&&<div style={{margin:'0 auto 8px',width:12,height:12,background:r.color??'#e5c65f',border:'2px solid white',borderRadius:'50%'}}/>}
      <span style={{display:'inline-block',whiteSpace:'nowrap',padding:'8px 16px',background:'#11191be8',color:'#f4ecdc',fontSize:28}}>{r.label}</span>
    </div>)}
    <div style={{position:'absolute',top:70,left:90,right:90,color:'#f0e9da',textShadow:'0 3px 9px #000'}}>
      {p.date&&<div style={{fontSize:29,letterSpacing:5,color:'#e86152',marginBottom:18}}>{p.date}</div>}
      <div style={{fontSize:46,letterSpacing:2}}>{p.title}</div>
    </div>
    <div style={{position:'absolute',bottom:12,left:20,fontSize:16,color:'#e5e1d8',background:'#07100eb8',padding:'5px 10px'}}>Imagery: NASA Blue Marble / GIBS (500 m) | Terrain: Mapzen / source agencies | Boundaries: Natural Earth (modern)</div>
  </AbsoluteFill>;
};
