import {createServer} from 'node:http';
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';

// Cache immutable provider tiles once; browser renders never send third-party API requests.
export const startMapTiles=async(root)=>{
  const cache=resolve(root,'../../geodata/tile_cache');
  const queue=[];let active=0;
  const limited=async(job)=>{
    if(active>=4)await new Promise(ok=>queue.push(ok));
    active++;
    try{return await job();}finally{active--;queue.shift()?.();}
  };
  const server=createServer(async(req,res)=>{
    res.setHeader('Access-Control-Allow-Origin','*');
    const m=/^\/(satellite|terrain)\/(\d{1,2})\/(\d+)\/(\d+)$/.exec(req.url);
    if(!m){res.writeHead(400).end();return;}
    const [,kind,zs,xs,ys]=m,[z,x,y]=[zs,xs,ys].map(Number);
    if(z>14||x>=2**z||y>=2**z){res.writeHead(400).end();return;}
    const folder=resolve(cache,kind,zs,xs),path=resolve(folder,ys);
    try{
      let bytes;
      try{bytes=await readFile(path);}catch(error){
        if(error.code!=='ENOENT')throw error;
        const url=kind==='satellite'
          ?`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/${z}/${y}/${x}.jpeg`
          :`https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${z}/${x}/${y}.png`;
        bytes=await limited(async()=>{
          let last;
          for(let attempt=0;attempt<3;attempt++){
            try{
              const response=await fetch(url,{signal:AbortSignal.timeout(20000)});
              if(!response.ok)throw new Error(`${kind} tile ${z}/${x}/${y}: HTTP ${response.status}`);
              return Buffer.from(await response.arrayBuffer());
            }catch(error){last=error;if(attempt<2)await new Promise(ok=>setTimeout(ok,500*(attempt+1)));}
          }
          throw new Error(`${url}: ${last.message}; ${last.cause?.message??''}`);
        });
        const jpeg=bytes[0]===255&&bytes[1]===216,png=bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
        if(!(kind==='satellite'?jpeg:png))throw new Error('Provider returned an invalid map image');
        await mkdir(folder,{recursive:true});const temp=path+'.'+randomUUID();await writeFile(temp,bytes);await rename(temp,path);
      }
      res.setHeader('Content-Type',kind==='satellite'?'image/jpeg':'image/png');res.end(bytes);
    }catch(error){console.error('Map tile:',error.message);res.writeHead(502).end(error.message);}
  });
  await new Promise((ok,fail)=>{server.once('error',fail);server.listen(0,'127.0.0.1',ok);});
  return {url:`http://127.0.0.1:${server.address().port}/`,close:()=>new Promise(ok=>server.close(ok))};
};
