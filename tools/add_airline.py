import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
overrides_file = root / "tools" / "airline_overrides.json"
data_file = root / "api" / "app" / "static" / "globe" / "airlines.json"


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def apply(overrides):
    by_code = {a[0]: a for a in load(data_file, [])}
    for a in overrides:
        by_code[a[0]] = a
    out = sorted(by_code.values(), key=lambda a: a[1].lower())
    data_file.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return len(out)


def main():
    args = sys.argv[1:]
    overrides = load(overrides_file, [])
    if args == ["--apply"]:
        print("airlines now:", apply(overrides), "| saved additions re-applied:", len(overrides))
        return
    if len(args) != 4:
        sys.exit('Usage: python3 tools/add_airline.py CODE "Airline name" IATA "Country"\n'
                 '   (use "" for IATA if unknown; CODE is the 3-letter callsign prefix, e.g. UAE)\n'
                 '   or:  python3 tools/add_airline.py --apply   (re-apply saved additions after regenerating)')
    code, name, iata, country = args
    code, iata, name, country = code.strip().upper(), iata.strip().upper(), name.strip(), country.strip()
    if len(code) != 3 or not code.isalpha():
        sys.exit("CODE must be exactly 3 letters, like UAE or RYR")
    if iata and not (len(iata) == 2 and iata.isalnum()):
        sys.exit("IATA must be 2 letters or digits, or empty")
    if not name:
        sys.exit("Please give the airline name")
    overrides = [o for o in overrides if o[0] != code] + [[code, name, iata, country]]
    overrides_file.write_text(json.dumps(overrides, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {code} = {name} | airlines now: {apply(overrides)}")


main()
