# main.py
# runs all the scripts in the correct order
import os

if __name__ == "__main__":
    # run the scripts in the correct order
    os.system("python 01_parse_statements.py")
    os.system("python 02_categorise.py")
    os.system("python 03_analyse.py")
        