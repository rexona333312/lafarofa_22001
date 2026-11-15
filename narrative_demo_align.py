"""Align the known local demo narration using the project's cached WhisperX model."""
import json
import sys
import torch
import whisperx

torch.set_num_threads(4)
audio = whisperx.load_audio(sys.argv[1])
segments = json.loads(open(sys.argv[2], encoding='utf-8').read())
model, metadata = whisperx.load_align_model(language_code='en', device='cpu')
result = whisperx.align(segments, model, metadata, audio, 'cpu', return_char_alignments=False)
with open(sys.argv[3], 'w', encoding='utf-8') as file:
    json.dump(result, file, ensure_ascii=False, indent=2)
print('Aligned demo words:', len(result['word_segments']), flush=True)
