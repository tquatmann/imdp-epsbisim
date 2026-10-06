#!/usr/bin/env python3
"""Learn an interval MDP for each MDP listed in benchmarks/umb/index.json using ruffle.

The imdp is stored next to the mdp and added to the index as "imdp", e.g.
    scripts/mdp_to_imdp.py [INSTANCE ...]
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
IMDP_FIELDS = ("imdp", "imdp-maxl1", "imdp-learning-accuracy")


def log(message):
    print(message, flush=True)


def load_index(path):
    with open(path) as f:
        return json.load(f)


def write_index(path, index):
    with open(path, "w") as f:
        json.dump(dict(sorted(index.items())), f, indent="\t", ensure_ascii=False)
        f.write("\n")


def imdp_file(mdp):
    """Returns the imdp file name for the given mdp file name, e.g. model/instance.umb -> model/instance.imdp.umb"""
    mdp = Path(mdp)
    return mdp.with_name(f"{mdp.stem}.imdp{mdp.suffix}")


def learn_imdp(ruffle, mdp, imdp, args):
    """Runs ruffle to learn the imdp from the given mdp. Raises an error if that fails.

    Returns the index fields describing the learned imdp as reported by ruffle.
    """
    command = [str(ruffle), "--input", str(mdp), "--output", str(imdp), "--mode", "learn-interval",
               "--lambda", args.learning_lambda, "--samples", args.samples, "--full-coverage", "--seed", args.seed]
    log(" ".join(command))
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0 or not imdp.exists():
        imdp.unlink(missing_ok=True)
        raise RuntimeError(f"ruffle failed with exit code {result.returncode}:\n{result.stdout.strip()}")
    max_l1 = re.search(r"Maximum feasible L1-diameter over all learned choices: (\S+?)\.?\s", result.stdout)
    accuracy = re.search(r"Learned intervals contain the true distribution for (\d+) of (\d+) states", result.stdout)
    if not max_l1 or not accuracy:
        raise RuntimeError(f"cannot find the L1-diameter and the accuracy in the output of ruffle:\n{result.stdout.strip()}")
    return {"imdp-maxl1": float(max_l1.group(1)),
            "imdp-learning-accuracy": round(int(accuracy.group(1)) / int(accuracy.group(2)), 10)}


def with_imdp(entry, imdp_fields):
    """Returns the index entry with the given imdp fields inserted right after the mdp."""
    result = {}
    for key, value in entry.items():
        if key not in IMDP_FIELDS:
            result[key] = value
        if key == "mdp":
            result.update(imdp_fields)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instances", nargs="*", metavar="INSTANCE",
                        help="names of the instances to process (shell-style wildcards allowed), default: all")
    parser.add_argument("--umb-dir", type=Path, default=REPO_DIR / "benchmarks/umb",
                        help="directory containing the umb files and their index.json (default: %(default)s)")
    parser.add_argument("--ruffle", type=Path, default=REPO_DIR / "bin/ruffle",
                        help="the ruffle binary (default: %(default)s)")
    parser.add_argument("--lambda", dest="learning_lambda", default="0.01",
                        help="local failure probability per successor (default: %(default)s)")
    parser.add_argument("--samples", default="2000",
                        help="number of samples per state-action pair (default: %(default)s)")
    parser.add_argument("--seed", default="0", help="RNG seed (default: %(default)s)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip instances that already have an imdp in the index and whose imdp file exists")
    args = parser.parse_args()

    index_file = args.umb_dir / "index.json"
    index = load_index(index_file)
    names = list(index)
    if args.instances:
        names = [n for n in names if any(fnmatch.fnmatchcase(n, pattern) for pattern in args.instances)]
        unmatched = [p for p in args.instances if not fnmatch.filter(index, p)]
        if unmatched:
            parser.error(f"no instance matches: {', '.join(unmatched)}")

    failed = []
    for i, name in enumerate(names, start=1):
        entry = index[name]
        if args.skip_existing and "imdp" in entry and (args.umb_dir / entry["imdp"]).exists():
            log(f"[{i}/{len(names)}] {name}: skipped")
            continue
        log(f"[{i}/{len(names)}] {name}: learning imdp")
        imdp = imdp_file(entry["mdp"])
        start = time.time()
        try:
            statistics = learn_imdp(args.ruffle, args.umb_dir / entry["mdp"], args.umb_dir / imdp, args)
        except Exception as e:
            log(f"{name}: FAILED: {e}")
            failed.append(name)
            index[name] = with_imdp(entry, {})
        else:
            log(f"{name}: learned after {time.time() - start:.2f}s, {json.dumps(statistics)}")
            index[name] = with_imdp(entry, {"imdp": imdp.as_posix(), **statistics})
        write_index(index_file, index)

    if failed:
        log(f"{len(failed)} of {len(names)} instances failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
