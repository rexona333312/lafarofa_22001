import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

export const EDITORIAL_TEXT = ['marker_highlight', 'question_panel_bottom', 'question_panel_top'];
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

// Deterministic uneven edges and translucent streaks, revealed by the same frame window as SFX.
export const MarkerStroke = ({progress}) => {
  const edge = (y, phase) => Array.from({length: 81}, (_, i) =>
    `${i * 12.5},${y + Math.sin(i * 1.9 + phase) * 2.6 + Math.sin(i * .47) * 1.8}`).join(' ');
  return <svg viewBox="0 0 1000 100" preserveAspectRatio="none"
    style={{position: 'absolute', inset: '-5% -2%', width: '104%', height: '110%', overflow: 'visible',
      clipPath: `inset(0 ${100 * (1 - progress)}% 0 0)`}}>
    <polygon points={`${edge(9, 0)} ${edge(91, 2).split(' ').reverse().join(' ')}`}
      fill="#f5c52b" opacity=".74" />
    {Array.from({length: 16}, (_, i) => <path key={i}
      d={`M 0 ${12 + i * 5} Q 370 ${6 + i * 5} 1000 ${14 + i * 5}`}
      fill="none" stroke={i % 3 ? '#ffdf57' : '#a98317'} strokeWidth={i % 3 ? 1.3 : .6} opacity=".24" />)}
  </svg>;
};

export const EditorialText = ({cue}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const frames = cue.duration_frames;
  const marker = cue.template === 'marker_highlight';
  const exit = interpolate(frame, [frames - 10, frames - 1], [1, 0], clamp);
  const appear = interpolate(frame, [0, marker ? 6 : 21], [0, 1],
    {...clamp, easing: Easing.out(Easing.cubic)});
  const progress = marker ? interpolate(frame, [cue.params.marker_delay_frames,
    cue.params.marker_delay_frames + cue.params.marker_frames], [0, 1], clamp) : 0;
  const y = marker ? 0 : (cue.template === 'question_panel_top' ? -1 : 1) * (height * .65) * (1 - appear);
  const text = cue.text.toLowerCase();
  const fontSize = Math.min(cue.params.font_size ?? 66, 1400 / Math.max(12, text.length) * 1.8) * width / 1920;
  return <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
    {!marker && <AbsoluteFill style={{opacity: appear * exit,
      background: 'radial-gradient(ellipse at center, transparent 18%, rgba(0,0,0,.32) 55%, rgba(0,0,0,.82) 100%)'}} />}
    <div style={{position: 'relative', maxWidth: '80%', padding: marker ? '8px 22px' : '18px 42px',
      transform: `translateY(${y}px)`, opacity: appear * exit,
      background: marker ? undefined : '#db2d2d', borderRadius: marker ? 0 : 12,
      fontFamily: 'coolvetica', fontSize, lineHeight: 1.15, textAlign: 'center', color: '#ffffff',
      boxShadow: marker ? undefined : '0 4px 0 rgba(0,0,0,.18)'}}>
      {marker && <MarkerStroke progress={progress} />}
      <span style={{position: 'relative', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
        textShadow: marker ? '0 2px 3px #33290d, 0 0 7px rgba(0,0,0,.85)' : '0 1px 2px rgba(0,0,0,.2)'}}>{text}</span>
    </div>
  </AbsoluteFill>;
};
