import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

const objectPosition = (p = [.5, .5]) => `${p[0] * 100}% ${p[1] * 100}%`;

// Video source offsets use the composition's fps; all inputs remain muted.
export const AvatarScene = ({avatar, avatarStart = 0, placement = 'full', picture,
  isVideo = false, motionParams: p = {}}) => {
  const frame = useCurrentFrame();
  const {width, height, fps, durationInFrames} = useVideoConfig();
  const full = placement === 'full';
  const left = placement === 'left';
  const panelWidth = width * (p.avatar_width ?? .42);
  const mediaWidth = width - panelWidth;
  const enter = interpolate(frame, [0, Math.min(p.arrival_frames ?? 18, Math.max(1, durationInFrames - 1))], [0, 1],
    {easing: Easing.out(Easing.cubic), extrapolateRight: 'clamp', extrapolateLeft: 'clamp'});
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1],
    {easing: Easing.inOut(Easing.sin), extrapolateRight: 'clamp'});
  const zoom = 1 + (p.zoom_start ?? 0) + ((p.zoom_end ?? .04) - (p.zoom_start ?? 0)) * progress;
  const video = (source, start, style) => <OffthreadVideo src={staticFile(source)} muted
    startFrom={Math.round(start * fps)} style={style}/>;
  const photoStyle = {width: '100%', height: '100%', objectFit: p.media_fit ?? 'contain',
    objectPosition: objectPosition(p.media_position), transform: `scale(${zoom})`};
  return <AbsoluteFill style={{background: '#11151b', overflow: 'hidden'}}>
    {!full && picture && <div style={{position: 'absolute', left: left ? panelWidth : 0,
      width: mediaWidth, height, overflow: 'hidden'}}>
      <AbsoluteFill style={{filter: `blur(${p.blur ?? 28}px) brightness(.65)`, transform: 'scale(1.12)'}}>
        {isVideo ? video(picture, p.media_source_start ?? 0, {width: '100%', height: '100%', objectFit: 'cover'})
          : <Img src={staticFile(picture)} style={{width: '100%', height: '100%', objectFit: 'cover'}}/>}
      </AbsoluteFill>
      <AbsoluteFill style={{opacity: enter}}>
        {isVideo ? video(picture, p.media_source_start ?? 0, photoStyle)
          : <Img src={staticFile(picture)} style={photoStyle}/>}
      </AbsoluteFill>
    </div>}
    <div style={{position: 'absolute', left: full || left ? 0 : mediaWidth,
      width: full ? width : panelWidth, height, overflow: 'hidden', opacity: full ? 1 : enter,
      transform: full ? undefined : `translateX(${(left ? -1 : 1) * 24 * (1 - enter)}px)`}}>
      {video(avatar, avatarStart, {width: '100%', height: '100%', objectFit: p.avatar_fit ?? 'cover',
        objectPosition: objectPosition(p.avatar_position)})}
    </div>
    {!full && <div style={{position: 'absolute', top: 0, left: (left ? panelWidth : mediaWidth) - 1,
      width: 2, height, background: '#ffffff20', opacity: enter}}/>}
  </AbsoluteFill>;
};
