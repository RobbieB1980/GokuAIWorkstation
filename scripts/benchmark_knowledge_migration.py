#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, re, sqlite3, time, urllib.request, urllib.error
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

MAX_EXCERPT_CHARS = 4000
PHYSICAL_CONTEXT_LINES = 16

SYSTEM = """You are being benchmarked as an RBLocalLLM Minecraft migration agent.
The benchmark controller has already resolved and opened authoritative exact-version local evidence before your first turn. Use that injected evidence first. Do not waste rounds rediscovering sources the controller already supplied.
Do not rely on memory when local evidence can answer the question. Do not claim compilation succeeded unless compilation output is supplied.
Return exactly one JSON object per turn, with no prose outside JSON.
Allowed actions:
  {\"action\":\"search_knowledge\",\"query\":\"...\",\"version\":\"1.20.1 or 26.2 only\",\"category\":\"optional\",\"limit\":8}
  {\"action\":\"read_reference\",\"evidence_id\":\"E1\",\"start_line\":1,\"end_line\":220}
  {\"action\":\"search_mappings\",\"symbol\":\"...\",\"minecraft_version\":\"1.20.1\",\"namespace\":\"optional\",\"limit\":20}
  {\"action\":\"resolve_mapping\",\"symbol\":\"...\",\"minecraft_version\":\"1.20.1\",\"source_namespace\":\"...\",\"target_namespace\":\"...\"}
  {\"action\":\"final\",\"target_version\":\"26.2\",\"summary\":\"...\",\"changes\":[...],\"claims\":[{\"statement\":\"...\",\"evidence_ids\":[\"E1\"]}],\"mapping_result\":\"... or null\",\"validation\":\"compile required\",\"status\":\"unverified until compilation\"}
Rules:
- The supplied mock class is authoritative 1.20.1 source evidence.
- The controller-injected transitive primer ledger explains migration history. Only cited exact 26.2 target_physical_source excerpts are authoritative for target API claims.
- The injected primer chain may contain intermediate versions. Unguided reads/searches of adjacent non-target versions remain blocked.
- You may make at most two unguided search_knowledge requests.
- If sufficient evidence is already present, return action=\"final\" immediately. Do not continue searching merely because rounds remain.
- Cite exact target_source evidence IDs for each concrete target API claim. Primer-only citations do not establish API existence.
- Never invent EntityRegistry, RegistryObject, or another replacement when the exact 26.2 source excerpt does not contain it.
- Preserve rbmock:mock_entity.
"""

MOCK_SOURCE = r'''// Mock Forge/Minecraft 1.20.1 source to migrate to NeoForge 26.2.
package example.mock;

import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MobCategory;
import net.minecraftforge.registries.DeferredRegister;
import net.minecraftforge.registries.ForgeRegistries;
import net.minecraftforge.registries.RegistryObject;

public final class ModEntities {
    public static final String MODID = "rbmock";
    public static final DeferredRegister<EntityType<?>> ENTITIES =
        DeferredRegister.create(ForgeRegistries.ENTITY_TYPES, MODID);

    public static final RegistryObject<EntityType<MockEntity>> MOCK = ENTITIES.register(
        "mock_entity",
        () -> EntityType.Builder.of(MockEntity::new, MobCategory.CREATURE)
            .sized(0.6F, 1.8F)
            .build(new ResourceLocation(MODID, "mock_entity").toString())
    );
}

// Build context: source project is Forge 1.20.1. Target is NeoForge 26.2.
// Requirement: preserve registry id rbmock:mock_entity and behavior; do not invent target APIs.
'''


def active_db(canonical: Path) -> Path:
    pointer = canonical.parent / "_ACTIVE_DB.txt"
    try: name = pointer.read_text(encoding="utf-8-sig").strip()
    except OSError: name = ""
    candidate = canonical.parent / name if name else canonical
    return candidate if candidate.exists() else canonical


def safe_query(q: str) -> str:
    toks = re.findall(r"[A-Za-z0-9_.$:/#-]+", q)
    return " AND ".join(f'"{t}"' for t in toks[:12]) if toks else '""'

def sqlite_read_only(path: Path):
    connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    return connection

def version_key(version):
    value=str(version or '').strip()
    if not re.fullmatch(r'\d+(?:\.\d+)*',value): return None
    return tuple(int(x) for x in value.split('.'))


def version_between(version,source_version,target_version):
    key=version_key(version); source=version_key(source_version); target=version_key(target_version)
    return key is not None and source is not None and target is not None and source < key <= target
class Knowledge:
    def __init__(self, root: Path):
        self.root = root
        self.db = active_db(root / "knowledge" / "Index" / "knowledge.db")
        if not self.db.exists():
            # versioned DBs may not use the canonical filename; pointer usually resolves this.
            ptr = root / "knowledge" / "Index" / "_ACTIVE_DB.txt"
            if ptr.exists(): self.db = root / "knowledge" / "Index" / ptr.read_text(encoding="utf-8-sig").strip()
        self.mdb = active_db(root / "knowledge" / "Minecraft_Mappings_Corpus" / "mappings.db")
        self.evidence = {}
        self.next_id = 1

    def connect(self):
        return sqlite_read_only(self.db)

    def search(self, query, version="", category="", limit=8):
        limit=max(1,min(int(limit),20)); sql='''SELECT f.path,f.physical_path,f.source_id,f.category,f.version,ch.start_line,ch.end_line,
        snippet(chunks_fts,0,'[',']',' ... ',18) snippet,bm25(chunks_fts) rank
        FROM chunks_fts JOIN chunks ch ON ch.id=CAST(chunks_fts.chunk_id AS INTEGER)
        JOIN files f ON f.id=ch.file_id WHERE chunks_fts MATCH ?'''; params=[safe_query(query)]
        if version: sql+=' AND f.version=?'; params.append(version)
        if category: sql+=' AND f.category=?'; params.append(category)
        sql+=" ORDER BY CASE WHEN f.category LIKE 'ExactSource:%' THEN 0 ELSE 1 END, rank LIMIT ?"; params.append(limit)
        try:
            with self.connect() as c: rows=[dict(r) for r in c.execute(sql,params)]
        except Exception as exc: return {"error":str(exc),"results":[]}
        return {"results":self._register_rows(rows)}

    def target_evidence_search(self, version="26.2", limit=12):
        """Exact-version, target-specific retrieval. Uses several focused FTS probes and deduplicates by file/chunk."""
        queries=[
          "DeferredRegister",
          "EntityType",
          "RegistryObject",
          "entity registration",
          "registries entity",
        ]
        gathered=[]; seen=set()
        for q in queries:
            result=self.search(q,version=version,limit=limit)
            for row in result.get('results') or []:
                key=(row.get('physical_path'),row.get('start_line'),row.get('end_line'))
                if key in seen: continue
                seen.add(key); gathered.append(row)
                if len(gathered)>=limit: break
            if len(gathered)>=limit: break
        return {"version":version,"queries":queries,"results":gathered}

    def evidence_text(self, evidence_id, max_chars=24000):
        meta=self.evidence.get(evidence_id)
        if not meta: return ""
        p=Path(meta.get('physical_path') or '')
        if not p.is_file(): return str(meta.get('snippet') or '')
        try: text=p.read_text(encoding='utf-8',errors='replace')
        except OSError: return str(meta.get('snippet') or '')
        start=int(meta.get('start_line') or 0); end=int(meta.get('end_line') or 0)
        if start>0 and end>=start:
            lines=text.splitlines(); text='\n'.join(lines[start-1:min(end,len(lines))])
        return text[:max_chars]

    def _register_rows(self, rows):
        out=[]
        for r in rows:
            r=dict(r)
            eid=f"E{self.next_id}"; self.next_id+=1
            self.evidence[eid]=r
            out.append({"evidence_id":eid,**r})
        return out

    def resolve_reference(self, kind, version, limit=8):
        """Deterministically resolve exact-version reference entrypoints without FTS."""
        kind=(kind or '').strip().lower(); version=(version or '').strip(); limit=max(1,min(int(limit),20))
        rules={
          'primer': ("category='Upstream:neoforge_primers'", []),
          'minecraft_reference': ("category='Minecraft_Java_Server_Client'", []),
          'mcpconfig': ("category='Upstream:mcpconfig'", []),
          'gradle': ("(category='Upstream:gradle' OR lower(path) LIKE '%gradle%')", []),
        }
        if kind not in rules: return {"error":"unsupported reference kind","allowed":sorted(rules),"results":[]}
        where,extra=rules[kind]
        sql=f"""SELECT path,physical_path,source_id,category,version,0 start_line,0 end_line,'' snippet,0.0 rank
                 FROM files WHERE version=? AND {where}
                 ORDER BY CASE
                   WHEN lower(path) LIKE '%/index.md' THEN 0
                   WHEN lower(path) LIKE '%/_source.json' THEN 1
                   WHEN lower(path) LIKE '%/version.json' THEN 2
                   WHEN lower(path) LIKE '%config.json' THEN 3
                   ELSE 10 END, length(path), path LIMIT ?"""
        with self.connect() as c: rows=[dict(r) for r in c.execute(sql,[version,*extra,limit])]
        return {"kind":kind,"version":version,"results":self._register_rows(rows)}

    def primer_chain(self,source_version='1.20.1',target_version='26.2',limit=128):
        with self.connect() as c:
            rows=[dict(r) for r in c.execute("SELECT path,physical_path,source_id,source_root,category,version,0 start_line,0 end_line,'' snippet,0.0 rank FROM files WHERE category='Upstream:neoforge_primers'")]
        rows=[r for r in rows if version_between(r.get('version'),source_version,target_version)]
        rows.sort(key=lambda r:version_key(r.get('version')) or ())
        out=[]; seen=set()
        for row in rows:
            if row['version'] in seen: continue
            seen.add(row['version']); out.append(row)
        return {"source_version":source_version,"target_version":target_version,"selection_rule":"source_version < primer_version <= target_version","versions":[r['version'] for r in out],"results":self._register_rows(out[:limit])}

    def exact_source_root(self,loader='neoforge',version='26.2'):
        folder={'neoforge':'NeoForge','minecraft':'Minecraft'}.get(str(loader).lower())
        if not folder: return None,{"error":"unsupported loader"}
        root=(self.root/'knowledge'/'Exact_Version_Sources'/folder/version).resolve()
        manifest_path=root/'.rb-source-version.json'
        if not manifest_path.is_file(): return None,{"error":"EXACT_VERSION_SOURCE_NOT_MATERIALIZED","expected_manifest":str(manifest_path)}
        try: manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        except Exception as exc: return None,{"error":"INVALID_EXACT_VERSION_SOURCE_MANIFEST","detail":str(exc)}
        if str(manifest.get('version'))!=version or str(manifest.get('loader','')).lower()!=str(loader).lower():
            return None,{"error":"EXACT_VERSION_SOURCE_MISMATCH","requested_version":version,"manifest_version":manifest.get('version'),"source_root":str(root)}
        manifest['source_root']=str(root); manifest['physical_path']=str(root)
        return root,manifest

    def grep_physical_source(self,query,version='26.2',loader='neoforge',limit=8,context_lines=PHYSICAL_CONTEXT_LINES):
        root,manifest=self.exact_source_root(loader,version)
        if root is None: return {**manifest,"results":[]}
        stop={'the','and','for','from','with','into','using','entity','registration','migration'}
        terms=[]
        for token in re.findall(r'[A-Za-z_$][A-Za-z0-9_.$-]{2,}',query or ''):
            if token.lower() not in stop and token.lower() not in {x.lower() for x in terms}: terms.append(token)
        terms=terms[:12]; candidates=[]; allowed={'.java','.kt','.kts','.gradle','.json','.toml','.md'}; skipped={'.git','.gradle','build','out','runs','node_modules'}
        ctx=max(0,min(int(context_lines),20))
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in allowed or any(x in skipped for x in path.parts): continue
            try: lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
            except OSError: continue
            best=None; rel=str(path.relative_to(root)).replace('\\','/'); low=rel.lower(); stem=path.stem.lower()
            for index,line in enumerate(lines,1):
                matched=[term for term in terms if term.lower() in line.lower()]
                if not matched: continue
                score=_score_grep_line(line,matched,stem,low,terms)
                if best is None or score>best[0]: best=(score,index,matched,line)
            if best is None: continue
            score,index,matched,line=best
            candidates.append({"path":rel,"physical_path":str(path),"source_id":f"exact_{loader}_{version}","source_root":str(root),"category":f"ExactSource:{loader}","version":version,"start_line":max(1,index-ctx),"end_line":min(len(lines),index+ctx),"snippet":line.strip(),"rank":-score,"evidence_kind":"target_source","commit":manifest.get('commit'),"matched_terms":matched})
        candidates.sort(key=lambda r:(r['rank'],len(r['path']),r['path']))
        return {"loader":loader,"version":version,"query":query,"source_verification":manifest,"results":self._register_rows(candidates[:max(1,min(int(limit),20))])}

    def primer_chain_evidence(self,chain,query,limit=12):
        terms=[x for x in re.findall(r'[A-Za-z_$][A-Za-z0-9_.$-]{2,}',query or '') if x.lower() not in {'the','and','for','from','with','entity','registration','migration'}][:12]
        rows=[]
        for item in chain.get('results') or []:
            meta=self.evidence.get(item.get('evidence_id')) or item
            path=Path(meta.get('physical_path') or '')
            if not path.is_file(): continue
            lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
            best=None
            for index,line in enumerate(lines,1):
                matched=[term for term in terms if term.lower() in line.lower()]
                if not matched: continue
                score=_score_grep_line(line,matched,path.stem.lower(),str(path).replace('\\','/').lower(),terms)
                if best is None or score>best[0]: best=(score,index,matched,line)
            if best:
                score,index,matched,line=best
                rows.append({**meta,"start_line":max(1,index-PHYSICAL_CONTEXT_LINES),"end_line":min(len(lines),index+PHYSICAL_CONTEXT_LINES),"snippet":line.strip(),"evidence_kind":"primer_delta","matched_terms":matched})
            if len(rows)>=limit: break
        return {"versions":[r.get('version') for r in rows],"results":self._register_rows(rows)}
    def follow_links(self, evidence_id, limit=12):
        meta=self.evidence.get(evidence_id)
        if not meta: return {"error":"unknown evidence_id","results":[]}
        p=Path(meta.get('physical_path') or '')
        if not p.is_file(): return {"error":"indexed file unavailable","results":[]}
        text=p.read_text(encoding='utf-8',errors='replace')
        raw=[]
        for m in re.finditer(r'\[[^\]]+\]\(([^)]+)\)',text):
            target=m.group(1).strip().split('#',1)[0].strip()
            if not target or '://' in target or target.startswith('#'): continue
            cand=(p.parent/target).resolve()
            raw.append(str(cand))
        # Also capture simple markdown/reference filenames in code/text when they exist beside the primer.
        seen=[]
        for x in raw:
            if x not in seen: seen.append(x)
        rows=[]
        with self.connect() as c:
            for target in seen:
                row=c.execute("SELECT path,physical_path,source_id,category,version,0 start_line,0 end_line,'' snippet,0.0 rank FROM files WHERE physical_path=? LIMIT 1",(target,)).fetchone()
                if row and (not meta.get('version') or row['version']==meta.get('version')):
                    rows.append(dict(row))
                if len(rows)>=max(1,min(int(limit),30)): break
        return {"source_evidence_id":evidence_id,"results":self._register_rows(rows)}

    def read(self, evidence_id, start=1, end=220):
        meta=self.evidence.get(evidence_id)
        if not meta: return {"error":"unknown evidence_id"}
        p=Path(meta.get("physical_path") or "")
        if not p.is_file(): return {"error":"indexed file unavailable","evidence_id":evidence_id,"path":str(p)}
        lines=p.read_text(encoding="utf-8",errors="replace").splitlines(); start=max(1,int(start)); end=max(start,min(int(end),start+500))
        return {"evidence_id":evidence_id,"path":meta.get("path"),"physical_path":str(p),"category":meta.get("category"),"version":meta.get("version"),
                "lines":[{"line":i+1,"text":lines[i]} for i in range(start-1,min(end,len(lines)))]}

    def mapping_probe(self):
        if not self.mdb.exists(): return None
        with sqlite_read_only(self.mdb) as c:
            c.row_factory=sqlite3.Row
            row=c.execute('''SELECT sy.minecraft_version,sy.namespace_from,sy.namespace_to,sy.name_from,sy.name_to,sy.kind,so.physical_path source_path
                             FROM symbols sy JOIN sources so ON so.id=sy.source_id
                             WHERE sy.minecraft_version='1.20.1' AND sy.name_from<>'' AND sy.name_to<>''
                             ORDER BY CASE sy.kind WHEN 'class' THEN 0 WHEN 'method' THEN 1 ELSE 2 END LIMIT 1''').fetchone()
            return dict(row) if row else None

    def search_mappings(self,symbol,version="",namespace="",limit=20):
        if not self.mdb.exists(): return {"error":"mapping DB missing","results":[]}
        sql='''SELECT sy.minecraft_version,sy.namespace_from,sy.namespace_to,sy.kind,sy.owner_from,sy.owner_to,sy.name_from,sy.name_to,sy.signature,so.physical_path source_path
               FROM symbols sy JOIN sources so ON so.id=sy.source_id WHERE (sy.name_from LIKE ? OR sy.name_to LIKE ?)'''; params=[f"%{symbol}%",f"%{symbol}%"]
        if version: sql+=' AND sy.minecraft_version=?'; params.append(version)
        if namespace: sql+=' AND (sy.namespace_from=? OR sy.namespace_to=?)'; params += [namespace,namespace]
        sql+=' LIMIT ?'; params.append(max(1,min(int(limit),50)))
        with sqlite_read_only(self.mdb) as c:
            c.row_factory=sqlite3.Row; return {"results":[dict(r) for r in c.execute(sql,params)]}

    def resolve_mapping(self,symbol,version,source_ns,target_ns,max_hops=3):
        if not self.mdb.exists(): return {"error":"mapping DB missing"}
        def neighbors(c,ns,sym):
            rows=c.execute('''SELECT sy.namespace_from,sy.namespace_to,sy.kind,sy.owner_from,sy.owner_to,sy.name_from,sy.name_to,sy.signature,so.physical_path source_path
              FROM symbols sy JOIN sources so ON so.id=sy.source_id WHERE sy.minecraft_version=? AND ((sy.namespace_from=? AND sy.name_from=?) OR (sy.namespace_to=? AND sy.name_to=?))''',(version,ns,sym,ns,sym)).fetchall()
            out=[]
            for r in rows:
                r=dict(r)
                if r['namespace_from']==ns and r['name_from']==sym: out.append((r['namespace_to'],r['name_to'],r,'forward'))
                if r['namespace_to']==ns and r['name_to']==sym: out.append((r['namespace_from'],r['name_from'],r,'reverse'))
            return out
        with sqlite_read_only(self.mdb) as c:
            c.row_factory=sqlite3.Row; q=[(source_ns,symbol,[],0)]; seen={(source_ns,symbol)}
            while q:
                ns,sym,path,h=q.pop(0)
                if h>=max_hops: continue
                for nns,nsym,edge,d in neighbors(c,ns,sym):
                    np=path+[{**edge,"direction":d}]
                    if nns==target_ns: return {"input":symbol,"version":version,"source_namespace":source_ns,"target_namespace":target_ns,"result":nsym,"path":np}
                    if (nns,nsym) not in seen: seen.add((nns,nsym)); q.append((nns,nsym,np,h+1))
        return {"input":symbol,"version":version,"source_namespace":source_ns,"target_namespace":target_ns,"result":None,"error":"No translation path found"}

    def version_inventory(self):
        with self.connect() as c:
            rows=[dict(r) for r in c.execute("SELECT version,category,source_id,COUNT(*) files FROM files WHERE version<>'' GROUP BY version,category,source_id ORDER BY version,category")]
        return rows

    def exact_version_files(self, version, limit=20):
        with self.connect() as c:
            rows=[dict(r) for r in c.execute("SELECT path,physical_path,source_id,category,version FROM files WHERE version=? ORDER BY source_id,category,path LIMIT ?",(version,limit))]
        return rows

    def coverage(self):
        primer=self.resolve_reference('primer','26.2',8)
        primer_chain=self.primer_chain('1.20.1','26.2',128)
        mc1201=self.resolve_reference('minecraft_reference','1.20.1',8)
        mcp1201=self.resolve_reference('mcpconfig','1.20.1',8)
        gradle261=self.resolve_reference('gradle','26.2',8)
        physical_probe=self.grep_physical_source('DeferredRegister createEntities registerEntityType','26.2','neoforge',8)
        probe=self.mapping_probe()
        exact={"1.20.1":self.exact_version_files("1.20.1"),"26.2":self.exact_version_files("26.2")}
        fts_diag={
          "source_api_terms": self.search("DeferredRegister",version="1.20.1",limit=8),
          "target_api_terms": self.search("createEntities",version="26.2",limit=8),
          "target_general_terms": self.search("DeferredRegister",version="26.2",limit=8),
          "gradle_terms": self.search("ModDevGradle",version="26.2",limit=8),
        }
        chain_versions=primer_chain.get('versions') or []
        physical_ids=[row.get('evidence_id') for row in (physical_probe.get('results') or []) if row.get('evidence_id')]
        invented_regression=_semantic_support('NeoForge 26.2 uses EntityRegistry for entity registration.',physical_ids,self)
        generic_regression=_semantic_support('NeoForge 26.2 uses DeferredRegister for entity registration.',physical_ids,self)
        deterministic={
          "mock_source_supplied": True,
          "mapping_1_20_1": probe is not None,
          "primer_26_2": bool(primer.get('results')),
          "transitive_primer_chain": bool(chain_versions) and chain_versions[-1]=='26.2',
          "minecraft_reference_1_20_1": bool(mc1201.get('results')),
          "mcpconfig_1_20_1": bool(mcp1201.get('results')),
          "gradle_26_1": bool(gradle261.get('results')),
          "exact_physical_source_26_2": not bool(physical_probe.get('error')),
          "physical_source_symbols_26_2": any(term in ' '.join((row.get('snippet') or '') for row in (physical_probe.get('results') or [])) for term in ('createEntities','registerEntityType')),
          "fts_target_api_26_2": bool((fts_diag.get('target_api_terms') or {}).get('results')),
          "claim_scorer_rejects_invented_api": invented_regression.get('status')=='UNSUPPORTED',
          "claim_scorer_requires_concrete_entity_symbol": generic_regression.get('status')=='UNSUPPORTED',
        }
        required=('mock_source_supplied','mapping_1_20_1','primer_26_2','transitive_primer_chain','exact_physical_source_26_2','physical_source_symbols_26_2','fts_target_api_26_2','claim_scorer_rejects_invented_api','claim_scorer_requires_concrete_entity_symbol')
        required_ok=all(deterministic[key] for key in required)
        missing=[key for key in required if not deterministic[key]]
        return {"checks":deterministic,"required_ok":required_ok,"failure_reason":None if required_ok else 'Missing required exact-version evidence: '+', '.join(missing),
                "mapping_probe":probe,"knowledge_db":str(self.db),"mapping_db":str(self.mdb),
                "resolved_entrypoints":{"primer_26_2":primer,"primer_chain_1_20_1_to_26_1":primer_chain,"minecraft_reference_1_20_1":mc1201,"mcpconfig_1_20_1":mcp1201,"gradle_26_1":gradle261},
                "physical_source_probe":physical_probe,"scoring_regression":{"invented_api":invented_regression,"generic_entity_api":generic_regression},"exact_version_files":exact,"version_inventory":self.version_inventory(),
                "fts_diagnostics":{k:len(v.get('results') or []) for k,v in fts_diag.items()},"fts_raw":fts_diag}
def post_json(url,payload,timeout=1800):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors='replace'); raise RuntimeError(f"HTTP {e.code}: {body}")


def extract_json(text):
    text=(text or '').strip()
    if not text: raise ValueError('empty model response')
    candidates=[]
    candidates.extend(m.group(1).strip() for m in re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```',text,re.S|re.I))
    candidates.append(text)
    decoder=json.JSONDecoder()
    for start,ch in enumerate(text):
        if ch!='{': continue
        try:
            obj,end=decoder.raw_decode(text[start:])
            if isinstance(obj,dict): return obj
        except Exception: pass
    for candidate in candidates:
        for repaired in (candidate,re.sub(r',\s*([}\]])',r'\1',candidate)):
            try:
                obj=json.loads(repaired)
                if isinstance(obj,dict): return obj
            except Exception: pass
    raise ValueError('no valid JSON action object found')


def router_status():
    with urllib.request.urlopen('http://127.0.0.1:11436/health',timeout=10) as r: return json.load(r)


def _compact_read(result, max_chars=2800):
    if not isinstance(result, dict): return result
    out={k:result.get(k) for k in ('evidence_id','path','physical_path','category','version','error') if k in result}
    lines=result.get('lines') or []
    text='\n'.join(f"{x.get('line')}: {x.get('text','')}" for x in lines)
    if len(text)>max_chars: text=text[:max_chars]+"\n...[controller evidence truncated]"
    out['content']=text
    out['line_count']=len(lines)
    return out


def controller_evidence(k:Knowledge, coverage):
    """Build a compressed transitive primer ledger and exact-target physical-source packet."""
    trace=[]; bundle={"source":{"kind":"supplied_mock","version":"1.20.1","content":MOCK_SOURCE}}
    chain=k.primer_chain('1.20.1','26.2',128)
    trace.append({"round":0,"action":"controller_resolve_primer_chain","request":{"source_version":"1.20.1","target_version":"26.2"},"result_summary":{"versions":chain.get('versions'),"count":len(chain.get('versions') or [])}})
    primer_hits=k.primer_chain_evidence(chain,'DeferredRegister EntityType RegistryObject createEntities registerEntityType',12)
    ledger=[]
    for item in (primer_hits.get('results') or [])[:4]:
        rd=k.read(item['evidence_id'],item.get('start_line') or 1,item.get('end_line') or 80)
        trace.append({"round":0,"action":"controller_read_reference","request":{"evidence_id":item['evidence_id'],"start_line":item.get('start_line'),"end_line":item.get('end_line')},"result_summary":{**{x:rd.get(x) for x in ('evidence_id','path','physical_path','category','version','error')},"line_count":len(rd.get('lines',[]))}})
        compact=_compact_read(rd,700); compact['evidence_kind']='primer_delta'; ledger.append(compact)
    bundle['migration_ledger']={"source_version":"1.20.1","target_version":"26.2","selection_rule":"source_version < primer_version <= target_version","primer_chain":chain.get('versions') or [],"relevant_deltas":ledger}

    source_results=[]
    for query in ('DeferredRegister','createEntities registerEntityType','DeferredHolder EntityType'):
        found=k.grep_physical_source(query,'26.2','neoforge',5)
        trace.append({"round":0,"action":"controller_grep_physical_source","request":{"loader":"neoforge","version":"26.2","query":query},"result_summary":{"error":found.get('error'),"source_verification":found.get('source_verification'),"results":[{x:r.get(x) for x in ('evidence_id','path','physical_path','source_root','version','start_line','end_line','commit')} for r in (found.get('results') or [])]}})
        for item in (found.get('results') or [])[:2]:
            if item['evidence_id'] not in {x['evidence_id'] for x in source_results}: source_results.append(item)
    source_reads=[]
    for item in source_results[:4]:
        rd=k.read(item['evidence_id'],item.get('start_line') or 1,item.get('end_line') or 80)
        trace.append({"round":0,"action":"controller_read_physical_source","request":{"evidence_id":item['evidence_id'],"version":"26.2"},"result_summary":{**{x:rd.get(x) for x in ('evidence_id','path','physical_path','category','version','error')},"line_count":len(rd.get('lines',[]))}})
        compact=_compact_read(rd,2000); compact.update({"evidence_kind":"target_source","source_root":item.get('source_root'),"commit":item.get('commit')}); source_reads.append(compact)
    source_root,source_manifest=k.exact_source_root('neoforge','26.2')
    bundle['target_physical_source']={"verification":source_manifest,"excerpts":source_reads,"claim_rule":"Target API claims require a cited target_source excerpt; primers alone are insufficient."}

    rr=k.resolve_reference('minecraft_reference','1.20.1',4)
    trace.append({"round":0,"action":"controller_resolve_reference","request":{"kind":"minecraft_reference","version":"1.20.1"},"result_summary":rr})
    rows=rr.get('results') or []
    if rows:
        rd=k.read(rows[0]['evidence_id'],1,40); bundle['source_reference']=_compact_read(rd,800)
        trace.append({"round":0,"action":"controller_read_reference","request":{"evidence_id":rows[0]['evidence_id'],"start_line":1,"end_line":40},"result_summary":{**{x:rd.get(x) for x in ('evidence_id','path','physical_path','category','version','error')},"line_count":len(rd.get('lines',[]))}})

    probe=coverage.get('mapping_probe')
    if probe:
        mr=k.resolve_mapping(probe['name_from'],probe['minecraft_version'],probe['namespace_from'],probe['namespace_to'])
        trace.append({"round":0,"action":"controller_resolve_mapping","request":{"symbol":probe['name_from'],"minecraft_version":probe['minecraft_version'],"source_namespace":probe['namespace_from'],"target_namespace":probe['namespace_to']},"result_summary":mr})
        bundle['mapping_probe_result']=mr
    encoded=json.dumps(bundle,ensure_ascii=False)
    bundle['packet_chars']=len(encoded)
    bundle['packet_budget_chars']=9000
    if len(json.dumps(bundle,ensure_ascii=False))>9000:
        bundle['migration_ledger']['relevant_deltas']=bundle['migration_ledger']['relevant_deltas'][:2]
        bundle['target_physical_source']['excerpts']=bundle['target_physical_source']['excerpts'][:3]
        bundle['packet_truncated']=True
        bundle['packet_chars']=len(json.dumps(bundle,ensure_ascii=False))
    return bundle,trace
def run_agent(alias,label,k:Knowledge,coverage,max_rounds=10,completion=4000):
    probe=coverage.get('mapping_probe')
    injected,trace=controller_evidence(k,coverage)
    user={"task":"Migrate the supplied mock Forge/Minecraft Java 1.20.1 entity registration source to NeoForge 26.2 using the LOCAL knowledge evidence injected by the controller.",
          "controller_evidence":injected,
          "requirements":["use the compressed transitive primer ledger for migration history","use exact 26.2 target_physical_source excerpts for target API claims","the supplied mock class is authoritative 1.20.1 source evidence","preserve rbmock:mock_entity","do not claim compilation succeeded","cite target_source evidence IDs in each target API claim","return action=final as soon as evidence is sufficient","return action=insufficient_evidence rather than inventing unsupported target APIs"],
          "mapping_probe": None if not probe else {"minecraft_version":probe['minecraft_version'],"symbol":probe['name_from'],"source_namespace":probe['namespace_from'],"target_namespace":probe['namespace_to'],"controller_result":injected.get('mapping_probe_result')}}
    messages=[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps(user,ensure_ascii=False)}]
    max_prompt=0; total_completion=0; final=None; error=None; empty_searches={}; unguided_searches=0; json_recovery_attempts=0
    for round_no in range(1,max_rounds+1):
        # After two model tool rounds, explicitly push toward a final answer if evidence is sufficient.
        # Append onto the last user turn. A second consecutive user message 500s
        # Ministral's [INST] / peg-native template.
        if round_no>2:
            policy="CONTROLLER_POLICY: Authoritative evidence was already injected. If it is sufficient, return action=final now. You have at most two unguided search_knowledge requests total."
            if messages and messages[-1].get('role')=='user':
                messages[-1]['content']=str(messages[-1].get('content') or '')+'\n'+policy
            else:
                messages.append({"role":"user","content":policy})
        t0=time.time()
        try:
            resp=post_json('http://127.0.0.1:11436/v1/chat/completions',{"model":alias,"messages":messages,"temperature":0.1,"max_tokens":completion})
        except Exception as exc:
            error=f"inference/tool-loop failure on round {round_no}: {exc}"
            trace.append({"round":round_no,"action":"inference_error","seconds":round(time.time()-t0,3),"error":str(exc)})
            break
        dt=time.time()-t0; choice=resp['choices'][0]; text=choice['message'].get('content') or ''; usage=resp.get('usage') or {}
        max_prompt=max(max_prompt,int(usage.get('prompt_tokens') or 0)); total_completion += int(usage.get('completion_tokens') or 0)
        try: obj=extract_json(text)
        except Exception as exc:
            json_recovery_attempts += 1
            trace.append({"round":round_no,"action":"invalid_json_action","seconds":round(dt,3),"usage":usage,"error":str(exc),"response_preview":text[:1000]})
            if json_recovery_attempts<=2:
                messages.append({"role":"assistant","content":text})
                messages.append({"role":"user","content":"FORMAT_ERROR: Return exactly one valid JSON action object with no markdown or outside text. Preserve the same evidence IDs and claims."})
                continue
            error=f"invalid JSON action after {json_recovery_attempts} attempts: {exc}: {text[:500]}"; break
        action=obj.get('action')
        row={"round":round_no,"action":action,"request":obj,"seconds":round(dt,3),"usage":usage}
        if resp.get("timings") is not None: row["timings"] = resp.get("timings")
        if action in ('final','insufficient_evidence'): final=obj; trace.append(row); break
        if action=='search_knowledge':
            unguided_searches += 1
            version=str(obj.get('version','')).strip()
            if version and version not in ('1.20.1','26.2'):
                result={"error":"ADJACENT_VERSION_BLOCKED","requested_version":version,"allowed_versions":["1.20.1","26.2"],"notice":"This benchmark requires exact-version evidence; 26.1/1.21.x evidence is blocked for unguided search; use injected primer chain + exact 26.2 target source."}
            elif unguided_searches>2:
                result={"error":"UNGUIDED_SEARCH_LIMIT","limit":2,"notice":"Authoritative evidence is already injected. Return action=final or read an existing evidence_id."}
            else:
                sig=(obj.get('query','').strip().lower(),version,obj.get('category','').strip())
                if empty_searches.get(sig,0)>=1:
                    result={"error":"REPEATED_EMPTY_SEARCH_BLOCKED","notice":"Do not repeat an empty search. Use injected evidence or return action=final."}
                else:
                    result=k.search(obj.get('query',''),version,obj.get('category',''),obj.get('limit',8))
                    if not result.get('results'):
                        empty_searches[sig]=1
                        result['empty_search_notice']='No exact matching content hit. This identical search is now blocked. Use injected evidence or return action=final.'
        elif action=='read_reference': result=k.read(obj.get('evidence_id',''),obj.get('start_line',1),obj.get('end_line',220))
        elif action=='search_mappings': result=k.search_mappings(obj.get('symbol',''),obj.get('minecraft_version',''),obj.get('namespace',''),obj.get('limit',20))
        elif action=='resolve_mapping': result=k.resolve_mapping(obj.get('symbol',''),obj.get('minecraft_version',''),obj.get('source_namespace',''),obj.get('target_namespace',''))
        elif action in ('resolve_reference','follow_reference_links'):
            result={"error":"CONTROLLER_OWNED_ACTION","notice":"The controller already resolved exact-version entrypoints and primer links before inference. Use the injected evidence or request read_reference/search_knowledge if truly needed."}
        else: result={"error":"unsupported action","allowed":["search_knowledge","read_reference","search_mappings","resolve_mapping","final","insufficient_evidence"]}
        row['result_summary']=result if action!='read_reference' else {**{x:result.get(x) for x in ('evidence_id','path','physical_path','category','version','error')},"line_count":len(result.get('lines',[]))}
        trace.append(row); messages.append({"role":"assistant","content":json.dumps(obj)}); messages.append({"role":"user","content":"TOOL_RESULT\n"+json.dumps(result,ensure_ascii=False)})
    status=router_status(); ctx=status.get('aliases',{}).get(alias,{}).get('context')
    score=score_run(final,trace,coverage,k,probe)
    return {"model":label,"alias":alias,"score":score,"final":final,"error":error,"tool_trace":trace,
            "controller_evidence":{"injected":True,"evidence_ids":sorted(k.evidence.keys()),"unguided_searches_used":unguided_searches,"json_recovery_attempts":json_recovery_attempts},
            "context":{"configured":ctx,"max_prompt_tokens":max_prompt,"completion_tokens_total":total_completion,"peak_utilization_pct": round(max_prompt*100/ctx,1) if ctx else None},
            "runtime":{"flash_attention":status.get('flash_attention'),"post_load_gpu":status.get('post_load_gpu'),"no_cpu_layer_spill":status.get('no_cpu_layer_spill'),"capabilities":status.get('runtime_capabilities'),"router_policy":status.get('router_policy')}}

def _score_grep_line(line, matched, path_stem, rel_lower, query_terms=None):
    score=10*len(matched)
    stripped=line.strip()
    if stripped.startswith(('//','*','/*','*/','#')): score-=30
    if stripped.startswith(('import ','package ')): score-=25
    if '/src/main/' in '/'+rel_lower: score+=8
    if 'test' in rel_lower: score-=8
    if re.search(r'\b(class|interface|record|enum)\b',line): score+=8
    if re.search(r'\b(public|protected|private|static|final)\b',line): score+=12
    stem=path_stem.lower()
    specific=[term for term in matched if term.lower().split('.')[-1]!=stem]
    if specific: score+=40*len(specific)
    elif any(term.lower().split('.')[-1]!=stem for term in (query_terms or matched)): score-=15
    for term in matched:
        simple=term.split('.')[-1]
        if stem==simple.lower(): score+=20
        if re.search(rf'(?<![A-Za-z0-9_]){re.escape(simple)}(?![A-Za-z0-9_])',line): score+=15
        if re.search(rf'\b{re.escape(simple)}\s*\(',line): score+=25
    return score


def _symbol_aliases(symbol):
    clean=(symbol or '').split('(')[0]
    aliases=[clean]
    simple=clean.split('.')[-1]
    if simple and simple not in aliases: aliases.append(simple)
    return aliases


def _api_symbols(statement):
    statement=statement or ''
    symbols=[]
    for block in re.findall(r'`([^`]+)`',statement):
        symbols.extend(re.findall(r'[A-Za-z_$][A-Za-z0-9_.$]*(?:\([^)]*\))?',block))
    symbols.extend(re.findall(r'\b(?:[A-Z][A-Za-z0-9_$]*(?:\.[A-Za-z0-9_$]+)+|[A-Z][A-Za-z0-9_$]{3,}|[a-z][A-Za-z0-9_$]{3,}(?=\())',statement))
    stop={'NeoForge','Minecraft','Forge','Java','MockEntity','MODID'}; out=[]
    for symbol in symbols:
        clean=symbol.split('(')[0]
        if clean not in stop and clean not in out: out.append(clean)
    return out[:12]


def _claim_tokens(statement):
    code=_api_symbols(statement)
    if code: return code
    words=[w for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]{3,}',statement or '') if w.lower() not in {'this','that','with','from','into','uses','using','target','source','entity','registration','neoforge','minecraft','forge','updated','system'}]
    return words[:10]


def _semantic_support(statement, evidence_ids, k):
    raw_ids=re.findall(r'[A-Za-z]+-[A-Za-z0-9.-]+|E\d+',evidence_ids) if isinstance(evidence_ids,str) else (evidence_ids or [])
    ids=[i for i in raw_ids if i in k.evidence]
    if not ids: return {'status':'UNSUPPORTED','matched':[],'tokens':_claim_tokens(statement),'api_symbols':_api_symbols(statement),'evidence_ids':[],'reason':'no cited evidence'}
    target_ids=[i for i in ids if str((k.evidence.get(i) or {}).get('version') or '')=='26.2' and (k.evidence.get(i) or {}).get('evidence_kind')=='target_source']
    if not target_ids: return {'status':'UNSUPPORTED','matched':[],'tokens':_claim_tokens(statement),'api_symbols':_api_symbols(statement),'evidence_ids':ids,'reason':'no cited exact 26.2 target_source excerpt'}
    text='\n'.join(k.evidence_text(i,max_chars=MAX_EXCERPT_CHARS) for i in target_ids).lower()
    api_symbols=_api_symbols(statement)
    if not api_symbols:
        return {'status':'UNSUPPORTED','matched':[],'tokens':_claim_tokens(statement),'api_symbols':[],'evidence_ids':target_ids,'reason':'claim has no concrete API symbol'}
    api_matched=[symbol for symbol in api_symbols if any(alias.lower() in text for alias in _symbol_aliases(symbol))]
    low_statement=(statement or '').lower()
    entity_registration_claim=('entity' in low_statement and any(word in low_statement for word in ('register','registry','create')))
    concrete_entity_symbols={'createentities','registerentitytype','entitytypes','register'}
    concrete_matched=[]
    for symbol in api_matched:
        simple=symbol.split('.')[-1].split('(')[0].lower()
        if simple in concrete_entity_symbols: concrete_matched.append(symbol)
    if entity_registration_claim and not concrete_matched:
        return {'status':'UNSUPPORTED','matched':api_matched,'tokens':_claim_tokens(statement),'api_symbols':api_symbols,'matched_api_symbols':api_matched,'evidence_ids':target_ids,'reason':'entity-registration claim lacks a cited concrete registration symbol such as createEntities, registerEntityType, entityTypes, or register'}
    tokens=_claim_tokens(statement); matched=[token for token in tokens if any(alias.lower() in text for alias in _symbol_aliases(token))]
    semantic_ratio=len(matched)/max(1,len(tokens)); symbol_ratio=len(api_matched)/max(1,len(api_symbols))
    status='SUPPORTED' if symbol_ratio==1.0 and semantic_ratio>=0.7 else 'PARTIALLY_SUPPORTED' if symbol_ratio>=0.5 and semantic_ratio>=0.35 else 'UNSUPPORTED'
    return {'status':status,'matched':matched,'tokens':tokens,'api_symbols':api_symbols,'matched_api_symbols':api_matched,'concrete_entity_symbols':concrete_matched,'evidence_ids':target_ids,'match_ratio':round(semantic_ratio,3),'symbol_ratio':round(symbol_ratio,3)}
def score_run(final,trace,coverage,k,probe):
    if not final: return {"quality":0.0,"components":{},"hard_penalties":["no final answer"]}
    action=final.get('action')
    searches=[x for x in trace if x.get('action') in ('controller_resolve_reference','controller_resolve_primer_chain','controller_grep_physical_source','search_knowledge')]
    reads=[x for x in trace if x.get('action') in ('controller_read_reference','controller_read_primer_delta','controller_read_physical_source','read_reference')]
    physical_reads=[x for x in trace if x.get('action')=='controller_read_physical_source']
    maps=[x for x in trace if x.get('action') in ('controller_resolve_mapping','search_mappings','resolve_mapping')]
    read_versions=[str(x.get('result_summary',{}).get('version') or '') for x in reads]
    physical_versions=[str(x.get('result_summary',{}).get('version') or '') for x in physical_reads]
    comp={}
    comp['knowledge_retrieval']=20 if len(searches)>=2 and len(reads)>=2 else 12 if searches and reads else 4 if searches else 0
    exact_target=any(v=='26.2' for v in physical_versions); exact_source=True
    distractor=sum(1 for v in physical_versions if v and v!='26.2')
    comp['version_selection']=15 if exact_target and exact_source else 10 if exact_target else 4
    if distractor: comp['version_selection']=max(0,comp['version_selection']-min(8,distractor*2))
    if probe:
        resolved=[x for x in trace if x.get('action') in ('controller_resolve_mapping','resolve_mapping')]; expected=probe.get('name_to'); got=(final.get('mapping_result') if isinstance(final,dict) else None)
        comp['mapping_usage']=10 if resolved and (got==expected or action=='insufficient_evidence') else 6 if resolved else 2 if maps else 0
    else: comp['mapping_usage']=10

    claims=(final.get('claims') or final.get('supported_claims') or [])
    validations=[]
    for c in claims:
        if not isinstance(c,dict): continue
        validations.append({'statement':c.get('statement',''),**_semantic_support(c.get('statement',''),c.get('evidence_ids'),k)})
    supported=sum(1 for v in validations if v['status']=='SUPPORTED')
    partial=sum(1 for v in validations if v['status']=='PARTIALLY_SUPPORTED')
    unsupported=sum(1 for v in validations if v['status']=='UNSUPPORTED')
    denom=max(1,len(validations)); semantic_ratio=(supported+0.5*partial)/denom if validations else 0
    comp['api_grounding']=round(20*semantic_ratio,2)
    comp['traceability']=round(10*(sum(1 for v in validations if v.get('evidence_ids'))/denom),2) if validations else 0

    target_ok=str(final.get('target_version'))=='26.2'; preserve=('mock_entity' in json.dumps(final) or 'rbmock' in json.dumps(final))
    if action=='insufficient_evidence':
        # Reward justified restraint if exact target retrieval occurred but no target-specific evidence was found.
        target_searches=[x for x in trace if x.get('action')=='controller_grep_physical_source']
        targeted_hits=sum(len((x.get('result_summary') or {}).get('results') or []) for x in target_searches)
        missing=final.get('missing') or []
        justified=target_ok and bool(missing) and targeted_hits==0
        comp['migration_correctness']=15 if justified else 8 if target_ok and bool(missing) else 0
        comp['api_grounding']=20 if justified else comp['api_grounding']
        comp['traceability']=10 if justified else comp['traceability']
    else:
        changes=final.get('changes') or []
        comp['migration_correctness']=15 if target_ok and changes and preserve and unsupported==0 else 10 if target_ok and changes and preserve else 5 if target_ok else 0

    val=(str(final.get('validation') or '')+' '+str(final.get('status') or '')).lower()
    disciplined=('compil' in val and ('unverified' in val or 'until' in val or 'required' in val or 'cannot safely' in val))
    if action=='insufficient_evidence' and ('insufficient' in val or 'blocked' in val or 'cannot safely' in val): disciplined=True
    comp['compile_discipline']=10 if disciplined else 5 if 'compil' in val else 0
    penalties=[]; blob=json.dumps(final).lower()
    if not target_ok: penalties.append('wrong target version')
    if any(x in blob for x in ('compilation succeeded','compiled successfully','build succeeded')): penalties.append('unsupported success claim')
    if action=='final' and unsupported: penalties.append(f'{unsupported} unsupported API claim(s)')
    raw=sum(comp.values()); quality=max(0,raw-20*len(penalties))
    return {"quality":round(quality,2),"components":comp,"hard_penalties":penalties,"read_versions":read_versions,"tool_rounds":len(trace),"claim_validation":validations,"outcome":action}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--models',default='mc-fast,mc-code,mc-research,mc-heavy,mc-reviewer'); ap.add_argument('--label-prefix',default='production'); ap.add_argument('--output',required=True); ap.add_argument('--completion-limit',type=int,default=4000); ap.add_argument('--max-rounds',type=int,default=10); ap.add_argument('--coverage-only',action='store_true')
    a=ap.parse_args(); root=Path(a.root); k=Knowledge(root); coverage=k.coverage()
    models=[x.strip() for x in a.models.split(',') if x.strip()]; report={"schema":"rb-model-benchmark-v3.7","suite":"knowledge-grounded-migration","created":datetime.now().isoformat(),"migration":"Forge/Minecraft 1.20.1+ -> NeoForge 26.2","coverage":coverage,"models":{}}
    if not coverage.get("required_ok"):
        report["status"]="KNOWLEDGE_COVERAGE_INVALID"
        report["message"]=coverage.get("failure_reason")
        Path(a.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(a.output)
        raise SystemExit(2)
    if a.coverage_only:
        report["status"]="KNOWLEDGE_COVERAGE_VALID"
        Path(a.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(a.output)
        return
    report["status"]="RUNNING"
    for alias in models:
        # Reset evidence ids per model so traces are easy to compare, while using same physical DB.
        k.evidence={}; k.next_id=1
        report['models'][alias]=run_agent(alias,f"{a.label_prefix}:{alias}",k,coverage,a.max_rounds,a.completion_limit)
        Path(a.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    report["status"]="COMPLETE"
    Path(a.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(a.output)

if __name__=='__main__': main()
