import React from 'react';
import {AbsoluteFill,Img,staticFile,useCurrentFrame,useVideoConfig} from 'remotion';
import {cameraTransform} from './photo-camera-motion.mjs';

export const PhotoCamera = ({picture,pictureWidth,pictureHeight,background,cameraParams:p}) => {
  const frame=useCurrentFrame(),{width,height,durationInFrames}=useVideoConfig();
  const backdrop=p.layout!=='cover';
  const card=p.layout==='blur'||p.layout==='paper';
  const ratio=card ? .82 : 1;
  const factor=Math.min(width*ratio/pictureWidth,height*ratio/pictureHeight);
  const cw=backdrop?pictureWidth*factor:width,ch=backdrop?pictureHeight*factor:height;
  const {zoom,x,y}=cameraTransform(frame,durationInFrames,cw,ch,p.zoom_start,p.zoom_end,p.direction);
  const border=p.layout==='paper'?6:0;
  return <AbsoluteFill style={{background:p.layout==='paper'?'#e6dfd0':'#111',overflow:'hidden'}}>
    {backdrop && (p.layout==='paper'
      ? background&&<Img src={staticFile(background)} style={{width,height,objectFit:'cover'}}/>
      : <AbsoluteFill style={{overflow:'hidden'}}><Img src={staticFile(picture)} style={{width,height,objectFit:'cover',
          transform:'scale(1.1)',filter:`blur(${p.blur}px) brightness(.92)`}}/></AbsoluteFill>)}
    <div style={{position:'absolute',left:(width-cw)/2-border,top:(height-ch)/2-border,
      width:cw+border*2,height:ch+border*2,padding:border,background:border?'white':undefined,
      boxShadow:border?'10px 10px 0 #0003':undefined}}>
      <div style={{width:cw,height:ch,overflow:'hidden'}}>
        <Img src={staticFile(picture)} style={{width:cw,height:ch,objectFit:'cover',display:'block',
          transform:`translate3d(${x}px,${y}px,0) scale(${zoom})`,transformOrigin:'0 0',willChange:'transform'}}/>
      </div>
    </div>
  </AbsoluteFill>;
};
