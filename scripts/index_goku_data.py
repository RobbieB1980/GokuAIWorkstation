#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, sys, time
from pathlib import Path

TEXT_EXTS={'.md','.mdx','.txt','.csv','.tsv','.json','.json5','.java','.gradle','.kts','.properties','.toml','.yml','.yaml','.xml','.html','.htm','.cfg','.conf','.accesswidener','.srg','.tsrg','.tiny','.mapping','.map','.diff','.patch','.mcmeta'}
SKIP_EXTS={'.jar','.zip','.png','.jpg','.jpeg','.gif','.webp','.ogg','.wav','.mp3','.class','.dll','.exe','.so','.bin','.db','.sqlite','.pyc'}
SKIP_PARTS={'.git','.gradle','build','out','node_modules','assets/objects','logs','cache','caches'}
VERSION_RE=re.compile(r'(?<!\d)(?:1\.\d{1,2}(?:\.\d{1,2})?|2[4-9]\.\d{1,2})(?!\d)')

def norm_rel(p:Path,root:Path)->str:return p.relative_to(root).as_posix()
def allowed(p:Path,root:Path,max_bytes:int)->bool:
    rel=norm_rel(p,root).lower(); parts=set(rel.split('/'))
    if any(x in rel for x in ('/assets/objects/','/logs/','/.git/','/.gradle/','/build/')): return False
    if parts & SKIP_PARTS or p.suffix.lower() in SKIP_EXTS: return False
    if p.stat().st_size==0 or p.stat().st_size>max_bytes:return False
    if p.suffix.lower() in TEXT_EXTS:return True
    # Extensionless mapping tables are useful only in mapping/primer trees.
    return not p.suffix and any(x in rel for x in ('mapping','primer','mcp','srg','neoforge','geckolib','gradle'))
def read_text(p:Path)->str|None:
    raw=p.read_bytes()
    if b'\0' in raw[:8192]:return None
    for enc in ('utf-8-sig','utf-8','cp1252'):
        try:return raw.decode(enc)
        except UnicodeDecodeError:pass
    return None
def chunks(text:str,size:int,overlap:int):
    text=text.replace('\r\n','\n').replace('\r','\n'); start=0;n=len(text)
    while start<n:
        end=min(n,start+size)
        if end<n:
            cut=max(text.rfind('\n',start+size//2,end),text.rfind(' ',start+size//2,end))
            if cut>start:end=cut
        piece=text[start:end].strip()
        if piece:yield start,end,piece
        if end>=n:break
        start=max(start+1,end-overlap)
def family(rel:str)->str:
    x=rel.lower()
    for needle,name in [('neoforge migration primer changes','neoforge_changes'),('neoforge-migration-primers','neoforge_primers'),('geckolib','geckolib'),('mcreator','mcreator'),('gradle','gradle'),('mcp_mapping','mappings'),('minecraft_mcp','mappings'),('mapping','mappings'),('solved','solved_problems'),('generator','generator_template')]:
        if needle in x:return name
    return 'other'
def schema(c):
    c.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY,sha256 TEXT UNIQUE,bytes INTEGER,mtime_ns INTEGER,family TEXT,versions TEXT,canonical_path TEXT);
    CREATE TABLE IF NOT EXISTS sources(document_id INTEGER,path TEXT UNIQUE,FOREIGN KEY(document_id) REFERENCES documents(id));
    CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,document_id INTEGER,ordinal INTEGER,start_char INTEGER,end_char INTEGER,sha256 TEXT UNIQUE,text TEXT,FOREIGN KEY(document_id) REFERENCES documents(id));
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, path UNINDEXED, family UNINDEXED, versions UNINDEXED, chunk_id UNINDEXED, tokenize='unicode61');
    CREATE INDEX IF NOT EXISTS idx_sources_doc ON sources(document_id); CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);''')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default=r'C:\gokuai\Data');ap.add_argument('--out',default=r'C:\gokuai\DataIndex\goku-data.db');ap.add_argument('--chunk-size',type=int,default=1800);ap.add_argument('--overlap',type=int,default=240);ap.add_argument('--max-file-mib',type=int,default=32);ap.add_argument('--rebuild',action='store_true');a=ap.parse_args()
    root=Path(a.root).resolve();out=Path(a.out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if a.rebuild and out.exists():out.unlink()
    con=sqlite3.connect(out);schema(con); stats={'seen':0,'indexed':0,'duplicate_sources':0,'skipped':0,'binary':0,'chunks':0,'errors':0}; begun=time.time()
    con.execute('DELETE FROM chunks_fts');con.execute('DELETE FROM chunks');con.execute('DELETE FROM sources');con.execute('DELETE FROM documents')
    for p in root.rglob('*'):
        if not p.is_file():continue
        stats['seen']+=1
        try:
            if not allowed(p,root,a.max_file_mib*1024*1024):stats['skipped']+=1;continue
            text=read_text(p)
            if text is None:stats['binary']+=1;continue
            rawhash=hashlib.sha256(text.encode('utf-8')).hexdigest();rel=norm_rel(p,root);fam=family(rel);versions=','.join(sorted(set(VERSION_RE.findall(rel+' '+text[:4000]))))
            row=con.execute('SELECT id FROM documents WHERE sha256=?',(rawhash,)).fetchone()
            if row:doc=row[0];con.execute('INSERT OR IGNORE INTO sources(document_id,path) VALUES(?,?)',(doc,rel));stats['duplicate_sources']+=1;continue
            cur=con.execute('INSERT INTO documents(sha256,bytes,mtime_ns,family,versions,canonical_path) VALUES(?,?,?,?,?,?)',(rawhash,p.stat().st_size,p.stat().st_mtime_ns,fam,versions,rel));doc=cur.lastrowid;con.execute('INSERT INTO sources(document_id,path) VALUES(?,?)',(doc,rel));stats['indexed']+=1
            for i,(s,e,txt) in enumerate(chunks(text,a.chunk_size,a.overlap)):
                ch=hashlib.sha256((rawhash+':'+str(i)+':'+txt).encode()).hexdigest();cur=con.execute('INSERT INTO chunks(document_id,ordinal,start_char,end_char,sha256,text) VALUES(?,?,?,?,?,?)',(doc,i,s,e,ch,txt));con.execute('INSERT INTO chunks_fts(text,path,family,versions,chunk_id) VALUES(?,?,?,?,?)',(txt,rel,fam,versions,cur.lastrowid));stats['chunks']+=1
            if stats['indexed']%100==0:con.commit();print(f"indexed={stats['indexed']} chunks={stats['chunks']} seen={stats['seen']}",flush=True)
        except Exception as e:stats['errors']+=1;print(f"WARN {p}: {e}",file=sys.stderr,flush=True)
    stats['seconds']=round(time.time()-begun,2);stats['database']=str(out);stats['root']=str(root)
    for k,v in {'schema':'goku-data-index-v1','root':str(root),'created':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'stats':json.dumps(stats)}.items():con.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)',(k,v))
    con.commit();con.execute('PRAGMA optimize');con.close();Path(str(out)+'.manifest.json').write_text(json.dumps(stats,indent=2),encoding='utf-8');print(json.dumps(stats,indent=2))
if __name__=='__main__':main()
