import React from 'react';
import {AbsoluteFill, Img, staticFile, interpolate, Easing, useCurrentFrame, useVideoConfig} from 'remotion';
import {useCoolvetica} from './Fonts';

const STYLES = {
  paper: {background: '#f0f0ed', border: '#ffffff', ink: '#222222', radius: 42},
  editorial: {background: '#eee8dd', border: '#fffdf8', ink: '#34312b', radius: 4},
  dark: {background: '#111820', border: '#263341', ink: '#f3f5f7', radius: 22},
  film: {background: '#d7c8b1', border: '#27251f', ink: '#27251f', radius: 8},
};

export const PhotoCarousel = props => {
  useCoolvetica();
  const frame = useCurrentFrame() + props.frameOffset;
  const {width, height} = useVideoConfig();
  if(props.style==='board'){
    const count=props.starts.length,columns=count<=3?count:3,rows=Math.ceil(count/columns);
    const cw=Math.min(650,(width-220)/columns-36),ch=rows===1?560:365;
    return <AbsoluteFill style={{background:'#191d20',fontFamily:'coolvetica',overflow:'hidden'}}>
      <Img src={staticFile(props.background)} style={{width:'100%',height:'100%',objectFit:'cover',opacity:.06,filter:'grayscale(1)'}}/>
      {props.starts.map((s,i)=>{
        const a=interpolate(frame,[s,s+18],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.out(Easing.cubic)});
        const row=Math.floor(i/columns),colsInRow=Math.min(columns,count-row*columns);
        return <div key={i} style={{position:'absolute',left:(width-colsInRow*(cw+36))/2+(i%columns)*(cw+36),top:(height-rows*(ch+68))/2+row*(ch+68),width:cw,opacity:a,transform:`translateY(${45*(1-a)}px) rotate(${i%2?1.2:-1.2}deg)`}}>
          <div style={{height:ch,border:'14px solid #eee9df',boxSizing:'border-box',background:'#eee9df',boxShadow:'0 20px 50px #0008'}}><Img src={staticFile(props[`picture${i}`])} style={{width:'100%',height:'100%',objectFit:'contain',filter:props.archival?'grayscale(1)':undefined}}/></div>
          <div style={{textAlign:'center',marginTop:18,color:'#ede5d8',fontSize:32,lineHeight:1.2}}>{props.captions[i]}</div>
        </div>;
      })}
    </AbsoluteFill>;
  }
  const config = STYLES[props.style];
  const opts = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)};
  let position = 0;
  props.starts.slice(1).forEach(start => {position += interpolate(frame, [start, start+21], [0, 1], opts);});
  const entrance = interpolate(frame, [0, 21], [0, 1], {...opts, easing: Easing.out(Easing.cubic)});
  const cardWidth = width * .86, cardHeight = height * .79, gap = width * .1;
  const index = Math.min(props.starts.length-1, Math.floor(position+.5));
  return <AbsoluteFill style={{background: config.background, overflow: 'hidden', fontFamily: 'coolvetica'}}>
    {props.style === 'paper' && <>
      <Img src={staticFile(props.background)} style={{width: '100%', height: '100%', objectFit: 'cover', opacity: .13, filter: 'grayscale(1)'}} />
      <AbsoluteFill style={{backgroundImage: 'linear-gradient(#91918d55 1px, transparent 1px), linear-gradient(90deg, #91918d55 1px, transparent 1px)', backgroundSize: '42px 42px'}} />
    </>}
    {props.style === 'editorial' && <div style={{position: 'absolute', top: '3%', left: '7%', right: '7%', color: config.ink,
      display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #9c958a', paddingBottom: 12, fontSize: 28}}>
      <span>{(props.captions[index] ?? '').toLowerCase()}</span><span>{String(index+1).padStart(2, '0')} / {String(props.starts.length).padStart(2, '0')}</span>
    </div>}
    {props.style === 'dark' && <div style={{position: 'absolute', bottom: height*.035, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 12}}>
      {props.starts.map((_, i) => <div key={i} style={{height: 4, width: i === index ? 48 : 24,
        borderRadius: 4, background: i === index ? '#f2f6fc' : '#43515f'}} />)}
    </div>}
    {props.starts.map((_, i) => {
      const x = (width-cardWidth)/2 + (i-position)*(cardWidth+gap);
      const y = height*.12 + (1-entrance)*height;
      return <div key={i} style={{position: 'absolute', left: x, top: y, width: cardWidth, height: cardHeight,
        background: config.border, padding: props.style === 'film' ? '30px 16px 38px' : 12, boxSizing: 'border-box',
        borderRadius: config.radius, boxShadow: props.style === 'dark' ? '0 28px 70px #0008' : '0 14px 38px #0004'}}>
        <Img src={staticFile(props[`picture${i}`])} style={{width: '100%', height: '100%', objectFit: 'contain',
          borderRadius: Math.max(0, config.radius-10), filter: props.archival ? 'grayscale(1)' : undefined}} />
        {props.style === 'film' && <>
          {[0, 1].map(row => <div key={row} style={{position: 'absolute', top: row ? undefined : 8, bottom: row ? 12 : undefined,
            left: 18, right: 18, display: 'flex', justifyContent: 'space-between'}}>
            {Array.from({length: 24}, (_, p) => <div key={p} style={{width: 18, height: 10, background: config.background, borderRadius: 2}} />)}
          </div>)}
          <div style={{position: 'absolute', bottom: 12, right: 34, padding: '0 8px', background: config.border,
            fontSize: 16, color: '#d7bd85'}}>{String(i+1).padStart(2, '0')}</div>
        </>}
      </div>;
    })}
  </AbsoluteFill>;
};
