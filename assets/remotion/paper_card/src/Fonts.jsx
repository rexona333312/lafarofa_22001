import {useEffect, useState} from 'react';
import {staticFile, delayRender, continueRender, cancelRender} from 'remotion';

let fontPromise;
export const useCoolvetica = () => {
  const [handle] = useState(() => delayRender('Loading coolvetica'));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    fontPromise ??= new FontFace('coolvetica', `url("${staticFile('fonts/coolvetica-rg.ttf')}")`).load()
      .then(font => document.fonts.add(font));
    fontPromise.then(() => {setReady(true); continueRender(handle);}).catch(cancelRender);
  }, [handle]);
  return ready;
};

export const fitFont = (text, preferred, maxWidth) => {
  if (typeof document === 'undefined') return preferred;
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = `${preferred}px coolvetica`;
  return Math.min(preferred, preferred * maxWidth / Math.max(1, ctx.measureText(text).width));
};
