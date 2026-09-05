#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True)
    ap.add_argument('--path', required=True)
    ns = ap.parse_args()
    project = Path(ns.project).resolve()
    target = Path(ns.path).resolve()
    ctx = project / '.rb-migration' / 'knowledge-context.json'
    if not ctx.exists():
        raise SystemExit('knowledge-context.json missing; refresh project knowledge wiring first')
    data = json.loads(ctx.read_text(encoding='utf-8-sig'))
    db = Path(data['knowledge_db'])
    roots = [project, db.parent.parent]
    roots += [Path(s['source_root']).resolve() for s in data.get('sources', []) if s.get('source_root')]
    matched = None
    for root in roots:
        try:
            target.relative_to(root)
            matched = str(root)
            break
        except ValueError:
            pass
    print(json.dumps({'allowed': matched is not None, 'path': str(target), 'matched_root': matched}, indent=2))
    raise SystemExit(0 if matched else 2)

if __name__ == '__main__':
    main()
