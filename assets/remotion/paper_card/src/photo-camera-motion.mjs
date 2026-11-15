// Frame-driven, floating-point motion. No CSS transitions, elapsed time or integer crop steps.
export const cameraTransform = (frame, frames, width, height, start, end, direction = null) => {
  const t=frames<=1?0:Math.min(1,Math.max(0,frame/(frames-1)));
  const progress=.5-.5*Math.cos(Math.PI*t);
  const zoom=1+start+(end-start)*progress;
  let x=width*(1-zoom)/2,y=height*(1-zoom)/2;
  if(direction==='right')x=width*(1-zoom)*progress;
  if(direction==='left')x=width*(1-zoom)*(1-progress);
  if(direction==='down')y=height*(1-zoom)*progress;
  if(direction==='up')y=height*(1-zoom)*(1-progress);
  return {zoom,x,y};
};
