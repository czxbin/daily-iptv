"""Reject stale build baselines before replacing generated publication artifacts."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from .publish import FILES

ALLOWED={'live.m3u','STATUS.md','status.json','results.json','published_channels.json',*FILES.values()}

def install_artifacts(expected_sha, actual_sha, artifacts, target):
    if not re.fullmatch('[a-f0-9]{40}',expected_sha) or actual_sha!=expected_sha:
        raise ValueError('main changed after validation; keep current public files and rerun workflow')
    artifacts=Path(artifacts); target=Path(target)
    for path in artifacts.rglob('*'):
        relative=path.relative_to(artifacts).as_posix()
        if path.is_symlink(): raise ValueError('artifact symlinks are not allowed')
        if path.is_dir():
            if relative!='history': raise ValueError('unexpected artifact directory')
        elif relative not in ALLOWED and not re.fullmatch(r'history/\d{8}T\d{6}Z\.json',relative):
            raise ValueError('unexpected artifact filename')
    report=json.loads((artifacts/'status.json').read_text(encoding='utf-8'))
    if report.get('schema_version')!=1: raise ValueError('unsupported report schema')
    count=report.get('playlist_count')
    if type(count) is not int or count<0: raise ValueError('invalid playlist count')
    playlist=artifacts/'live.m3u'
    if count and (not playlist.is_file() or playlist.read_text(encoding='utf-8').count('\n#EXTINF:')!=count):
        raise ValueError('playlist content does not match report')
    if target.exists(): shutil.rmtree(target)
    shutil.copytree(artifacts,target)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--artifacts',required=True)
    args=parser.parse_args()
    actual=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    install_artifacts(args.expected_sha,actual,args.artifacts,'public')

if __name__=='__main__': main()
