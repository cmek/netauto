from argparse import Namespace
import argparse
import json
from pathlib import Path
from netauto.parsers import AristaConfigParser

def main() -> int:
    parser = argparse.ArgumentParser(description="parser for Arista JSON-wrapped config files")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("./configs/arista/"),
        help="Path to a config file or directory of *.config.txt files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/arista/"),
        help="Optional path to write JSON output",
    )
    args: Namespace = parser.parse_args()

    input_path: Path = args.input
    output_path: Path = args.output
    files = input_path.glob("*.config.txt")
    if not files:
        raise SystemExit(f"No config files found at: {args.input}")

    for config_file in files:
        print(f"Results for: {config_file.name}")
        parser = AristaConfigParser(config_file)
        config_data = parser.parse_arista_config()
        print(f"  parsed interfaces: {len(config_data['interfaces'])}")
        print(f"  parsed lags: {len(config_data['lags'])}")
        print(f"  parsed vlans: {len(config_data['vlans'])}")
        print(f"  parsed network_instances: {len(config_data['network_instances'])}")
        print(f"  parsed evpns: {len(config_data['evpns'])}")

        folder_name = config_file.name.removesuffix(".config.txt")
        output_dir = output_path / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        for key, values in config_data.items():
            output_file = output_dir / f"{key}.json"
            with output_file.open("w", encoding="utf-8") as handle:
                data = [entry.model_dump() for entry in values]
                json.dump(data, handle, indent=4)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
