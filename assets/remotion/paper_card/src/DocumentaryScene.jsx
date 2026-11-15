import React from 'react';
import {AbsoluteFill, Img, Video, staticFile, useCurrentFrame, useVideoConfig, interpolate, Easing} from 'remotion';
import {useCoolvetica,fitFont} from './Fonts';

const progress = (f,s,d) => interpolate(f,[s,s+d],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.out(Easing.cubic)});
const ink='#eee9df', red='#d54c43';
const tag={background:'#e8e2d6',color:'#17191b',padding:'12px 22px',display:'inline-block'};

export const DocumentaryScene=({variant,picture,background,isVideo,pictureWidth,pictureHeight,motionParams:p})=>{
  useCoolvetica();
  const f=useCurrentFrame(), {width,height}=useVideoConfig();
  const a=progress(f,p.start_frame,p.arrival_frames);
  const Media=isVideo?Video:Img;
  const mediaStyle={width:'100%',height:'100%',objectFit:'contain'};
  const media=<Media src={staticFile(picture)} muted style={mediaStyle}/>;
  let content;
  if(variant==='stat_callout'){
    const overlay=p.layout==='overlay';
    const mediaArrival=progress(f,0,p.arrival_frames);
    content=<>
      {overlay?<AbsoluteFill>{media}</AbsoluteFill>:<div style={{position:'absolute',left:130,top:210,width:820,height:640,border:'15px solid #f3eee5',transform:`rotate(-2deg) scale(${.94+.06*mediaArrival})`,opacity:mediaArrival,boxShadow:'0 30px 70px #0008'}}>{media}</div>}
      {overlay&&<AbsoluteFill style={{background:'linear-gradient(transparent 30%,#080b0fd9)'}}/>}
      <div style={{position:'absolute',left:overlay?160:1060,top:overlay?650:380,width:overlay?1580:730,opacity:a,transform:`translateY(${30*(1-a)}px)`}}>
        <div style={{fontSize:Math.min(160,1150/p.value.length),color:ink,lineHeight:1.08,fontVariantNumeric:'tabular-nums'}}>{p.value}</div>
        <div style={{fontSize:44,color:'#ddd5c9',marginTop:28,maxWidth:overlay?1400:680}}>{p.label}</div>
      </div>
    </>;
  }else if(variant==='portrait_profile'){
    content=<>
      <div style={{position:'absolute',left:150,top:150,width:690,height:760,padding:18,background:'#f3eee5',boxSizing:'border-box',transform:`translateY(${40*(1-a)}px) rotate(-2deg)`,opacity:a,boxShadow:'0 30px 70px #0008'}}>{media}</div>
      <div style={{position:'absolute',left:1000,top:330,width:750,opacity:a,transform:`translateX(${40*(1-a)}px)`}}>
        <div style={{...tag,fontSize:Math.max(36,Math.min(64,1200/p.name.length))}}>{p.name}</div>
        <div style={{marginTop:42,fontSize:44,lineHeight:1.4,color:ink}}>{p.description}</div>
      </div>
    </>;
  }else if(variant==='data_comparison'){
    const max=Math.max(...p.items.map(r=>r.value));
    content=<>
      <AbsoluteFill style={{backgroundImage:'linear-gradient(#b6c3c512 1px,transparent 1px),linear-gradient(90deg,#b6c3c512 1px,transparent 1px)',backgroundSize:'68px 68px'}}/>
      <div style={{position:'absolute',left:150,top:95,right:150,fontSize:fitFont(p.title,55,1300),color:ink,opacity:a}}>{p.title}<span style={{float:'right',fontSize:28,opacity:.6}}>{p.unit}</span></div>
      {p.items.map((r,i)=>{
        const b=progress(f,r.start_frame,p.arrival_frames), y=280+i*(640/p.items.length);
        return <div key={i} style={{position:'absolute',left:150,right:150,top:y,opacity:b}}>
          <div style={{fontSize:34,color:'#dad3c8',marginBottom:14}}>{r.label}</div>
          <div style={{display:'flex',alignItems:'center',gap:30}}>
            <div style={{height:52,width:Math.max(2,r.value/max*1240*b),background:i%2?'#de945e':red,boxShadow:'0 5px 20px #0004'}}/>
            <div style={{fontSize:fitFont(r.display,39,320),color:ink,whiteSpace:'nowrap'}}>{r.display}</div>
          </div>
        </div>;
      })}
    </>;
  }else{
    const [x,y,w,h]=p.focus_rect;
    const z=progress(f,p.zoom_start_frame,p.arrival_frames), mark=progress(f,p.highlight_start_frame,p.arrival_frames);
    const scale=Math.min(1540/pictureWidth,820/pictureHeight);
    const iw=pictureWidth*scale,ih=pictureHeight*scale;
    const target=Math.min(3,Math.max(1,Math.min(1300/(iw*w),600/(ih*h))));
    const zoom=1+(target-1)*z,tx=(.5-(x+w/2))*iw*zoom*z,ty=(.5-(y+h/2))*ih*zoom*z;
    content=<>
      <AbsoluteFill style={{alignItems:'center',justifyContent:'center',opacity:a}}>
        <div style={{position:'relative',width:iw,height:ih,transform:`translate(${tx}px,${ty}px) scale(${zoom})`,boxShadow:'0 22px 70px #0009'}}>
          <Img src={staticFile(picture)} style={{width:'100%',height:'100%'}}/>
          <svg viewBox={`0 0 ${iw} ${ih}`} style={{position:'absolute',inset:0,width:'100%',height:'100%',overflow:'visible'}}>
            {p.mark==='circle'?<ellipse cx={(x+w/2)*iw} cy={(y+h/2)*ih} rx={w*iw/2+5} ry={h*ih/2+5} fill="none" stroke={red} strokeWidth={4/zoom} pathLength="1" strokeDasharray="1" strokeDashoffset={1-mark} opacity={mark>0?1:0}/>:<rect x={x*iw} y={y*ih} width={w*iw*mark} height={h*ih} fill="#ffffff" opacity=".4"/>}
          </svg>
        </div>
      </AbsoluteFill>
      {p.caption&&<div style={{position:'absolute',left:150,right:150,bottom:55,textAlign:'center',fontSize:34,opacity:mark}}><span style={tag}>{p.caption}</span></div>}
    </>;
  }
  return <AbsoluteFill style={{background:'#171b1d',overflow:'hidden',fontFamily:'coolvetica',color:ink}}>
    {background&&<Img src={staticFile(background)} style={{width:'100%',height:'100%',objectFit:'cover',opacity:.055,filter:'grayscale(1)'}}/>}
    {content}
  </AbsoluteFill>;
};
