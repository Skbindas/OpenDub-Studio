"""Install optional CLI/vault/download tools without changing media environments."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]


def main():
    if sys.version_info<(3,11):raise SystemExit('Kaggle SDK needs Python 3.11+. Existing environments were retained.')
    target=ROOT/'runtime/kaggle-env'
    if not target.exists():venv.EnvBuilder(with_pip=True).create(target)
    python=target/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements-kaggle.txt')],check=True)
    print('Isolated Kaggle SDK installed. Main/clone/separation runtimes were not changed.')


if __name__=='__main__':main()
