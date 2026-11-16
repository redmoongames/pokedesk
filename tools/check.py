"""Run the portable regression gate with the bundled Python."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from regression.runner import main

if __name__=='__main__':main()
