import React from 'react';
import {AbsoluteFill, Easing, Img, Video, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {useCoolvetica, fitFont} from './Fonts';
import {CurvedGrid} from './NarrativeText';
import {nextComponents} from './NextReferenceScene';
import {lateComponents} from './LateReferenceScene';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};
const progress = (f, start, duration, easing = Easing.out(Easing.cubic)) =>
  interpolate(f, [start, start+duration], [0, 1], {...clamp, easing});
const mediaStyle = {width: '100%', height: '100%', objectFit: 'cover'};
const Backdrop = ({picture, isVideo, style = {}}) => isVideo
  ? <Video src={staticFile(picture)} muted loop style={{...mediaStyle, ...style}} />
  : <Img src={staticFile(picture)} style={{...mediaStyle, ...style}} />;
const Vignette = ({opacity = 1}) => <AbsoluteFill style={{opacity,
  background: 'radial-gradient(ellipse at center, transparent 15%, rgba(0,0,0,.75) 100%)'}} />;

const Chapter = ({picture, isVideo, p, f, groupFrames}) => {
  const text = p.text.toLowerCase(), size = fitFont(text, 120, 1520);
  const arrival = progress(f, 0, p.arrival_frames);
  const underline = progress(f, p.underline_start, p.underline_frames, Easing.linear);
  return <AbsoluteFill>
    <AbsoluteFill>
      <Backdrop picture={picture} isVideo={isVideo} style={{filter: 'brightness(.85)'}} />
      <Vignette opacity={.3} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div style={{position: 'relative', color: '#fff', fontSize: size, opacity: arrival,
          textShadow: '0 4px 15px #000', transform: `translateY(${(1-arrival)*24}px) scale(${1+.18*progress(f,p.arrival_frames,78,Easing.out(Easing.cubic))})`}}>
          {text}
          <div style={{position: 'absolute', bottom: -23, left: 0, right: 0, height: 10,
            background: '#e5b944', transform: `scaleX(${underline})`, transformOrigin: 'left center'}} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  </AbsoluteFill>;
};

const DateCounter = ({picture, isVideo, p, f}) => {
  const arrival = progress(f, 0, p.arrival_frames);
  const line = progress(f, 0, p.line_frames);
  const text = progress(f, p.arrival_frames*.5, p.arrival_frames*.5);
  const count = progress(f, p.count_start, p.count_frames, Easing.inOut(Easing.cubic));
  const exact = (p.from_year ?? p.year)+((p.year)-(p.from_year ?? p.year))*count;
  const value = Math.ceil(exact), fraction = value-exact;
  const counting = count > 0 && count < 1;
  return <AbsoluteFill>
    <Backdrop picture={picture} isVideo={isVideo} style={{filter: `brightness(${1-arrival*.27})`}} />
    <Vignette opacity={arrival} />
    <div style={{position: 'absolute', left: 960-7, top: 486-7, width: 14, height: 14,
      borderRadius: '50%', background: '#fff', transform: `scale(${.1+.9*arrival})`}} />
    <div style={{position: 'absolute', left: 270, top: 486, width: 1380, height: 2, background: '#fff',
      transform: `scaleX(${line})`, transformOrigin: 'center'}} />
    <div style={{position: 'absolute', top: 505, left: 710, width: 500, height: 62,
      overflow: 'hidden', textAlign: 'center', color: '#fff', fontSize: 62, opacity: text,
      transform: `scale(${.2+.8*arrival})`, textShadow: '0 2px 8px #000'}}>
      <div style={{transform: `translateY(${-fraction*62}px)`}}>
        <div style={{height: 62, lineHeight: '62px'}}>{value}</div>
        {counting && <div style={{height: 62, lineHeight: '62px'}}>{value-1}</div>}
      </div>
    </div>
  </AbsoluteFill>;
};

const Statement = ({picture, isVideo, background, p, f}) => {
  const text = p.text.toLowerCase(), size = fitFont(text, 96, 1220);
  const arrival = progress(f, 0, p.arrival_frames);
  const reveal = progress(f, p.reveal_start, p.reveal_frames, Easing.linear);
  const highlight = progress(f, p.highlight_start, p.highlight_frames, Easing.linear);
  const upper = progress(f, p.reveal_start, p.reveal_frames+6, Easing.linear);
  const lower = progress(f, p.reveal_start+p.reveal_frames, Math.max(1,p.highlight_frames-p.reveal_frames), Easing.linear);
  return <AbsoluteFill style={{background: '#0b0b0b'}}>
    <AbsoluteFill style={{background: '#efeeea', transform: `translateY(${(1-arrival)*480}px)`}}>
      <Img src={staticFile(background)} style={{...mediaStyle, opacity: .13, filter: 'grayscale(1)'}} />
      <div style={{position:'absolute',left:35,top:170,bottom:170,width:140,opacity:.17,
        backgroundImage:'radial-gradient(#555 1.2px,transparent 1.2px)',backgroundSize:'15px 15px'}} />
      <AbsoluteFill style={{opacity: .065, transform: 'translateX(180px) scale(1.1)'}}><Backdrop picture={picture} isVideo={isVideo} style={{filter: 'grayscale(1)'}} /></AbsoluteFill>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div style={{position: 'relative', width: 1280, textAlign: 'left'}}>
          <div style={{height: 5, background: '#141414', transform: `scaleX(${upper})`, transformOrigin: 'left'}} />
          <div style={{position: 'relative', display:'inline-block', maxWidth:'100%', margin: '24px 0', padding: '12px 20px', color: '#fff', fontSize: size,
            background: '#242424', clipPath: `inset(0 ${(1-reveal)*100}% 0 0)`, textShadow: '0 2px 5px #0006'}}>
            <svg viewBox="0 0 1650 170" preserveAspectRatio="none" style={{position: 'absolute', inset: 0, width: '100%', height: '100%', clipPath: `inset(0 ${(1-highlight)*100}% 0 0)`}}>
              <path d="M 0 12 L 140 8 L 340 14 L 520 7 L 760 11 L 1020 5 L 1240 12 L 1430 7 L 1650 13 L 1650 160 L 1440 166 L 1260 158 L 1030 164 L 820 158 L 600 166 L 420 160 L 200 167 L 0 159 Z" fill="#db243a" />
              {[23,54,81,119,148].map((y,i) => <path key={i} d={`M 0 ${y} Q 650 ${y-8} 1650 ${y+3}`} fill="none" stroke={i%2 ? '#ef5d69' : '#a9162b'} strokeWidth="3" opacity=".17" />)}
            </svg>
            <span style={{position: 'relative'}}>{text}</span>
          </div>
          <div style={{height: 5, background: '#141414', transform: `scaleX(${lower})`, transformOrigin: 'left'}} />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  </AbsoluteFill>;
};

const Evidence = ({left, right, labels, p, f}) => {
  const arrival = progress(f, p.arrival_start, p.arrival_frames);
  const label = progress(f, p.label_start, 10);
  return <AbsoluteFill>
    <CurvedGrid />
    {[left, right].map((source, i) => <React.Fragment key={i}>
      <div style={{position: 'absolute', left: [180,1020][i], top: 274, width: 720, height: 426,
        boxSizing: 'border-box', border: '24px solid #f7f4f1', boxShadow: '0 16px 45px #0008',
        transform: `scale(${arrival})`, transformOrigin: 'center', opacity: arrival > 0 ? 1 : 0}}>
        <Backdrop picture={source} style={{filter: p.archival ? 'grayscale(1)' : undefined}} />
      </div>
      <div style={{position: 'absolute', left: [279,1119][i], top: 732+(1-label)*18, width: 522, height:74,
        padding: '0 20px', lineHeight:'74px', boxSizing: 'border-box', textAlign: 'center', color: '#fff', background: '#bf1530',
        opacity: label, fontSize: fitFont(labels[i].toLowerCase(), 62, 482)}}>{labels[i].toLowerCase()}</div>
    </React.Fragment>)}
  </AbsoluteFill>;
};

export const ReferenceScene = ({variant, motionParams: p, frameOffset = 0, ...props}) => {
  useCoolvetica();
  const f = useCurrentFrame()+frameOffset;
  const components = {chapter_heading: Chapter, date_countback: DateCounter,
    editorial_statement: Statement, paired_evidence: Evidence, ...nextComponents, ...lateComponents};
  const Component = components[variant];
  if (!Component) throw new Error(`Unknown reference template: ${variant}`);
  return <AbsoluteFill style={{fontFamily: 'coolvetica', overflow: 'hidden'}}><Component {...props} p={p} f={f} /></AbsoluteFill>;
};
