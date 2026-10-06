#!/usr/bin/env python3
"""Generate the list of tool invocations (configuration x benchmark x repetition).

Reads benchmarks/umb/index.json and scripts/configurations.json and writes a JSON array with
one entry per invocation. An entry contains the command with all %placeholders replaced, the
input files the command needs and where its log and its output files are stored.
"""

import argparse
import json
import random
import sys
from pathlib import Path

from commands import benchmark_values, is_applicable, resolve

# The root of the repository. The binary and the input files of an invocation are relative to it.
ROOT = Path(__file__).resolve().parent.parent
CONFIGS_FILE = ROOT / "scripts" / "configurations.json"
# Directory of the benchmarks relative to the root. The files in index.json are relative to it.
BENCHMARK_DIR = "benchmarks/umb"
INDEX_FILE = ROOT / BENCHMARK_DIR / "index.json"

# Keys of an index.json entry that are not relevant for running it.
BENCHMARK_SKIP_KEYS = {"reference-result"}
# Keys of a configuration that are replaced by the resolved entries of the invocation.
CONFIG_SKIP_KEYS = {"input-files", "output-files"}


def load_dict(path):
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"{path}: expected a JSON object at the top level")
    return data


def select(entries, spec, what):
    """Return the (id, entry) pairs selected by a comma separated list of ids."""
    if spec is None:
        return list(entries.items())
    ids = [i.strip() for i in spec.split(",") if i.strip()]
    unknown = [i for i in ids if i not in entries]
    if unknown:
        sys.exit(f"unknown {what}: {', '.join(unknown)}")
    seen, result = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            result.append((i, entries[i]))
    return result


def with_id(id, entry, skip=()):
    """The entry as a dict with its id as the first key, without the skipped keys."""
    item = {"id": id}
    item.update({k: v for k, v in entry.items() if k != "id" and k not in skip})
    return item


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--invfile", required=True, help="file that the invocations are written to")
    parser.add_argument("--configs", help="comma separated list of configurations (default: all)")
    parser.add_argument("--benchmarks", help="comma separated list of benchmarks (default: all)")
    parser.add_argument("--timelimit", type=int, default=1800, help="time limit in seconds (default: 1800)")
    parser.add_argument("--logdir", default="logs", help="directory for the logs, relative paths are relative to the "
                             "directory that run.py is called from (default: logs)")
    parser.add_argument("--outdir", default="output",
                        help="directory for the files produced by the tools, relative paths are relative "
                             "to the directory that run.py is called from (default: output)")
    parser.add_argument("--repetitions", type=int, default=1,
                        help="how often each invocation is repeated (default: 1)")
    parser.add_argument("--noshuffle", action="store_true",
                        help="keep lexicographic order instead of shuffling the output")
    args = parser.parse_args()

    if args.timelimit <= 0:
        sys.exit("--timelimit must be positive")
    if args.repetitions < 1:
        sys.exit("--repetitions must be at least 1")

    if not CONFIGS_FILE.is_file():
        sys.exit(f"{CONFIGS_FILE} not found")
    all_configs = load_dict(CONFIGS_FILE)
    invalid = [i for i in all_configs if "_" in i]
    if invalid:
        sys.exit(f"{CONFIGS_FILE}: configuration identifiers must not contain '_': "
                 f"{', '.join(invalid)}")

    configs = select(all_configs, args.configs, "configuration")
    benchmarks = select(load_dict(INDEX_FILE), args.benchmarks, "benchmark")
    logdir = args.logdir.rstrip("/")
    outdir = args.outdir.rstrip("/")

    invocations = []
    skipped = 0
    for config_id, config in configs:
        for benchmark_id, benchmark in benchmarks:
            # Skip combinations the configuration cannot be run on, e.g. a configuration
            # for imdps on a benchmark for which no imdp was learned.
            values = benchmark_values(benchmark_id, benchmark)
            if not is_applicable(config, values):
                skipped += 1
                continue
            cmd_args, input_files, output_files = resolve(config, values)
            for repetition in range(1, args.repetitions + 1):
                name = f"{config_id}_{benchmark_id}"
                if args.repetitions > 1:
                    name += f"_rep{repetition}"
                # With several repetitions, each one gets its own output directory.
                rep_outdir = f"{outdir}/rep{repetition}" if args.repetitions > 1 else outdir
                invocation = {
                    "config": with_id(config_id, config, CONFIG_SKIP_KEYS),
                    "benchmark": with_id(benchmark_id, benchmark, BENCHMARK_SKIP_KEYS),
                    "command": [config["bin"], *cmd_args],
                    "timelimit": args.timelimit,
                }
                if args.repetitions > 1:
                    invocation["repetition"] = repetition
                invocation["input-files"] = [f"{BENCHMARK_DIR}/{f}" for f in input_files]
                invocation["output-files"] = [f"{rep_outdir}/{f}" for f in output_files]
                invocation["log"] = f"{logdir}/{name}.log"
                invocations.append(invocation)

    if args.noshuffle:
        invocations.sort(key=lambda i: (i["config"]["id"], i["benchmark"]["id"], i.get("repetition", 1)))
    else:
        random.shuffle(invocations)

    with open(args.invfile, "w") as f:
        json.dump(invocations, f, indent=2)
        f.write("\n")

    print(f"wrote {len(invocations)} invocations "
          f"({len(configs)} configurations x {len(benchmarks)} benchmarks "
          f"x {args.repetitions} repetition(s)) to {args.invfile}")
    if skipped:
        print(f"  skipped:     {skipped} configuration/benchmark pairs "
              f"the configuration is not applicable to")
    print(f"  time limit:  {args.timelimit}s")
    print(f"  log dir:     {logdir}")
    print(f"  output dir:  {outdir}")
    print(f"  repetitions: {args.repetitions}")


if __name__ == "__main__":
    main()
