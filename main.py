# main.py
# runs all the scripts in the correct order
import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "01_parse_statements.py"], check=True)
    subprocess.run([sys.executable, "02_categorise.py"], check=True)
    subprocess.run([sys.executable, "03_analyse.py"], check=True)
