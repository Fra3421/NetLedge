import subprocess
import sys

packages = ['kuzu', 'streamlit', 'pandas', 'pywebview']

for package in packages:
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])