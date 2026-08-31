#!/usr/bin/env python3
"""Build root-tree tasks for label-blind atomic task-shape gate outcomes."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from english_knowledge_tagger.root_tree_tasks import build_root_tree_tasks
def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--packet',type=Path,required=True); parser.add_argument('--evidence',type=Path,required=True); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--report',type=Path,required=True); args=parser.parse_args()
    if args.output == args.report: parser.error('--output and --report must differ')
    if args.report.exists(): parser.error(f'refusing to overwrite report: {args.report}')
    try: report=build_root_tree_tasks(args.packet,args.evidence,output_path=args.output)
    except (FileExistsError,OSError,ValueError,json.JSONDecodeError) as error: parser.error(str(error))
    args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,sort_keys=True))
if __name__=='__main__': main()
