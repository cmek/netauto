from pathlib import Path
from netauto.parsers import OcnosConfigXMLParser


if __name__ == "__main__":
    parser = OcnosConfigXMLParser(Path("./ocnos_config.xml"))

    output = parser.parse_config()

    print(output.lags)
