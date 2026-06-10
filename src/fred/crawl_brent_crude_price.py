import requests
import os
import pandas as pd 
from io import StringIO

# CONFIG PATHS
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
RAW_DIR = os.path.join(_ROOT, "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

OUTPUT_FILE = os.path.join(RAW_DIR, "brent_crude_price.csv")
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
UNIT = "Dollars per Barrel"

def main():
    # DOWNLOAD DATA
    response = requests.get(CSV_URL, headers={"User-Agent": "Mozilla/5.0"}, mtimeout=30)
    
    df = pd.read_csv(StringIO(response.text))
    df["unit"] = UNIT

    # SAVE TO RAW
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    
    print(f"Đã lưu: {OUTPUT_FILE}")
    
if __name__ == "__main__":
    main()