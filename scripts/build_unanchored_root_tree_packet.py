#!/usr/bin/env python3
"""Build root-tree tasks from a label-blind sanitized question packet."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from english_knowledge_tagger.unanchored_root_tree_packet import build_unanchored_root_tree_packet
def main() -> None:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--report',type=Path,required=True); a=p.parse_args()
    if a.output==a.report: p.error('--output and --report must differ')
    if a.report.exists(): p.error(f'refusing to overwrite report: {a.report}')
    try: report=build_unanchored_root_tree_packet(a.input,output_path=a.output)
    except (FileExistsError,OSError,ValueError,json.JSONDecodeError) as e: p.error(str(e))
    a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,sort_keys=True))
if __name__=='__main__': main()
