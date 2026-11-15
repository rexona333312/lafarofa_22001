import React from 'react';
import {AbsoluteFill, Easing, Img, Video, interpolate, staticFile} from 'remotion';
import {fitFont} from './Fonts';
import {CurvedGrid} from './NarrativeText';

const clamped = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};
export const phase = (f, start, duration, easing = Easing.out(Easing.cubic)) =>
  interpolate(f, [start, start+duration], [0,1], {...clamped, easing});
export const Media = ({picture, isVideo, style = {}}) => {
  const Component = isVideo ? Video : Img;
  return <Component src={staticFile(picture)} {...(isVideo ? {muted: true, loop: true} : {})}
    style={{width: '100%', height: '100%', objectFit: 'cover', ...style}} />;
};
export const Shade = () => <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, transparent 28%, #0009 100%)'}} />;
export const Marker = ({progress, color = '#d52c3e'}) => <svg viewBox="0 0 1000 100" preserveAspectRatio="none"
  style={{position: 'absolute', inset: 0, width: '100%', height: '100%', clipPath: `inset(0 ${(1-progress)*100}% 0 0)`}}>
  <path d="M0 8 L180 3 L370 9 L580 4 L810 9 L1000 3 L1000 95 L780 99 L580 92 L370 97 L170 92 L0 98Z" fill={color} />
  {[20,45,70,90].map((y,i) => <path key={y} d={`M0 ${y} Q500 ${y-6} 1000 ${y+2}`} stroke={i%2 ? '#ff8990' : '#8e1122'} strokeWidth="2" opacity=".15" />)}
</svg>;

export const ObjectPointer = ({picture, isVideo, p, f, groupFrames}) => {
  const appear = phase(f, p.start_frame, p.arrival_frames);
  const draw = phase(f, p.start_frame, p.line_frames, Easing.linear);
  const x = p.label_point[0]*1920, y = p.label_point[1]*1080;
  const [ax,ay] = p.anchor.map((v,i) => v*(i ? 1080 : 1920));
  const [cx,cy] = p.control_point.map((v,i) => v*(i ? 1080 : 1920));
  const label = p.label.toLowerCase(), size = fitFont(label, 55, 550);
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = `${size}px coolvetica`;
  const width = Math.min(590, Math.max(220, ctx.measureText(label).width+40));
  const direction = ax < x ? -1 : 1;
  const rotation = Math.atan2(ay-cy, ax-cx)*180/Math.PI;
  return <AbsoluteFill>
    <AbsoluteFill style={{transform: `scale(${1+.035*phase(f,0,Math.max(1,groupFrames-1),Easing.linear)})`}}>
      <Media picture={picture} isVideo={isVideo} style={{filter: p.archival ? 'grayscale(1)' : undefined}} />
      <svg viewBox="0 0 1920 1080" style={{position:'absolute', inset:0, width:'100%', height:'100%'}}>
        <path d={`M${x+direction*width/2} ${y} Q${cx} ${cy} ${ax} ${ay}`} stroke="white" strokeWidth="5" fill="none"
          pathLength="1" strokeDasharray="1" strokeDashoffset={1-draw} opacity={draw>0 ? 1 : 0} />
        <path d="M0 0 L-19 -9 L-15 0 L-19 9 Z" fill="white" transform={`translate(${ax},${ay}) rotate(${rotation})`}
          opacity={phase(f,p.start_frame+p.line_frames-4,4)} />
      </svg>
      <div style={{position:'absolute',left:x-width/2,top:y-42,width,height:84,background:'#111',color:'#fff',
        borderRadius:6, display:'flex',alignItems:'center',justifyContent:'center',fontSize:size,opacity:appear,
        transform:`translateY(${(1-appear)*14}px)`, boxShadow:'0 3px 14px #0005'}}>{label}</div>
    </AbsoluteFill>
  </AbsoluteFill>;
};

export const CornerSection = ({picture, isVideo, p, f, groupFrames}) => {
  const right = (p.corner ?? 'top_left').endsWith('right');
  const bottom = (p.corner ?? 'top_left').startsWith('bottom');
  return <AbsoluteFill>
    <AbsoluteFill style={{transform:`scale(${1+.06*phase(f,0,Math.max(1,groupFrames-1),Easing.linear)})`}}>
      <Media picture={picture} isVideo={isVideo} style={{filter: `${p.archival ? 'grayscale(1) ' : ''}brightness(.73)`}} />
    </AbsoluteFill><Shade />
    <div style={{position:'absolute', [right ? 'right' : 'left']:110, [bottom ? 'bottom' : 'top']:85,
      display:'flex',flexDirection:'column',alignItems:right ? 'flex-end' : 'flex-start', gap:8}}>
      {p.lines.map((line,i) => {
        const amount = phase(f,line.start_frame,line.reveal_frames,Easing.linear);
        return <div key={i} style={{position:'relative', padding:'2px 16px 8px',color:'white',
          fontSize:fitFont(line.text.toLowerCase(),66,710),lineHeight:1.1,opacity:amount>0 ? 1 : 0,
          transform:`translateX(${(1-amount)*(right ? 16 : -16)}px)`,clipPath:`inset(0 ${(1-amount)*100}% 0 0)`}}>
          <Marker progress={amount} /><span style={{position:'relative'}}>{line.text.toLowerCase()}</span>
        </div>;
      })}
    </div>
  </AbsoluteFill>;
};

export const DateInterval = ({picture, isVideo, p, f, groupFrames}) => {
  const grid = phase(f,p.grid_start,p.arrival_frames);
  const line = phase(f,p.line_start,p.line_frames,Easing.linear);
  const drift = phase(f,p.grid_start,Math.max(1,groupFrames-p.grid_start-1),Easing.linear);
  const years = [p.from_year,p.to_year], labels=[p.from_label,p.to_label];
  return <AbsoluteFill style={{background:'#050505'}}>
    <AbsoluteFill style={{opacity:1-grid}}><Media picture={picture} isVideo={isVideo} /></AbsoluteFill>
    <AbsoluteFill style={{opacity:grid,transform:`rotate(${drift*1.8}deg) scale(${1+drift*.08})`}}>
      <CurvedGrid />
      <svg viewBox="0 0 1920 1080" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
        <path d="M310 680 L1610 680" stroke="#d8c2bd" strokeWidth="2" pathLength="1" strokeDasharray="1" strokeDashoffset={1-line} />
        {[620,950,1280].map((x,i) => <circle key={x} cx={x} cy={680} r="7" fill="#fff" opacity={phase(f,p.line_start+i*12,10)} style={{filter:'drop-shadow(0 0 10px #ffaabb)'}} />)}
      </svg>
      {[350,1570].map((x,i) => {
        const appear = phase(f,[p.from_start,p.to_start][i],p.arrival_frames);
        return <div key={x} style={{position:'absolute',left:x-240,top:574+(1-appear)*35,width:480,textAlign:'center',opacity:appear}}>
          <div style={{display:'inline-block',padding:'5px 25px',background:'#292929',color:'white',fontSize:48,boxShadow:'0 3px 15px #000'}}>{years[i]}</div>
          <div style={{marginTop:25,color:'white',fontSize:fitFont(labels[i].toLowerCase(),38,460),textShadow:'0 0 12px #c8334d',padding:'7px 10px',background:i ? '#a6621538' : '#a7183838'}}>{labels[i].toLowerCase()}</div>
        </div>;
      })}
      <div style={{position:'absolute',left:600,top:486,width:720,textAlign:'center',fontSize:84,color:'white',
        opacity:phase(f,p.difference_start,p.arrival_frames),transform:`translateY(${(1-phase(f,p.difference_start,p.arrival_frames))*20}px)`}}>
        {p.difference} {p.unit ?? 'years'}
      </div>
    </AbsoluteFill>
  </AbsoluteFill>;
};

// Letters settle from a curved trail, instead of behaving like caption word highlights.
const WaveText = ({text, f, start, duration, size, report = false}) => {
  const letters = [...text.toLowerCase()];
  const settle = Math.min(8,duration*.3), stagger=(duration-settle)/Math.max(1,letters.length-1);
  return <span style={{fontSize:size,whiteSpace:'pre'}}>{letters.map((char,i) => {
    const a=phase(f,start+i*stagger,settle);
    return <span key={i} style={{display:'inline-block',opacity:a,transform:`translate(${(1-a)*(report ? 25 : 0)}px,${(1-a)*(report ? 85 : 24)}px) rotate(${(1-a)*22}deg)`,filter:`blur(${(1-a)*2}px)`}}>{char}</span>;
  })}</span>;
};

export const BulletPanel = ({picture, isVideo, p, f, groupFrames}) => {
  if(p.style==='torn_sidebar') return <TornSidebar picture={picture} isVideo={isVideo} p={p} f={f} groupFrames={groupFrames}/>;
  const arrival=phase(f,p.panel_start,p.arrival_frames);
  const report=p.style==='report', accent=report ? '#efbc64' : '#e84354';
  const right=p.side==='right', x=right ? 1080 : 90;
  const size=p.items.length>4 ? 38 : 42, gap=p.items.length>4 ? 78 : 100;
  const height=Math.max(620,200+p.items.length*gap),top=(1080-height)/2;
  return <AbsoluteFill>
    <AbsoluteFill style={{transform:`scale(${1+.04*phase(f,0,Math.max(1,groupFrames-1),Easing.linear)})`}}>
      <Media picture={picture} isVideo={isVideo} style={{filter:`${p.archival ? 'grayscale(1) ' : ''}brightness(.8)`}} />
    </AbsoluteFill><Shade />
    <div style={{position:'absolute',left:x,top,width:750,height,background:report ? '#1e2c36' : '#242424',
      transform:`translateX(${(1-arrival)*(right ? 260 : -260)}px)`,opacity:arrival,
      clipPath:'polygon(0 1%, 10% 0, 23% 1%, 40% 0, 62% 1%, 80% 0, 100% 1%, 99% 28%, 100% 58%, 99% 80%, 100% 99%, 80% 100%, 60% 99%, 36% 100%, 15% 99%, 0 100%, 1% 69%, 0 35%)',
      boxShadow:'0 16px 40px #0005',padding:'58px 50px',color:'#fff',backgroundImage:'linear-gradient(#ffffff14 1px,transparent 1px),linear-gradient(90deg,#ffffff14 1px,transparent 1px)',backgroundSize:'26px 26px'}}>
      <div style={{position:'relative',height:110}}><WaveText text={p.title} f={f} start={p.panel_start+5} duration={Math.min(24,groupFrames-p.panel_start-6)} size={fitFont(p.title.toLowerCase(),58,650)} report={report} /></div>
      {p.items.map((row,i) => <div key={i} style={{position:'relative',height:gap,display:'flex',alignItems:'center',gap:25}}>
        <div style={{width:15,height:15,flexShrink:0,border:`3px solid ${accent}`,transform:'rotate(45deg)',opacity:phase(f,row.start_frame,6),boxShadow:`0 0 16px ${accent}aa`}} />
        <WaveText text={row.text} f={f} start={row.start_frame} duration={row.reveal_frames} size={fitFont(row.text.toLowerCase(),size,600)} report={report} />
      </div>)}
    </div>
  </AbsoluteFill>;
};

// Clip 234: top-down reveal, fixed torn edge and contextual rows beside the main media.
// Geometry is deterministic so scrubbing, parallel rendering and duration changes agree.
const TornSidebar = ({picture,isVideo,p,f,groupFrames}) => {
  const right=p.side!=='left';
  const open=phase(f,p.panel_start,p.arrival_frames,t=>Math.log1p(31.48*t)/Math.log1p(31.48));
  const title=phase(f,p.title_start,p.title_frames);
  const count=p.items.length, gap=Math.min(166,620/count), rowHeight=gap-24;
  const edge=Array.from({length:271},(_,i)=>[1100+i*(1.25/3)+Math.sin(i*1.8)*3.2+Math.sin(i*.63)*2.4+Math.sin(i*.18)*5,i*4]);
  const path=edge.map(([x,y],i)=>`${i?'L':'M'}${x} ${y}`).join(' ');
  const body=path+' L1920 1080 L1920 0 Z';
  const stripe=path+' '+[...edge].reverse().map(([x,y])=>`L${x-18-Math.sin(y*.12)*4} ${y}`).join(' ')+' Z';
  return <AbsoluteFill style={{background:'#131218'}}>
    <AbsoluteFill style={{transform:`scale(${1+.055*phase(f,0,Math.max(1,groupFrames-1),Easing.linear)})`,transformOrigin:right?'left center':'right center'}}>
      <Media picture={picture} isVideo={isVideo} style={{filter:`${p.archival?'grayscale(1) ':''}brightness(.78)`}}/>
    </AbsoluteFill><Shade/>
    <AbsoluteFill style={{clipPath:`inset(0 0 ${(1-open)*100}% 0)`}}>
      <svg viewBox="0 0 1920 1080" style={{position:'absolute',inset:0,width:'100%',height:'100%',transform:right?undefined:'scaleX(-1)'}}>
        <path d={body} fill="#131218"/><path d={stripe} fill="#ef244a"/>
      </svg>
    </AbsoluteFill>
    <div style={{position:'absolute',left:right?1278:55,top:190,width:586,color:'white'}}>
      <div style={{height:174,fontSize:fitFont(p.title.toLowerCase(),72,1120),lineHeight:1.08,opacity:title,
        transform:`translateY(${(1-title)*18}px)`,paddingRight:15}}>{p.title.toLowerCase()}</div>
      {p.items.map((row,i)=>{
        const reveal=phase(f,row.start_frame,row.reveal_frames,Easing.linear);
        const settle=phase(f,row.start_frame,Math.max(1,Math.min(12,row.reveal_frames)));
        const size=fitFont(row.text.toLowerCase(),count>4?27:count>3?34:46,1020);
        return <div key={i} style={{position:'relative',height:rowHeight,marginBottom:24,padding:count>4?'9px 22px 9px 44px':'15px 22px 15px 44px',
          fontSize:size,lineHeight:1.12,opacity:settle,transform:`translateX(${(1-settle)*(right?20:-20)}px)`}}>
          <AbsoluteFill style={{background:'#26262f',clipPath:`polygon(0 1%,23% 0,51% 2%,78% 0,99% 2%,100% 96%,77% 100%,48% 98%,21% 100%,0 98%)`,
            transform:`scaleX(${reveal})`,transformOrigin:'left center'}}/>
          <span style={{position:'absolute',left:19,top:24,width:9,height:9,borderRadius:'50%',background:'#ef244a',boxShadow:'0 0 8px #ef244a55'}}/>
          <div style={{position:'relative',clipPath:`inset(0 ${(1-reveal)*100}% 0 0)`}}>{row.text.toLowerCase()}</div>
        </div>;
      })}
    </div>
  </AbsoluteFill>;
};

export const EchoStatement = ({background, p, f, groupFrames}) => {
  const arrival=phase(f,p.start_frame,p.arrival_frames);
  const camera=phase(f,p.start_frame,p.camera_frames,Easing.out(Easing.cubic));
  const scale=p.camera_scale_start+(p.camera_scale_end-p.camera_scale_start)*camera;
  const echo=p.echo.toLowerCase(), words=p.text.toLowerCase().split(/\s+/), split=Math.ceil(words.length*.65);
  const lines=[words.slice(0,split).join(' '),words.slice(split).join(' ')].filter(Boolean);
  const size=Math.min(...lines.map(line => fitFont(line,122,1670)));
  return <AbsoluteFill style={{background:'#151212'}}>
    <AbsoluteFill style={{transform:`scale(${scale})`,filter:`blur(${(1-arrival)*13}px)`}}>
      <div style={{position:'absolute',left:-210,top:-150,width:2450,color:'#923737',fontSize:200,lineHeight:1.05,opacity:.65}}>
        {Array.from({length:7},(_,i) => <div key={i} style={{whiteSpace:'nowrap',transform:`translateX(${i%2 ? -160 : 0}px)`}}>{Array(4).fill(echo).join(' · ')}</div>)}
      </div>
      <Img src={staticFile(background)} style={{width:'100%',height:'100%',objectFit:'cover',mixBlendMode:'screen',opacity:.09}} />
      <Shade />
      <AbsoluteFill style={{alignItems:'center',justifyContent:'center'}}>
        <div style={{textAlign:'center',fontSize:size,lineHeight:1.15,color:'white',textShadow:'0 5px 20px #0008',opacity:1}}>
          {lines.map((line,i) => <div key={i}>{line}</div>)}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  </AbsoluteFill>;
};

export const nextComponents = {object_pointer:ObjectPointer,corner_section:CornerSection,
  date_interval:DateInterval,bullet_panel:BulletPanel,echo_statement:EchoStatement};
