import React from 'react';
import {MOTIONS, TextScene, TransitionWindow} from './V2';
import {PersonIntro} from './PersonIntro';
import {HistoryTimeline} from './HistoryTimeline';
import {PhotoCarousel} from './PhotoCarousel';
import {ReferenceScene} from './ReferenceScene';
import {PhotoCamera} from './PhotoCamera';
import {AvatarScene} from './AvatarScene';
import {DocumentaryScene} from './DocumentaryScene';
import {GeographicMap} from './GeographicMap';
import {
  AbsoluteFill,
  Composition,
  Easing,
  Img,
  Video,
  interpolate,
  registerRoot,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const starts = {
  'top-right': [1700, -1100],
  'top-left': [-1700, -1100],
  'bottom-right': [1700, 1100],
  'bottom-left': [-1700, 1100],
  top: [0, -1200],
  bottom: [0, 1200],
  left: [-1800, 0],
  right: [1800, 0],
};

const PaperCard = ({background, picture, from, isVideo, pictureWidth, pictureHeight, motionParams = {}}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const arrivalEnd = Math.min(motionParams.arrival_frames ?? 27, Math.max(1, durationInFrames - 1));
  const arrival = interpolate(frame, [0, arrivalEnd], [0, 1], {
    easing: Easing.inOut(Easing.cubic),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const turn = interpolate(frame, [arrivalEnd, Math.max(arrivalEnd + 1, durationInFrames - 1)], [0, 1], {
    easing: Easing.inOut(Easing.sin),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const [startX, startY] = starts[from] ?? starts['top-right'];
  const x = startX * (1 - arrival) + interpolate(turn, [0, 1], [12, -12]);
  const y = startY * (1 - arrival) + interpolate(turn, [0, 1], [-8, 8]);
  const z = 150 * (1 - arrival) + 12 * turn;
  const rx = interpolate(turn, [0, 1], [-4, 4]);
  const ry = interpolate(turn, [0, 1], [-5, 5]);
  const rz = interpolate(turn, [0, 1], [-1, 1]);
  const imageScale = Math.min(1152 / pictureWidth, 642 / pictureHeight);
  const cardWidth = Math.round(pictureWidth * imageScale) + 28;
  const cardHeight = Math.round(pictureHeight * imageScale) + 28;
  const Motion = MOTIONS[from];
  const card = (
    <div style={{width: cardWidth, height: cardHeight, padding: 14, background: '#f7f3ec',
      boxSizing: 'border-box', borderRadius: motionParams.corner_radius ?? 28, overflow: 'hidden',
      boxShadow: '0 35px 85px rgba(29, 23, 20, 0.34)', backfaceVisibility: 'hidden',
      transform: Motion ? undefined : `translate3d(${x}px, ${y}px, ${z}px) rotateX(${rx}deg) rotateY(${ry}deg) rotateZ(${rz}deg)`}}>
      {isVideo ? <Video src={staticFile(picture)} muted loop
        style={{width: '100%', height: '100%', objectFit: 'contain', borderRadius: 15}} />
        : <Img src={staticFile(picture)}
          style={{width: '100%', height: '100%', objectFit: 'contain', borderRadius: 15}} />}
    </div>
  );

  return (
    <AbsoluteFill style={{backgroundColor: '#d9d0c5', overflow: 'hidden'}}>
      <Img
        src={staticFile(background)}
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
      <AbsoluteFill
        style={{
          alignItems: 'center',
          justifyContent: 'center',
          perspective: 1500,
          perspectiveOrigin: '50% 50%',
        }}
      >
        {Motion ? <Motion durationInFrames={Math.min(motionParams.arrival_frames ?? 27, Math.max(1, durationInFrames - 1))}>
          {card}
        </Motion> : card}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Root = () => (<>
  <Composition id="DocumentaryScene" component={DocumentaryScene} width={1920} height={1080} fps={30}
    durationInFrames={180} calculateMetadata={({props})=>({durationInFrames:props.frames??180})}/>
  <Composition id="GeographicMap" component={GeographicMap} width={1920} height={1080} fps={30}
    durationInFrames={180} calculateMetadata={({props})=>({durationInFrames:props.frames??180})}/>
  <Composition id="AvatarScene" component={AvatarScene} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{placement: 'full', avatarStart: 0, motionParams: {}}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})}/>
  <Composition id="PhotoCamera" component={PhotoCamera} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{cameraParams:{layout:'cover',zoom_start:0,zoom_end:.06,blur:28}}}
    calculateMetadata={({props})=>({durationInFrames:props.frames??150})}/>
  <Composition id="ReferenceScene" component={ReferenceScene} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{variant: 'chapter_heading', motionParams: {text: 'chapter', arrival_frames: 12, underline_start: 9, underline_frames: 15}, groupFrames: 150}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})} />
  <Composition id="PhotoCarousel" component={PhotoCarousel} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{starts: [0, 75], captions: ['', ''], frameOffset: 0, style: 'paper', archival: false}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})} />
  <Composition id="HistoryTimeline" component={HistoryTimeline} width={1920} height={1080} fps={30}
    durationInFrames={210} defaultProps={{year: 1918, fromYear: 1913, label: 'fishing trap', scrollFrames: 72}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 210})} />
  <Composition id="PersonIntro" component={PersonIntro} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{placement: 'left', personName: 'Person', personRole: '',
      pictureWidth: 600, pictureHeight: 1000}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})} />
  <Composition
    id="PaperCard"
    component={PaperCard}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={150}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})}
    defaultProps={{
      background: 'background.jpg',
      picture: 'picture.jpeg',
      from: 'top-right',
      isVideo: false,
      pictureWidth: 1920,
      pictureHeight: 1080,
    }}
  />
  <Composition id="TextScene" component={TextScene} width={1920} height={1080} fps={30}
    durationInFrames={150} defaultProps={{cues: []}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 150})} />
  <Composition id="TransitionWindow" component={TransitionWindow} width={1920} height={1080} fps={30}
    durationInFrames={24} defaultProps={{kind: 'transition-fade'}}
    calculateMetadata={({props}) => ({durationInFrames: props.frames ?? 24})} />
</>);

registerRoot(Root);
