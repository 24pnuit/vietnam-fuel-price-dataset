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

    print("[FRED]")

    run_script("fred/crawl_brent_crude_price.py")
    run_script("fred/clean_brent_crude_price.py")
    
    print("\n" + "=" * 50)
    print("FRED PIPELINE FINISHED")
    print("=" * 50)

if __name__ == "__main__":
    main()