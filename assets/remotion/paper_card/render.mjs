import {copyFileSync, mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync} from 'node:fs';
import {extname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync, spawn} from 'node:child_process';
import {startMapTiles} from './map-tiles.mjs';
import {randomUUID} from 'node:crypto';
import {availableParallelism, totalmem} from 'node:os';

const args = process.argv.slice(2);
let job;
if (args[0] === '--job') {
  job = JSON.parse(readFileSync(args[1], 'utf8'));
} else {
  const [background, picture, output = 'preview.mp4', from = 'top-right', frames = '150', scale = '1'] = args;
  if (!background || !picture) throw new Error('Usage: npm run render -- BACKGROUND IMAGE OUTPUT [ENTRANCE] [FRAMES] [SCALE]');
  job = {composition: 'PaperCard', output, frames: Number(frames), width: Math.round(1920 * Number(scale)),
    height: Math.round(1080 * Number(scale)), props: {from}, media: {background, picture}};
}
if (!['DocumentaryScene', 'GeographicMap', 'PaperCard', 'PhotoCamera', 'AvatarScene', 'PersonIntro', 'HistoryTimeline', 'PhotoCarousel', 'ReferenceScene', 'TextScene', 'TransitionWindow'].includes(job.composition)
    || !Number.isInteger(job.frames) || job.frames < 1
    || !Number.isInteger(job.width) || !Number.isInteger(job.height) || job.width < 2 || job.height < 2) {
  throw new Error('Invalid render job');
}
const root = fileURLToPath(new URL('.', import.meta.url));
const token = randomUUID();
const copies = [];
const props = {...job.props, frames: job.frames};
if (job.composition === 'PersonIntro' && !['left', 'center', 'right'].includes(props.placement)) {
  throw new Error('Unknown character placement: ' + props.placement);
}
if (job.composition === 'PaperCard' && !['top-right', 'top-left', 'bottom-right', 'bottom-left',
  'top', 'bottom', 'left', 'right', 'blur-in', 'fade-in', 'scale-in', 'spring-in'].includes(props.from)) {
  throw new Error('Unknown card entrance: ' + props.from);
}
mkdirSync(resolve(root, 'public'), {recursive: true});
let mapTiles;
try {
  if(job.composition==='GeographicMap'){
    copyFileSync(resolve(root,'node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs'),resolve(root,'public/maplibre-gl-worker.mjs'));
    mapTiles=await startMapTiles(root);props.tileBase=mapTiles.url;
  }
  for (const [key, source] of Object.entries(job.media)) {
    if (!['background', 'picture', 'source', 'left', 'right', 'avatar'].includes(key) && !/^picture[0-4]$/.test(key)) throw new Error('Invalid media key');
    const name = `${token}-${key}${extname(source)}`;
    const path = resolve(root, 'public', name);
    copyFileSync(source, path);
    copies.push(path);
    props[key] = name;
    if (key === 'picture') {
      const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', source], {encoding: 'utf8'});
      if (probe.error) throw probe.error;
      const [pictureWidth, pictureHeight] = probe.stdout.trim().split('x').map(Number);
      if (probe.status !== 0 || !pictureWidth || !pictureHeight) throw new Error('Cannot read picture dimensions');
      Object.assign(props, {pictureWidth, pictureHeight,
        isVideo: ['.mp4', '.mov', '.webm', '.mkv'].includes(extname(source).toLowerCase())});
    }
  }
  const propsFile = resolve(root, 'public', `${token}-props.json`);
  writeFileSync(propsFile, JSON.stringify(props));
  copies.push(propsFile);
  const renderArgs = ['render', 'src/index.jsx', job.composition, resolve(job.output), '--props', propsFile,
      '--frames', `0-${job.frames - 1}`, '--scale', String(job.width / 1920),
      '--fps', '30', '--image-format', 'png', '--color-space', 'bt709'];
  // Measured on Apple Silicon with 16 GB RAM; retain the conservative path elsewhere.
  const fastPhotoCamera = job.composition === 'PhotoCamera' && process.platform === 'darwin'
    && availableParallelism() >= 8 && totalmem() >= 12 * 1024 ** 3;
  const run = (options) => new Promise(resolveRun=>{
    const child=spawn(resolve(root, 'node_modules', '.bin', 'remotion'),
      [...renderArgs,...options,'--overwrite'],{cwd:root,stdio:'inherit'});
    child.once('error',error=>resolveRun({error}));child.once('exit',status=>resolveRun({status}));
  });
  let result = await run(job.composition==='GeographicMap'?['--gl','angle','--concurrency','1','--timeout','120000']:
    fastPhotoCamera ? ['--gl', 'angle', '--concurrency', '4'] : ['--concurrency', '2']);
  if (fastPhotoCamera && (result.error || result.status !== 0)) {
    console.error('PhotoCamera acceleration failed; retrying with the original render settings.');
    result = await run(['--concurrency', '2']);
  }
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  if(mapTiles)await mapTiles.close();
  for (const path of copies) if (existsSync(path)) unlinkSync(path);
}
