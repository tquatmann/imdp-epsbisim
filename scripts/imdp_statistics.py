#!/usr/bin/env python3
"""Print statistics about the benchmark set listed in benchmarks/umb/index.json."""

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def property_type(benchmark):
    """The type of the property of a benchmark: Pmin, Pmax, Rmin or Rmax. Expected time counts as reward."""
    match = re.match(r"\s*([PRT])(?:\{[^}]*\})?(min|max)", benchmark.get("property", ""))
    return ("R" if match.group(1) == "T" else match.group(1)) + match.group(2) if match else "unknown"


def format_number(value):
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:.4g}"


def print_counts(title, counter):
    print(f"{title}:")
    width = max(len(str(key)) for key in counter)
    for key, count in sorted(counter.items()):
        print(f"  {str(key):<{width}}  {count:>4}")
    print()


def print_distributions(title, rows):
    """Prints min, median and max of several quantities.

    A row consists of the name of the quantity and a list of (value, benchmark) pairs.
    """
    rows = [(name, sorted(values)) for name, values in rows if values]
    if not rows:
        return
    print(f"{title}:")
    name_width = max(len(name) for name, _ in rows)
    header = f"  {'':<{name_width}}  {'n':>4}  {'min':>13}  {'median':>13}  {'max':>13}   attained by (min / max)"
    print(header)
    for name, values in rows:
        numbers = [value for value, _ in values]
        median = statistics.median(numbers)
        if all(isinstance(number, int) for number in numbers):
            median = round(median)
        print(f"  {name:<{name_width}}  {len(numbers):>4}  {format_number(numbers[0]):>13}  {format_number(median):>13}  "
              f"{format_number(numbers[-1]):>13}   {values[0][1]} / {values[-1][1]}")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=REPO_DIR / "benchmarks/umb/index.json",
                        help="the index.json to read (default: %(default)s)")
    args = parser.parse_args()

    with open(args.index) as f:
        index = json.load(f)

    families = Counter(name.split(".")[0] for name in index)
    print(f"{len(index)} benchmarks from {len(families)} model families")
    print(f"  with a learned IMDP:               {sum('imdp' in b for b in index.values()):>4}")
    print(f"  with a finite horizon property:    {sum('property-finite-horizon' in b for b in index.values()):>4}")
    print(f"  with a reference result:           {sum('reference-result' in b for b in index.values()):>4}")
    print()

    print_counts("Benchmarks per type", Counter(b.get("type", "unknown") for b in index.values()))
    print_counts("Benchmarks per property type (expected time counts as reward)",
                 Counter(property_type(b) for b in index.values()))
    print_counts("Benchmarks per model family", families)

    def values(get):
        """The (value, benchmark) pairs for the benchmarks that have the value."""
        result = []
        for name, benchmark in index.items():
            try:
                result.append((get(benchmark), name))
            except (KeyError, ZeroDivisionError):
                pass
        return result

    print_distributions("Size of the input MDPs", [
        ("states", values(lambda b: b["input-model"]["states"])),
        ("choices", values(lambda b: b["input-model"]["choices"])),
        ("transitions", values(lambda b: b["input-model"]["transitions"])),
        ("choices per state", values(lambda b: b["input-model"]["choices"] / b["input-model"]["states"])),
        ("transitions per choice", values(lambda b: b["input-model"]["transitions"] / b["input-model"]["choices"])),
        ("fraction of dirac states", values(lambda b: b["input-model"]["dirac-states"] / b["input-model"]["states"])),
    ])

    print_distributions("Learned IMDPs", [
        ("imdp-maxl1", values(lambda b: b["imdp-maxl1"])),
        ("imdp-learning-accuracy", values(lambda b: b["imdp-learning-accuracy"])),
    ])

    accuracies = [b["imdp-learning-accuracy"] for b in index.values() if "imdp-learning-accuracy" in b]
    if accuracies:
        print("Learning accuracy (fraction of states whose learned intervals contain the true distribution):")
        for bound in (1.0, 0.999, 0.99, 0.95, 0.9):
            comparison = "= 1" if bound == 1.0 else f">= {bound}"
            print(f"  {comparison:<9}  {sum(a >= bound for a in accuracies):>4} of {len(accuracies)} benchmarks")


if __name__ == "__main__":
    main()
