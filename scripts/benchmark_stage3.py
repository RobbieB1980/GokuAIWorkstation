#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime, json, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark_models import post, score_response, cleaned_json

CASES=[
 {'id':'registry_port','weight':18,'query':'Forge RegistryObject DeferredRegister Blocks DeferredBlock registerSimpleBlock NeoForge migration','families':['neoforge_changes','neoforge_primers','generator_template'],'groups':[['DeferredRegister'],['DeferredBlock','DeferredHolder'],['RegistryObject']], 'task':'Repair a Forge 1.20.1 block and block-item registration for a later NeoForge target. Preserve registry ids, avoid invented APIs, and give compile plus registry validation.', 'expected':{'contains_any_groups':[['DeferredRegister'],['compile','gradle'],['registry id','registry names','ids']]}},
 {'id':'gradle_moddev','weight':16,'query':'NeoForge ModDevGradle pluginManagement repositories net.neoforged.moddev migration','families':['gradle','neoforge_changes','neoforge_primers'],'groups':[['pluginManagement','ModDevGradle'],['net.neoforged','NeoForge']], 'task':'Diagnose a NeoForge Gradle plugin-resolution failure. Separate evidence from assumptions and provide minimal checks and commands.', 'expected':{'contains_any_groups':[['plugin','repository'],['gradle'],['compile','build','resolution']]}},
 {'id':'data_components','weight':16,'query':'NeoForge item data components ItemStack CompoundTag migration attachments capabilities','families':['neoforge_changes','neoforge_primers'],'groups':[['data component','DataComponent'],['ItemStack','item stack']], 'task':'Plan migration of durable custom ItemStack NBT state to the target mechanism while preserving old saves. Do not invent signatures absent from evidence.', 'expected':{'contains_any_groups':[['component'],['legacy','old save','compatibility'],['serialization','round trip','round-trip']]}},
 {'id':'geckolib_migration','weight':16,'query':'GeckoLib 3 migration AnimationController controller registrar triggerable animation current','families':['geckolib'],'groups':[['AnimationController','controller'],['trigger','animation']], 'task':'Port GeckoLib 3 controller behavior: walk loop while moving, idle otherwise, and one triggered attack. Preserve names and speed; cite target evidence and require runtime checks.', 'expected':{'contains_any_groups':[['walk'],['idle'],['attack'],['compile','gradle'],['runtime','in-game','animation test']]}},
 {'id':'mapping_resolution','weight':18,'query':'SRG MCP Mojmap mappings namespace owner descriptor Minecraft version mapping conversion','families':['mappings'],'groups':[['srg','SRG'],['mcp','MCP'],['namespace','mapping']], 'task':'Design a deterministic SRG-to-readable mapping lookup for a converter. It must bind version, source/target namespace, symbol kind, owner and descriptor and reject ambiguity.', 'expected':{'contains_any_groups':[['version'],['source namespace','source mapping'],['target namespace','target mapping'],['owner'],['descriptor'],['ambiguous','no match']]}},
 {'id':'capability_lifecycle','weight':16,'query':'NeoForge capability migration LazyOptional invalidate block entity sided capability setRemoved','families':['neoforge_changes','neoforge_primers'],'groups':[['capability'],['invalidate','invalidation','setRemoved']], 'task':'Repair a block-entity capability that is cached forever and exposed identically on every side. Address lifecycle, sided behavior, and validation without guessing unsupported APIs.', 'expected':{'contains_any_groups':[['invalidate','invalidation','lifecycle'],['side','sided'],['unload','removal','setRemoved'],['test']]}},
]
def terms(q):return list(dict.fromkeys(re.findall(r'[A-Za-z_$][A-Za-z0-9_.$-]{2,}',q)))
def search(con,q,families,limit=6,oracle_groups=None):
    ts=terms(q); expr=' OR '.join('"'+x.replace('"','')+'"' for x in ts[:18]); rows=[]
    try: rows=con.execute('SELECT chunk_id,path,family,versions,text,bm25(chunks_fts) score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT 60',(expr,)).fetchall()
    except sqlite3.Error: pass
    scored=[]
    for cid,path,fam,vers,text,bm in rows:
        low=text.lower(); bonus=sum(1 for x in ts if x.lower() in low)*2+(5 if fam in families else 0)
        if oracle_groups:bonus+=sum(12 for g in oracle_groups if any(x.lower() in low for x in g))
        scored.append((bonus-float(bm or 0),cid,path,fam,vers,text))
    scored.sort(reverse=True);out=[];seen=set()
    for _,cid,path,fam,vers,text in scored:
        if cid in seen:continue
        seen.add(cid);out.append({'chunk_id':cid,'path':path,'family':fam,'versions':vers,'text':text[:1800]})
        if len(out)>=limit:break
    return out
def coverage(passages,groups):
    text='\n'.join(x['text'] for x in passages).lower();hits=[any(t.lower() in text for t in g) for g in groups]
    return round(100*sum(hits)/len(hits),2) if hits else 100.0,hits
def prompt(case,mode,passages):
    evidence='\n\n'.join(f"[source:{p['path']}]\n{p['text']}" for p in passages)
    return f"""You are repairing a Java Minecraft mod using ONLY local evidence below. Return JSON only with keys diagnosis,repair_plan,code_or_pseudocode,validation,citations,uncertainties. citations must be an array of exact source paths shown below. Do not claim an API is verified unless evidence supports it. Mode={mode}.\nTASK: {case['task']}\nLOCAL EVIDENCE:\n{evidence}"""
def citation_score(text,passages):
    obj=cleaned_json(text);paths={p['path'] for p in passages}
    if not isinstance(obj,dict) or not isinstance(obj.get('citations'),list):return 0.0,[]
    cited=[str(x) for x in obj['citations']];valid=[x for x in cited if x in paths]
    return (100.0*len(valid)/len(cited) if cited else 0.0),valid
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--index',default=r'C:\gokuai\DataIndex\goku-data.db');ap.add_argument('--output',required=True);ap.add_argument('--report-as',required=True);ap.add_argument('--worker-label',required=True);ap.add_argument('--url',default='http://127.0.0.1:11437/v1/chat/completions');a=ap.parse_args()
    con=sqlite3.connect(f"file:{Path(a.index).as_posix()}?mode=ro",uri=True);rows=[]
    for case in CASES:
      for mode in ('production','oracle'):
        q=case['query'] if mode=='production' else ' '.join(g[0] for g in case['groups'])+' '+case['query']; ps=search(con,q,case['families'],6,case['groups'] if mode=='oracle' else None); cov,hits=coverage(ps,case['groups'])
        print(f"[stage3] {a.report_as}: {case['id']} {mode} retrieval={cov}%",flush=True)
        try:
          text,sec,usage,finish,trunc=post(a.url,'goku-heavy',prompt(case,mode,ps),timeout=480,max_tokens_override=2200);base=score_response(text,case['expected'],trunc);cs,valid=citation_score(text,ps);ground=round(base['factual_score']*.65+cs*.20+cov*.15,2);quality=round(ground*.9+base['format_score']*.1,2)
          rows.append({'test':case['id'],'mode':mode,'weight':case['weight'],'ok':True,'quality_score':quality,'repair_score':base['factual_score'],'format_score':base['format_score'],'retrieval_recall':cov,'retrieval_hits':hits,'citation_score':round(cs,2),'valid_citations':valid,'passages':[{k:p[k] for k in ('chunk_id','path','family','versions')} for p in ps],'seconds':round(sec,3),'usage':usage,'finish_reason':finish,'truncated':trunc,'response':text[:12000]})
        except Exception as e:rows.append({'test':case['id'],'mode':mode,'weight':case['weight'],'ok':False,'quality_score':0,'repair_score':0,'retrieval_recall':cov,'error':str(e)})
    con.close(); modes={}
    for mode in ('production','oracle'):
      rs=[x for x in rows if x['mode']==mode];tw=sum(x['weight'] for x in rs);modes[mode]={'quality_score':round(sum(x['quality_score']*x['weight'] for x in rs)/tw,2),'retrieval_recall':round(sum(x['retrieval_recall']*x['weight'] for x in rs)/tw,2),'mean_seconds':round(sum(x.get('seconds',0) for x in rs if x.get('ok'))/max(1,sum(bool(x.get('ok')) for x in rs)),3)}
    report={'schema':'goku-grounded-java-repair-stage3-v1','created':datetime.datetime.now().isoformat(),'index':a.index,'model':a.report_as,'worker_label':a.worker_label,'modes':modes,'tests':rows};Path(a.output).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(modes,indent=2))
if __name__=='__main__':main()
