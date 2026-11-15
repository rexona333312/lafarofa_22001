import React from 'react';
import {AbsoluteFill, Sequence, Video, staticFile, useVideoConfig} from 'remotion';
import {TransitionSeries} from '@remotion/transitions';
import {BlurIn} from './remotion/primitives/blur-in';
import {FadeIn} from './remotion/primitives/fade-in';
import {ScaleIn} from './remotion/primitives/scale-in';
import {SpringIn} from './remotion/primitives/spring-in';
import {transitionBlurReveal} from './remotion/primitives/blur-reveal';
import {transitionFrostedGlassWipe} from './remotion/primitives/frosted-glass-wipe';
import {transitionFade} from './remotion/primitives/transition-fade';
import {transitionWipe} from './remotion/primitives/transition-wipe';
import {transitionDirectionalWipe} from './remotion/primitives/directional-wipe';
import {EDITORIAL_TEXT, EditorialText} from './EditorialText';
import {NARRATIVE_TEXT, NarrativeText} from './NarrativeText';
import {useCoolvetica} from './Fonts';

export const MOTIONS = {
  'blur-in': BlurIn, 'fade-in': FadeIn,
  'scale-in': ScaleIn, 'spring-in': SpringIn,
};

const TextCue = ({cue}) => {
  if (NARRATIVE_TEXT.includes(cue.template)) return <NarrativeText cue={cue} />;
  if (EDITORIAL_TEXT.includes(cue.template)) return <EditorialText cue={cue} />;
  throw new Error(`Unknown text template: ${cue.template}`);
};

export const TextScene = ({source, cues}) => {
  useCoolvetica();
  return <AbsoluteFill>
    <Video src={staticFile(source)} muted style={{width: '100%', height: '100%'}} />
    {cues.map(cue => <Sequence key={cue.id} from={cue.local_start_frame} durationInFrames={cue.duration_frames}>
      <TextCue cue={cue} />
    </Sequence>)}
  </AbsoluteFill>;
};

const TRANSITIONS = {
  'blur-reveal': transitionBlurReveal,
  'frosted-glass-wipe': transitionFrostedGlassWipe,
  'transition-fade': transitionFade,
  'transition-wipe': transitionWipe,
  'directional-wipe': transitionDirectionalWipe,
};

export const TransitionWindow = ({left, right, kind, params = {}}) => {
  const {durationInFrames} = useVideoConfig();
  const transition = TRANSITIONS[kind];
  if (!transition) throw new Error(`Unknown transition: ${kind}`);
  // One guard frame on each side lets progress reach both endpoints without shortening the timeline.
  const config = transition({...params, durationInFrames: durationInFrames - 2});
  return <AbsoluteFill style={{backgroundColor: '#000'}}>
    <TransitionSeries>
      <TransitionSeries.Sequence durationInFrames={durationInFrames - 1}>
        <Video src={staticFile(left)} muted style={{width: '100%', height: '100%'}} />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition {...config} />
      <TransitionSeries.Sequence durationInFrames={durationInFrames - 1}>
        <Video src={staticFile(right)} muted trimBefore={1} style={{width: '100%', height: '100%'}} />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  </AbsoluteFill>;
};
