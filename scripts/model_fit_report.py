#!/usr/bin/env python3
"""Build a conservative model-fit scorecard from GokuAI benchmark reports."""
import argparse, json
from pathlib import Path

def newest(folder, pattern):
    files=list(Path(folder).glob(pattern)); return max(files,key=lambda p:p.stat().st_mtime) if files else None

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default=r'C:\gokuai');ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.root); manifest=json.loads((root/'models/model-manifest.json').read_text(encoding='utf-8-sig'))
    chat=newest(root/'benchmarks','model_benchmark_*.json')
    verify_dirs=sorted((root/'benchmarks').glob('model-verify-*'),key=lambda p:p.stat().st_mtime)
    verify=verify_dirs[-1]/'summary.json' if verify_dirs and (verify_dirs[-1]/'summary.json').exists() else None
    chat_data=json.loads(chat.read_text(encoding='utf-8-sig')) if chat else {}
    verify_data=json.loads(verify.read_text(encoding='utf-8-sig')) if verify else {}
    rows=[]
    aliases={'fast_coder':'goku-code','heavy_planner':'goku-heavy','dflash_draft':'goku-heavy-dflash'}
    for key,cfg in manifest.get('exl3',{}).items():
        alias=aliases[key]; score=chat_data.get('summary',{}).get(alias,{})
        q=score.get('quality'); speed=score.get('mean_seconds'); passed=score.get('success')
        fit='unvalidated' if q is None else ('primary' if q>=90 and passed==100 else 'secondary' if q>=75 else 'reject')
        rows.append({'model':key,'family':'chat','role':cfg.get('role'),'fit':fit,'quality_score':q,'mean_seconds':speed,'success_rate':passed})
    aux_by_name={}
    for r in verify_data.get('results',[]):
        if r.get('suite')=='aux': aux_by_name[r.get('worker','')]=r
    groups=[('embedding',manifest.get('embedding',{})),('reranker',manifest.get('reranker',{})),('vl',manifest.get('vl',{}))]
    for family,items in groups:
        for key,path in items.items():
            name=Path(path).name; smoke=next((v for k,v in aux_by_name.items() if name in k),None)
            status=smoke.get('status') if smoke else None
            rows.append({'model':key,'family':family,'path':path,'fit':'candidate' if status=='pass' else 'reject' if status=='fail' else 'unvalidated','smoke_status':status,'note':'Candidate means load/inference passed; retrieval/ranking task quality still requires corpus labels.'})
    payload={'schema':'goku-model-fit-v1','manifest':str(root/'models/model-manifest.json'),'chat_report':str(chat) if chat else None,'verification_report':str(verify) if verify else None,'decision_policy':{'primary':'quality >=90, 100% completion','secondary':'quality >=75','candidate':'auxiliary smoke pass only','reject':'failed or quality <75','unvalidated':'no current result'},'models':rows}
    Path(a.out).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps({'output':a.out,'models':len(rows)},indent=2))
if __name__=='__main__': main()
