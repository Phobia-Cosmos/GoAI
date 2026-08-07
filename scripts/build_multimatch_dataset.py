from pathlib import Path

from goai_data.multimatch_pipeline import MultiMatchDatasetBuilder


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path("/home/undefined/Disk/datasets/goai/processed/v2")


if __name__ == "__main__":
    catalog = MultiMatchDatasetBuilder(PROJECT_ROOT, OUTPUT_ROOT).build()
    print(f"built {catalog['match_count']} matches at {OUTPUT_ROOT}")
