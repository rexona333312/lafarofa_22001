import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {MarkerStroke} from './EditorialText';
import {fitFont} from './Fonts';

export const NARRATIVE_TEXT = ['impact_typewriter', 'speech_words_grid', 'speech_words_overlay', 'selective_marker'];
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

export const CurvedGrid = () => <AbsoluteFill style={{background: '#060606'}}>
  <svg viewBox="0 0 1920 1080" preserveAspectRatio="none" style={{width: '100%', height: '100%'}}>
    {Array.from({length: 25}, (_, i) => {
      const x = i * 80;
      return <path key={`x${i}`} d={`M ${x} 0 Q ${960+(x-960)*.9} 540 ${x} 1080`} stroke="#737373" strokeWidth="2" fill="none" />;
    })}
    {Array.from({length: 15}, (_, i) => {
      const y = i * 78;
      return <path key={`y${i}`} d={`M 0 ${y} Q 960 ${540+(y-540)*.84} 1920 ${y}`} stroke="#737373" strokeWidth="2" fill="none" />;
    })}
  </svg>
  <AbsoluteFill style={{background: 'radial-gradient(ellipse at center, transparent 25%, #060606 86%)'}} />
</AbsoluteFill>;

export const NarrativeText = ({cue}) => {
  const frame = useCurrentFrame();
  const {width} = useVideoConfig();
  const impact = cue.template === 'impact_typewriter';
  const selective = cue.template === 'selective_marker';
  const text = impact ? cue.text.toUpperCase() : cue.text.toLowerCase();
  const preferred = impact ? 230 : (cue.params.font_size ?? 76);
  const fontSize = (impact ? fitFont(text, preferred, 1540) : preferred) * width / 1920;
  const words = cue.speech_words ?? [];
  let typed = 0, letters = 0;
  const spans = words.map((word, index) => {
    const value = impact ? word.text.toUpperCase() : word.text.toLowerCase();
    const n = frame < word.start_frame ? 0 : Math.min(value.length, 1 + Math.floor(interpolate(frame,
      [word.start_frame, Math.max(word.start_frame + 1, word.end_frame - 1)], [0, value.length - 1], clamp)));
    typed += n; letters += value.length;
    const opacity = interpolate(frame, [word.start_frame, Math.min(word.end_frame, word.start_frame + 5)], [0, 1], clamp);
    return <React.Fragment key={index}>
      {index > 0 && ' '}
      <span style={{whiteSpace: 'nowrap', display: 'inline-block', opacity: impact ? 1 : opacity,
        filter: impact ? undefined : `blur(${(1-opacity)*3}px)`}}>
        {impact ? Array.from(value).map((char, i) => <span key={i} style={{visibility: i < n ? 'visible' : 'hidden'}}>{char}</span>) : value}
      </span>
    </React.Fragment>;
  });
  const appear = interpolate(frame, [0, 6], [0, 1], clamp);
  const progress = selective ? interpolate(frame,
    [cue.params.marker_delay_frames, cue.params.marker_delay_frames + cue.params.marker_frames], [0, 1], clamp) : 0;
  let highlighted;
  if (selective) {
    const tokens = text.split(/\s+/), pieces = [];
    let cursor = 0;
    cue.params.highlight_ranges.forEach(([lo, hi], i) => {
      if (lo > cursor) pieces.push(<React.Fragment key={`plain${i}`}>{tokens.slice(cursor, lo).join(' ')}{' '}</React.Fragment>);
      pieces.push(<span key={`mark${i}`} style={{position: 'relative', display: 'inline-block', whiteSpace: 'nowrap', margin: '0 6px', padding: '4px 10px', fontStyle: 'italic'}}>
        <MarkerStroke progress={progress} /><span style={{position: 'relative'}}>{tokens.slice(lo, hi).join(' ')}</span>
      </span>);
      if (hi < tokens.length) pieces.push(' ');
      cursor = hi;
    });
    if (cursor < tokens.length) pieces.push(tokens.slice(cursor).join(' '));
    highlighted = pieces;
  }
  return <AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', overflow: 'hidden'}}>
    {cue.template === 'speech_words_grid' && <CurvedGrid />}
    {impact && <AbsoluteFill style={{background: '#bb0006', opacity: .18 + .6 * typed / Math.max(1, letters), mixBlendMode: 'multiply'}} />}
    <div style={{position: 'relative', width: impact ? '86%' : '80%', textAlign: 'center', fontFamily: 'coolvetica',
      fontSize, color: '#fff', lineHeight: selective ? 1.75 : 1.35, opacity: selective ? appear : 1,
      textShadow: impact ? '0 5px 12px rgba(0,0,0,.8)' : selective ? '0 2px 3px #33290d, 0 0 7px rgba(0,0,0,.8)' : '0 0 9px rgba(255,255,255,.42), 0 2px 10px #000'}}>
      {selective ? highlighted : spans}
    </div>
  </AbsoluteFill>;
};
