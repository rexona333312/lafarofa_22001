import React from 'react';
import {AbsoluteFill, Easing} from 'remotion';
import {fitFont} from './Fonts';
import {phase, Media, Shade, Marker} from './NextReferenceScene';

const TextHighlightSplit = ({picture,isVideo,p,f}) => {
  const reveal=phase(f,p.text_start,p.arrival_frames);
  const mark=phase(f,p.highlight_start,p.highlight_frames,Easing.linear);
  const split=phase(f,p.split_start,p.split_frames,Easing.out(Easing.cubic));
  const words=p.text.toLowerCase().split(/\s+/), middle=Math.ceil(words.length/2);
  const lines=[words.slice(0,middle).join(' '),words.slice(middle).join(' ')].filter(Boolean);
  const size=Math.min(...lines.map(t=>fitFont(t,150,1460)));
  return <AbsoluteFill style={{background:'#181818'}}>
    <AbsoluteFill style={{width:1920-960*split,alignItems:'center',justifyContent:'center',overflow:'hidden'}}>
      <div style={{width:1540,flexShrink:0,textAlign:'center',opacity:reveal,
        transform:`translateY(${(1-reveal)*35}px) scale(${1-.47*split})`}}>
        {lines.map((line,i)=><div key={i} style={{position:'relative',display:'table',margin:'14px auto',padding:'8px 22px',color:'#fff',
          fontSize:size,lineHeight:1.1,textShadow:'0 4px 8px #000, 0 0 3px #000',background:'#222'}}>
          <Marker progress={mark} color="#c8a51c"/><span style={{position:'relative'}}>{line}</span>
        </div>)}
        {p.caption && <div style={{marginTop:55,color:'white',fontSize:64,opacity:phase(f,p.caption_start,p.caption_frames)}}>{p.caption.toLowerCase()}</div>}
      </div>
    </AbsoluteFill>
    <div style={{position:'absolute',left:1920-960*split,top:0,width:960,height:1080,overflow:'hidden',borderLeft:'5px solid #d92f43'}}>
      <Media picture={picture} isVideo={isVideo} style={{filter:p.archival?'grayscale(1)':undefined}}/>
    </div>
  </AbsoluteFill>;
};

const SplitVerdict = ({left,right,labels,p,f}) => {
  const divide=phase(f,p.split_start,p.split_frames,Easing.inOut(Easing.cubic));
  const centers=[960-442*divide,1402];
  return <AbsoluteFill style={{background:'radial-gradient(ellipse at center,#17110c,#080604 75%)'}}>
    <div style={{position:'absolute',left:1920-960*divide,top:0,width:960,height:1080,
      background:'radial-gradient(ellipse at center,#6b171b,#21090b 90%)'}}/>
    {[left,right].map((picture,i)=>{
      const arrival=phase(f,i?p.right_start:p.left_start,i?p.right_frames:p.left_frames,Easing.inOut(Easing.cubic));
      const opacity=phase(f,i?p.right_start:p.left_start,4);
      const typing=phase(f,i?p.right_label_start:p.left_label_start,i?p.right_label_frames:p.label_frames,Easing.linear);
      const label=labels[i].toLowerCase();
      return <React.Fragment key={i}>
        <div style={{position:'absolute',left:centers[i]-330,top:275,width:660,height:480,overflow:'hidden',borderRadius:28,
          opacity,transform:`scale(${.225+.775*arrival})`,boxShadow:'0 20px 40px #0005'}}>
          <Media picture={picture} style={{filter:p.archival?'grayscale(1)':undefined}}/>
        </div>
        <div style={{position:'absolute',top:815,left:centers[i]-380,width:760,textAlign:'center',color:'white',
          fontSize:fitFont(label,48,700),letterSpacing:2,opacity:typing>0?1:0}}>
          {label.slice(0,Math.floor(label.length*typing))}
        </div>
      </React.Fragment>;
    })}
  </AbsoluteFill>;
};

const DetailCallouts = ({picture,isVideo,p,f}) => {
  const arrival=phase(f,p.media_start,p.arrival_frames);
  return <AbsoluteFill style={{background:'#160a0c'}}>
    <AbsoluteFill style={{opacity:arrival,transform:`scale(${.88+.12*arrival})`}}>
      <Media picture={picture} isVideo={isVideo} style={{filter:`${p.archival?'grayscale(1) ':''}brightness(.72)`}}/>
      <Shade/>
      <svg viewBox="0 0 1920 1080" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
        {p.annotations.map((a,i)=>{
          const line=phase(f,a.start_frame,a.draw_frames,Easing.linear);
          const [ax,ay]=a.anchor.map((v,n)=>v*(n?1080:1920));
          const [lx,ly]=a.label_point.map((v,n)=>v*(n?1080:1920));
          const tagFrames=Math.min(8,a.draw_frames);
          const tag=phase(f,a.start_frame+a.draw_frames-tagFrames,tagFrames);
          const label=a.label.toLowerCase(),size=fitFont(label,44,460),width=Math.min(500,Math.max(180,label.length*size*.5+44));
          const edge=lx+(ax>lx?width/2:-width/2);
          return <g key={i}>
            <circle cx={ax} cy={ay} r={6} fill="#fff" opacity={line} style={{filter:'drop-shadow(0 0 12px #ffb390)'}}/>
            <path d={`M${ax} ${ay} L${ax} ${ly} L${edge} ${ly}`} fill="none" stroke="#ffb4a7" strokeWidth="3"
              pathLength="1" strokeDasharray="1" strokeDashoffset={1-line} opacity={line>0?1:0}/>
            <g opacity={tag} transform={`translate(${lx},${ly+(1-tag)*12})`}>
              <rect x={-width/2} y={-36} width={width} height={72} rx="17" fill="#08090d" stroke="#c9c9c9" strokeWidth="2"/>
              <text fill="#fff" fontSize={size} fontFamily="coolvetica" textAnchor="middle" dominantBaseline="central">{label}</text>
            </g>
          </g>;
        })}
      </svg>
    </AbsoluteFill>
  </AbsoluteFill>;
};

const LowerThirdContrast = ({picture,isVideo,p,f}) => {
  const right=p.side==='right';
  const row=p.segments.map(a=>a.text.toLowerCase()).join(' ');
  const size=fitFont(row,67,1650);
  const header=phase(f,p.heading_start,p.arrival_frames,Easing.linear);
  return <AbsoluteFill>
    <Media picture={picture} isVideo={isVideo} style={{filter:`${p.archival?'grayscale(1) ':''}brightness(.72)`}}/>
    <AbsoluteFill style={{background:'linear-gradient(transparent 48%,#000b 100%)'}}/>
    <div style={{position:'absolute',bottom:140,[right?'right':'left']:90,color:'white',maxWidth:1740}}>
      <div style={{fontSize:fitFont(p.heading.toLowerCase(),74,1660),marginBottom:18,opacity:header>0?1:0,
        clipPath:`inset(0 ${(1-header)*100}% 0 0)`,textShadow:'0 4px 10px #000'}}>{p.heading.toLowerCase()}</div>
      <div style={{display:'flex',gap:12,alignItems:'center',flexWrap:'wrap'}}>
        {p.segments.map((a,i)=>{
          const show=phase(f,a.start_frame,a.reveal_frames,Easing.linear);
          return <div key={i} style={{position:'relative',padding:a.highlight?'8px 14px':'8px 0',fontSize:size,
            opacity:show>0?1:0,clipPath:`inset(0 ${(1-show)*100}% 0 0)`,fontStyle:a.highlight?'italic':'normal',textShadow:'0 3px 5px #0008'}}>
            {a.highlight&&<Marker progress={show}/>}
            <span style={{position:'relative'}}>{a.text.toLowerCase()}</span>
          </div>;
        })}
      </div>
    </div>
  </AbsoluteFill>;
};

export const lateComponents={detail_callouts:DetailCallouts,text_highlight_split:TextHighlightSplit,
  split_verdict:SplitVerdict,lower_third_contrast:LowerThirdContrast};
