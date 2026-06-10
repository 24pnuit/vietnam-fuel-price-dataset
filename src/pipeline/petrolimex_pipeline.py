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

    print("[PETROLIMEX]")

    run_script("petrolimex/crawl_bog_petrolimex.py")
    run_script("petrolimex/parse_bog_petrolimex.py")
    run_script("petrolimex/clean_bog_petrolimex.py")

    print("\n" + "=" * 50)
    print("PETROLIMEX PIPELINE FINISHED")
    print("=" * 50)

if __name__ == "__main__":
    main()