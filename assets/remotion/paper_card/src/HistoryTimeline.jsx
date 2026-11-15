import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig, interpolate, Easing,
  delayRender, continueRender, cancelRender} from 'remotion';

export const HistoryTimeline = ({background, picture, year, fromYear, label, scrollFrames}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const [fontHandle] = useState(() => delayRender('Loading timeline coolvetica'));
  useEffect(() => {
    new FontFace('coolvetica', `url("${staticFile('fonts/coolvetica-rg.ttf')}")`).load().then(font => {
      document.fonts.add(font); continueRender(fontHandle);
    }).catch(cancelRender);
  }, [fontHandle]);
  const opts = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)};
  const t = interpolate(frame, [0, scrollFrames], [0, 1], opts);
  const current = fromYear + (year - fromYear) * t;
  const base = Math.floor(current);
  const spacing = width / 7;
  const reveal = interpolate(frame, [scrollFrames + 3, scrollFrames + 24], [0, 1],
    {...opts, easing: Easing.out(Easing.cubic)});
  return <AbsoluteFill style={{backgroundColor: '#f7f7f4', overflow: 'hidden', fontFamily: 'coolvetica'}}>
    <Img src={staticFile(background)} style={{width: '100%', height: '100%', objectFit: 'cover',
      filter: 'grayscale(1)', opacity: .12}} />
    <AbsoluteFill style={{backgroundImage: 'radial-gradient(#696966 1px, transparent 1.3px)',
      backgroundSize: `${width / 65}px ${width / 65}px`, opacity: .48}} />
    <div style={{position: 'absolute', top: height * .69, width: '100%', height: 5, background: '#171717'}} />
    {Array.from({length: 11}, (_, i) => base - 5 + i).filter(y => y >= 1 && y <= 9999).map(y => {
      const x = width / 2 + (y - current) * spacing;
      const emphasis = Math.max(0, 1 - Math.abs(y - current));
      return <React.Fragment key={y}>
        {[0, .5].map(offset => <div key={offset} style={{position: 'absolute',
          left: x + offset * spacing, top: height * .69 - (offset ? 22 : 36),
          height: offset ? 22 : 36, width: 3, background: '#171717'}} />)}
        <div style={{position: 'absolute', left: x, top: height * .72, transform: 'translateX(-50%)',
          fontSize: width * .028, color: '#171717', opacity: .38 + .62 * emphasis}}>{y}</div>
      </React.Fragment>;
    })}
    <div style={{position: 'absolute', left: width / 2, top: height * .84,
      width: width * .034, height: width * .034, background: '#cc003d',
      borderRadius: '0 0 25% 0', transform: 'translateX(-50%) rotate(45deg)'}} />
    <div style={{position: 'absolute', top: height * .1 + (1 - reveal) * 34, left: width * .29,
      width: width * .42, height: height * .46, opacity: reveal, padding: 12,
      boxSizing: 'border-box', background: '#fff', border: '1px solid #d6d4cf',
      borderRadius: 10, boxShadow: '0 10px 26px rgba(0,0,0,.14)'}}>
      <Img src={staticFile(picture)} style={{width: '100%', height: '100%', objectFit: 'contain', borderRadius: 4}} />
    </div>
    <div style={{position: 'absolute', top: height * .58, left: '50%', transform: 'translateX(-50%)',
      maxWidth: '75%', opacity: reveal, padding: '10px 30px', borderRadius: 32, background: '#cc003d',
      fontSize: width * .025, lineHeight: 1.1, color: '#fff', textAlign: 'center'}}>{label.toLowerCase()}</div>
  </AbsoluteFill>;
};
