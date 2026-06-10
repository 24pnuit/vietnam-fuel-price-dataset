import subprocess
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(_HERE)

def run_script(relative_path):
    script_path = os.path.join(SRC_DIR, relative_path)

    subprocess.run(
        [sys.executable, script_path],
        check=True
    )

def main():

    print("[VIETCOMBANK]")

    run_script("vietcombank/crawl_vietcombank.py")
    run_script("vietcombank/clean_vietcombank.py")
    
    print("\n" + "=" * 50)
    print("VIETCOMBANK PIPELINE FINISHED")
    print("=" * 50)

if __name__ == "__main__":
    main()