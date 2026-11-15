import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Img, continueRender, delayRender, interpolate, staticFile,
  useCurrentFrame, useVideoConfig} from 'remotion';

const ease = t => 1 - Math.pow(1 - t, 3);
const layouts = {
  left: {center: 310, maxWidth: 680, textX: 950, textWidth: 850,
    arrow: 'M 960 615 C 750 950, 555 1040, 350 890', tip: [350, 890], angle: -144},
  center: {center: 960, maxWidth: 680, textX: 1340, textWidth: 500,
    arrow: 'M 1360 615 C 1300 830, 1200 955, 1060 890', tip: [1060, 890], angle: -155},
  right: {center: 1610, maxWidth: 680, textX: 120, textWidth: 850,
    arrow: 'M 950 615 C 1170 950, 1365 1040, 1570 890', tip: [1570, 890], angle: -36},
};

export const PersonIntro = ({background, picture, pictureWidth, pictureHeight,
  placement = 'left', personName = '', personRole = '', motionParams = {}}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const [fontHandle] = useState(() => delayRender('Loading character font'));
  useEffect(() => {
    const font = new FontFace('coolvetica', `url("${staticFile('fonts/coolvetica-rg.ttf')}")`);
    let active = true;
    font.load().then(loaded => {
      document.fonts.add(loaded);
      if (active) continueRender(fontHandle);
    }).catch(() => {if (active) continueRender(fontHandle);});
    return () => {active = false;};
  }, [fontHandle]);
  const layout = layouts[placement];
  const arrival = Math.min(motionParams.arrival_frames ?? 36, Math.max(1, (durationInFrames - 1) / 1.4));
  const phase = (delay = 0) => interpolate(frame, [delay, delay + arrival], [0, 1],
    {easing: ease, extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const person = phase();
  const text = phase(arrival * .18);
  const arrow = phase(arrival * .4);
  const drift = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1]);
  const scale = Math.min(970 / pictureHeight, layout.maxWidth / pictureWidth);
  const w = pictureWidth * scale, h = pictureHeight * scale;
  const nameSize = placement === 'center' ? 68 : 98;
  const titleSize = Math.min(nameSize, layout.textWidth / Math.max(8, personName.length) * 1.6);
  const [tipX, tipY] = layout.tip;
  return <AbsoluteFill style={{background: '#111214', overflow: 'hidden'}}>
    <Img src={staticFile(background)} style={{width: '100%', height: '100%', objectFit: 'cover',
      filter: `grayscale(1) blur(${motionParams.background_blur ?? 8}px) brightness(.42)`,
      transform: `scale(${1.055 + drift * .025})`}} />
    <AbsoluteFill style={{background: 'rgba(0,0,0,.15)'}} />
    <Img src={staticFile(picture)} style={{position: 'absolute', width: w, height: h,
      left: layout.center - w / 2, bottom: 0, objectFit: 'contain', transformOrigin: 'bottom center',
      transform: `translateY(${(1080 + 40) * (1 - person)}px) scale(${1 + drift * .012})`,
      opacity: Math.min(1, person * 3), filter: 'drop-shadow(0px 12px 28px rgba(0,0,0,.45))'}} />
    <div style={{position: 'absolute', left: layout.textX, top: 465, width: layout.textWidth,
      color: '#fff', fontFamily: 'coolvetica, sans-serif', textAlign: 'left',
      opacity: text, transform: `translateY(${1080 * (1 - text)}px)`,
      textShadow: '0 3px 18px rgba(0,0,0,.6)'}}>
      <div style={{fontSize: titleSize, lineHeight: 1.05, letterSpacing: '0.035em',
        textTransform: 'uppercase', overflowWrap: 'anywhere'}}>{personName}</div>
      {personRole && <div style={{fontSize: placement === 'center' ? 31 : 42, marginTop: 22,
        lineHeight: 1.2, letterSpacing: '.025em', textTransform: 'uppercase'}}>{personRole}</div>}
    </div>
    <svg viewBox="0 0 1920 1080" style={{position: 'absolute', inset: 0, width: '100%', height: '100%',
      overflow: 'visible', opacity: arrow, transform: `translateY(${1080 * (1 - arrow)}px)`,
      filter: 'drop-shadow(0px 0px 5px rgba(255,255,255,.45))'}}>
      <path d={layout.arrow} pathLength="1" fill="none" stroke="white" strokeWidth="3.5"
        strokeLinecap="round" strokeDasharray="1" strokeDashoffset={1 - arrow} />
      <g transform={`translate(${tipX} ${tipY}) rotate(${layout.angle})`}
        opacity={Math.max(0, (arrow - .85) / .15)}>
        <path d="M 0 0 L -19 -8 L -14 0 L -19 8 Z" fill="white" />
      </g>
    </svg>
  </AbsoluteFill>;
};
