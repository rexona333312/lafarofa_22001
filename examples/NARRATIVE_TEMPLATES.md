# Формат новых шаблонов

Таймкоды печати и слов берутся из `word_timestamps` подготовленной озвучки. `word_range` в text_cue относится к исходному массиву WhisperX; `highlight_ranges` — к словам внутри своей фразы. Не передавай предполагаемые скорости речи.

```json
{
  "text_cues": [
    {"id":"T001","kind":"accent","template":"impact_typewriter","text":"new technology","chunk_index":0,"word_range":[0,2]},
    {"id":"T002","kind":"accent","template":"speech_words_grid","text":"as if something beneath it was displacing it","chunk_index":1,"word_range":[2,10]},
    {"id":"T003","kind":"accent","template":"selective_marker","text":"more power smaller chips and faster connections","chunk_index":2,"params":{"highlight_ranges":[[0,2],[2,4],[5,7]]}}
  ]
}
```

Серия состоит из обычных chunks с отдельными поисковыми планами. Например, следующий принцип работает одинаково для политических институтов, устройств и этапов работы:

```json
[
  {"type":"photo","start":0,"end":3,"query":"silicon wafer","entity":"silicon wafer","entity_type":"object","search_mode":"exact","source_policy":["archive","editorial"],"template":"photo_carousel_dark","params":{"carousel_group":"technology","archival":false}},
  {"type":"photo","start":3,"end":6,"query":"printed circuit board","entity":"printed circuit board","entity_type":"object","search_mode":"exact","source_policy":["archive","editorial"],"template":"photo_carousel_dark","params":{"carousel_group":"technology","archival":false}}
]
```

Карта-схема использует приблизительные координаты в кадре, без притязания на точные географические границы:

```json
{
  "type":"photo","start":0,"end":8,"query":"regional map","search_mode":"broll","source_policy":["archive","editorial"],"template":"map_annotations",
  "params":{"camera_zoom":1.25,"annotations":[
    {"kind":"route","points":[[0.2,0.7],[0.5,0.6],[0.7,0.4]],"label":"connection","start_frame":10,"draw_frames":35},
    {"kind":"region","points":[[0.6,0.3],[0.8,0.3],[0.8,0.6]],"label":"destination","start_frame":60,"draw_frames":35},
    {"kind":"point","points":[[0.7,0.45]],"label":"hub","start_frame":110,"draw_frames":21}
  ]}
}
```

При выборе содержимого используй только свой сценарий. Формулировки и координаты выше — примеры формата, не факты и не готовые реальные маршруты.
