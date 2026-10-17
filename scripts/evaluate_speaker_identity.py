"""Score two local JSON turn files; no models or remote media transfers."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.speaker_evaluation import evaluate
parser=argparse.ArgumentParser();parser.add_argument('prediction');parser.add_argument('reference');parser.add_argument('--output')
args=parser.parse_args()
def turns(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    return data.get('regular_turns',data.get('turns',[])) if isinstance(data,dict) else data
result=evaluate(turns(args.prediction),turns(args.reference));encoded=json.dumps(result,ensure_ascii=False,indent=2)
if args.output:Path(args.output).write_text(encoded,encoding='utf-8')
else:print(encoded)
