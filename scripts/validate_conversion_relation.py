#!/usr/bin/env python3
"""Run the narrow conversion-relation classifier over an audited task packet."""
from __future__ import annotations
import argparse, json, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from english_knowledge_tagger.candidate_labeling import LabelingServiceConfig, LabelingServiceError
from english_knowledge_tagger.conversion_relation import ConversionRelationClient, PROMPT_VERSION

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--endpoint',action='append'); parser.add_argument('--model',default='DeepSeek-V4-Flash'); parser.add_argument('--concurrency',type=int,default=10); parser.add_argument('--timeout-seconds',type=float,default=180)
    args=parser.parse_args()
    if args.output.exists() or args.report.exists(): parser.error('refusing to overwrite existing output or report')
    if not 1 <= args.concurrency <= 128: parser.error('--concurrency must be between 1 and 128')
    endpoints=args.endpoint or [os.getenv('ENGLISH_TAGGER_DS_V4_ENDPOINT','http://172.22.0.35:9102/v1/chat/completions')]
    rows=[json.loads(line) for line in args.input.read_text(encoding='utf-8').splitlines() if line.strip()]
    clients=[ConversionRelationClient(LabelingServiceConfig(endpoint=endpoint,model=args.model,timeout_seconds=args.timeout_seconds)) for endpoint in endpoints]
    def one(index_row):
        index,row=index_row; endpoint=endpoints[index%len(endpoints)]
        try:
            result=clients[index%len(clients)].classify(row)
            return {"schema_version":"conversion-relation-evidence-v1","task_id":row.get("task_id"),"question_id":row.get("question_id"),"parent_id":row.get("parent_id"),"endpoint":endpoint,"model":args.model,"prompt_version":PROMPT_VERSION,"relation":result.relation,"confidence":result.confidence,"evidence":result.evidence,"elapsed_ms":result.elapsed_ms,"prompt_chars":result.prompt_chars}
        except (LabelingServiceError,ValueError) as error:
            return {"schema_version":"conversion-relation-evidence-v1","task_id":row.get("task_id"),"question_id":row.get("question_id"),"parent_id":row.get("parent_id"),"endpoint":endpoint,"model":args.model,"prompt_version":PROMPT_VERSION,"status":"error","error":str(error)}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        result=list(pool.map(one,enumerate(rows)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as handle:
        for row in result: handle.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    counts={}
    for row in result: counts[row.get('relation',row.get('status','missing'))]=counts.get(row.get('relation',row.get('status','missing')),0)+1
    report={"schema_version":"conversion-relation-report-v1","input":str(args.input),"output":str(args.output),"endpoints":endpoints,"concurrency":args.concurrency,"processed":len(result),"counts":counts,"prompt_version":PROMPT_VERSION}
    args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,sort_keys=True))
if __name__=='__main__': main()
