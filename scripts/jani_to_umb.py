#!/usr/bin/env python3
"""Build the benchmark instances from benchmarks/index.json with stormpy and export them in the umb format.

Run with the python interpreter of the virtual environment that provides stormpy, e.g.
    benchmarks/venv/bin/python tools/export_umb.py [INSTANCE ...]
"""
import argparse
import fnmatch
import json
import re
import sys
import time
from pathlib import Path

import stormpy

REPO_DIR = Path(__file__).resolve().parent.parent
FINITE_HORIZON = 500


def log(message):
    print(message, flush=True)


def load_index(path):
    with open(path) as f:
        return json.load(f)


def write_index(path, index):
    with open(path, "w") as f:
        json.dump(dict(sorted(index.items())), f, indent="\t", ensure_ascii=False)
        f.write("\n")


def build_instance(jani_file, property_name, constants):
    """Builds the sparse model for the given property. Returns the (discrete-time) model and the property."""
    jani_model, properties = stormpy.parse_jani_model(str(jani_file))
    properties = [p for p in properties if p.name == property_name]
    if len(properties) != 1:
        raise RuntimeError(f"expected exactly one property named '{property_name}', found {len(properties)}")
    description, properties = stormpy.preprocess_symbolic_input(jani_model, properties, constants)
    model = stormpy.build_sparse_model(description.as_jani_model(), properties)
    formula = properties[0].raw_formula
    if model.model_type == stormpy.ModelType.MA:
        model, formulae = stormpy.transform_to_discrete_time_model(model, [formula])
        formula = formulae[0]
    return relabel(model, formula)


def relabel(model, formula):
    """Replaces the expressions occurring in the formula by labels.

    The builder labels the states satisfying such an expression with the expression itself. These state labels are
    renamed to "target", "target_2", ... so that the property refers to explicitly chosen label names.
    Returns the model with the renamed labels and the property (as string) over these labels.
    """
    prop = str(formula)
    old_labels = model.labeling.get_labels()
    # Labels that the formula does not refer to by name but that occur as an expression
    expressions = [l for l in old_labels if f'"{l}"' not in prop and l in prop]
    # Number in order of occurrence, replace long expressions first as they may contain shorter ones
    expressions.sort(key=prop.index)
    names = {}
    for expression in expressions:
        name = "target" if not names else f"target_{len(names) + 1}"
        while name in old_labels:
            name += "_"
        names[expression] = name
    for expression in sorted(expressions, key=len, reverse=True):
        prop = prop.replace(expression, f'"{names[expression]}"')

    # The property shall now be well-defined without the symbolic model, i.e., only refer to labels of the model
    try:
        stormpy.parse_properties_without_context(prop)
    except Exception as e:
        raise RuntimeError(f"cannot express '{formula}' over state labels, got '{prop}': {e}")
    labeling = stormpy.storage.StateLabeling(model.nr_states)
    for label in old_labels:
        labeling.add_label(names.get(label, label))
        labeling.set_states(names.get(label, label), model.labeling.get_states(label))
    missing = [l for l in re.findall(r'"([^"]*)"', re.sub(r'\{"[^"]*"\}', "", prop)) if not labeling.contains_label(l)]
    if missing:
        raise RuntimeError(f"property '{prop}' refers to unknown labels: {', '.join(missing)}")
    if not expressions:
        return model, prop

    components = stormpy.SparseModelComponents(transition_matrix=model.transition_matrix, state_labeling=labeling,
                                               reward_models=model.reward_models)
    if model.has_choice_labeling():
        components.choice_labeling = model.choice_labeling
    if model.model_type == stormpy.ModelType.MDP:
        return stormpy.storage.SparseMdp(components), prop
    if model.model_type == stormpy.ModelType.DTMC:
        return stormpy.storage.SparseDtmc(components), prop
    raise RuntimeError(f"unsupported model type {model.model_type.name}")


def model_statistics(model):
    """Returns the size of the model. A state is dirac if all its outgoing transitions have probability 1."""
    matrix = model.transition_matrix

    def is_dirac(row):
        # The entries of a row sum up to one
        entries = matrix.get_row(row)
        return len(entries) == 1 or sum(1 for entry in entries if entry.value() != 0) == 1

    dirac_states = 0
    for state in range(model.nr_states):
        if all(is_dirac(row) for row in range(matrix.get_row_group_start(state), matrix.get_row_group_end(state))):
            dirac_states += 1
    return {"states": model.nr_states, "choices": model.nr_choices, "transitions": model.nr_transitions,
            "dirac-states": dirac_states}


def finite_horizon_property(prop, bound=FINITE_HORIZON):
    """Returns the step-bounded variant of the given property or None if there is none."""
    if re.fullmatch(r'P(min|max)=\? \[F .*\]', prop):
        result = prop.replace("[F ", f"[F<={bound} ", 1)
    elif re.fullmatch(r'P(min|max)=\? \[.* U .*\]', prop) and prop.count(" U ") == 1:
        result = prop.replace(" U ", f" U<={bound} ")
    elif match := re.fullmatch(r'(R\{"[^"]*"\}(min|max)=\?) \[F .*\]', prop):
        result = f"{match.group(1)} [C<={bound}]"
    else:
        return None
    stormpy.parse_properties_without_context(result)
    return result


def export_instance(name, entry, input_dir, output_dir):
    """Exports the given instance and returns its entry for the umb index."""
    jani = Path(entry["jani"])
    umb = jani.parent / f"{name}.umb"
    model, prop = build_instance(input_dir / jani, entry["property"], entry.get("constants", ""))
    (output_dir / umb).parent.mkdir(parents=True, exist_ok=True)
    stormpy.export_to_umb(model, str(output_dir / umb))
    result = {"type": entry["type"], "mdp": umb.as_posix(), "property": prop}
    finite_horizon = finite_horizon_property(prop)
    if finite_horizon is None:
        log(f"{name}: no finite horizon variant for property '{prop}'")
    else:
        result["property-finite-horizon"] = finite_horizon
    result["input-model"] = model_statistics(model)
    if "reference-result" in entry:
        result["reference-result"] = entry["reference-result"]
    log(f"{name}: {model.model_type.name} with {json.dumps(result['input-model'])}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("instances", nargs="*", metavar="INSTANCE",
                        help="names of the instances to export (shell-style wildcards allowed), default: all")
    parser.add_argument("--input-dir", type=Path, default=REPO_DIR / "benchmarks/jani",
                        help="directory containing the input index.json (default: %(default)s)")
    parser.add_argument("--output-dir", type=Path, default=REPO_DIR / "benchmarks/umb",
                        help="directory for the umb files and their index.json (default: %(default)s)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip instances that are already listed in the output index and whose umb file exists")
    args = parser.parse_args()

    index = load_index(args.input_dir / "index.json")
    names = list(index)
    if args.instances:
        names = [n for n in names if any(fnmatch.fnmatchcase(n, pattern) for pattern in args.instances)]
        unmatched = [p for p in args.instances if not fnmatch.filter(index, p)]
        if unmatched:
            parser.error(f"no instance matches: {', '.join(unmatched)}")

    # Keep the entries of previous runs so that the instances can be exported in several runs
    umb_index_file = args.output_dir / "index.json"
    umb_index = load_index(umb_index_file) if umb_index_file.exists() else {}

    failed = []
    for i, name in enumerate(names, start=1):
        if args.skip_existing and name in umb_index and (args.output_dir / umb_index[name]["mdp"]).exists():
            log(f"[{i}/{len(names)}] {name}: skipped")
            continue
        log(f"[{i}/{len(names)}] {name}: building")
        start = time.time()
        try:
            umb_index[name] = export_instance(name, index[name], args.input_dir, args.output_dir)
        except Exception as e:
            log(f"{name}: FAILED: {e}")
            failed.append(name)
            umb_index.pop(name, None)
        else:
            log(f"{name}: exported after {time.time() - start:.2f}s")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_index(umb_index_file, umb_index)

    if failed:
        log(f"{len(failed)} of {len(names)} instances failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
