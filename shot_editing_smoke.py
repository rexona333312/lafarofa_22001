"""One local Apple model probe; no network or stock search."""
import json
import time
from pathlib import Path
from vision_ranker import _apple_rank

ROOT=Path(__file__).resolve().parent/'output/scene_shot_editing/verification'

if __name__=='__main__':
    plan={'query':'Men examining a large paper map at a table, medium shot',
          'text':'The men lean over the map to study the plan.',
          'search_mode':'broll','match_policy':'illustrative','_fast_vision':True,
          'shot_plan':{'role':'action','scale':'medium','pace':'normal','relation':'new_scene',
                       'goal':'Show discussion of a plan','action':'Men lean over a large paper map on a table'}}
    started=time.monotonic()
    result=_apple_rank(plan,[str(ROOT/'action_candidate.mp4')],2,print)
    report={'test':'Controlled concatenation: mountain / men examining paper / foundry. Three equal 3s sections.',
            'expected_window':1,'plan':plan,'results':result,
            'elapsed_seconds':round(time.monotonic()-started,2)}
    report['passed']=bool(result and result[0].get('relevant') and result[0].get('selected_window')==1)
    (ROOT/'apple_live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
