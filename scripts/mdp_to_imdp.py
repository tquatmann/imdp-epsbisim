#!/usr/bin/env python3
"""Learn an interval MDP for each MDP listed in benchmarks/umb/index.json using ruffle.

The imdp is stored next to the mdp and added to the index as "imdp", e.g.
    scripts/mdp_to_imdp.py [INSTANCE ...]

Several imdps can be learned for an mdp, e.g. with different numbers of samples, by giving each of them
an identifier: with --identifier a, the imdp is stored as <instance>.imdpa.umb and added to the index as
"imdpa" (together with "imdpa-maxl1" and "imdpa-learning-accuracy").
"""
import argparse
import fcntl
import fnmatch
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def imdp_key(identifier):
    """The index key of the imdp with the given identifier, which is also the prefix of its other keys."""
    return f"imdp{identifier}"


def log(message):
    print(message, flush=True)


def load_index(path):
    with open(path) as f:
        return json.load(f)


def write_index(path, index):
    with open(path, "w") as f:
        json.dump(dict(sorted(index.items())), f, indent="\t", ensure_ascii=False)
        f.write("\n")


def update_index(path, name, key, imdp_fields):
    """Replaces the fields of the imdp with the given key in the entry of the given instance in the index file.

    The index is read again while holding a lock on it, so that several processes (e.g. one per instance,
    see --index) can update it without overwriting the changes of each other.
    """
    with open(path.with_name(path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = load_index(path)
        index[name] = with_imdp(index[name], key, imdp_fields)
        write_index(path, index)


def imdp_file(mdp, key):
    """Returns the imdp file name for the given mdp file name, e.g. model/instance.umb -> model/instance.imdp.umb"""
    mdp = Path(mdp)
    return mdp.with_name(f"{mdp.stem}.{key}{mdp.suffix}")


def learn_imdp(ruffle, mdp, imdp, key, args):
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
    return {f"{key}-maxl1": float(max_l1.group(1)),
            f"{key}-learning-accuracy": round(int(accuracy.group(1)) / int(accuracy.group(2)), 10)}


def with_imdp(entry, key, imdp_fields):
    """Returns the index entry with the fields of the imdp with the given key replaced by the given ones.

    The fields of a new imdp are inserted after the mdp and the imdps that are already there.
    """
    own_fields = (key, f"{key}-maxl1", f"{key}-learning-accuracy")
    keys = list(entry)
    if key in entry:
        # Keep the position of an imdp that is learned again.
        position = keys.index(key)
    else:
        position = max((i for i, k in enumerate(keys, start=1) if k == "mdp" or k.startswith("imdp")), default=0)
    before = {k: entry[k] for k in keys[:position] if k not in own_fields}
    after = {k: entry[k] for k in keys[position:] if k not in own_fields}
    return {**before, **imdp_fields, **after}


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
    parser.add_argument("--identifier", default="",
                        help="identifier of the learned imdps (letters and digits), which is appended to \"imdp\" "
                             "in the file names and in the keys of the index (default: none)")
    parser.add_argument("--index", type=int, metavar="I",
                        help="only process the I-th of the instances (1-based, as numbered in the output), "
                             "e.g. to process each instance in a job of its own")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip instances that already have an imdp in the index and whose imdp file exists")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]*", args.identifier):
        parser.error("--identifier must consist of letters and digits only")
    key = imdp_key(args.identifier)

    index_file = args.umb_dir / "index.json"
    index = load_index(index_file)
    names = list(index)
    if args.instances:
        names = [n for n in names if any(fnmatch.fnmatchcase(n, pattern) for pattern in args.instances)]
        unmatched = [p for p in args.instances if not fnmatch.filter(index, p)]
        if unmatched:
            parser.error(f"no instance matches: {', '.join(unmatched)}")

    selected = list(enumerate(names, start=1))
    if args.index is not None:
        if not 1 <= args.index <= len(names):
            parser.error(f"--index must be between 1 and {len(names)}, got {args.index}")
        selected = [selected[args.index - 1]]

    failed = []
    for i, name in selected:
        entry = index[name]
        if args.skip_existing and key in entry and (args.umb_dir / entry[key]).exists():
            log(f"[{i}/{len(names)}] {name}: skipped")
            continue
        log(f"[{i}/{len(names)}] {name}: learning {key}")
        imdp = imdp_file(entry["mdp"], key)
        start = time.time()
        try:
            statistics = learn_imdp(args.ruffle, args.umb_dir / entry["mdp"], args.umb_dir / imdp, key, args)
        except Exception as e:
            log(f"{name}: FAILED: {e}")
            failed.append(name)
            update_index(index_file, name, key, {})
        else:
            log(f"{name}: learned after {time.time() - start:.2f}s, {json.dumps(statistics)}")
            update_index(index_file, name, key, {key: imdp.as_posix(), **statistics})

    if failed:
        log(f"{len(failed)} of {len(selected)} instances failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
