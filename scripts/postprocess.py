#!/usr/bin/env python3
"""Evaluate the logs and output files produced by run.py.

First, evalquo determines for each iMDP quotient whether it is equal to, finer than, coarser
than or incomparable with the MDP quotient of the same benchmark. The result is appended to the log file of the run that produced the iMDP quotient
(unless it is already there). Then, a table with one row per benchmark is written as csv
and as html, together with one html page per log file that the cells of the table link to.
The file plotdata.csv contains the same table in a form that pgfplots can read and
quantile-absdiff.csv contains the data for a quantile plot of the absolute differences (see latex/).

Only runs with a single repetition are supported.
"""

import argparse
import csv
import html
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from commands import benchmark_values, is_applicable, kept_parts, placeholders, resolve

# The root of the repository.
ROOT = Path(__file__).resolve().parent.parent
CONFIGS_FILE = ROOT / "scripts" / "configurations.json"
INDEX_FILE = ROOT / "benchmarks" / "umb" / "index.json"
EVALQUO = ROOT / "tools" / "evalquo" / "build" / "bin" / "evalquo"

# Marks the result of evalquo in a log file.
EVALQUO_MARKER = "Evalquo command:\t"
ERROR_LINE = re.compile(r"^ERROR\b.*$", re.MULTILINE)
UNSUPPORTED = re.compile(r"unsupported|not implemented|do not support", re.IGNORECASE)

# The result of evalquo, where quotient 1 is the MDP quotient and quotient 2 is the iMDP quotient.
EVALQUO_RELATION = re.compile(r"^Quotient 2 is (equal to|finer than|coarser than|incomparable with) quotient 1\.$", re.MULTILINE)
# The css classes for the relation of the iMDP quotient to the MDP quotient.
RELATION_CSS = {"equal": "agrees", "finer": "refines", "coarser": "coarser", "incomparable": "differs"}


# Smallest value in the data for the quantile plots; this must match \plotminvalue in latex/plots.tex.
PLOT_MIN_VALUE = 1e-8

# Position of runs that exceeded the time or memory limit in the plots of the runtimes. This must be
# larger than the time limit and match \plottimeout in latex/plots.tex.
PLOT_TIMEOUT = 20000
# The csv columns with runtimes start with one of these.
TIME_COLUMNS = ("bisimulation-time-", "checking-time-", "wallclock-time-")

# Classes of the absolute error of a run: the name of the class and the error that has to be exceeded.
# Runs with a smaller error are in the class "low" and runs without any error are in the class "none".
ERROR_CLASSES = (("high", 0.1), ("medium", 1e-2), ("small", 1e-3))

# The kinds of properties and the placeholders that provide them.
PROPERTY_KINDS = {"property-finite-horizon": "fin", "property": "indef"}
KIND_TEXT = {"indef": "indefinite horizon", "fin": "finite horizon"}


class Config:
    """A configuration together with what can be derived from its command line."""

    def __init__(self, id, entry):
        self.id = id
        self.entry = entry
        cmd = entry["cmd"]
        # The model that the configuration runs on is the index key of its input file: mdp or imdp<identifier>,
        # where the identifier distinguishes several IMDPs that were learned for an MDP (see mdp_to_imdp.py).
        models = [name for file in entry.get("input-files", []) for name in placeholders(file)]
        self.model = models[0] if models else "mdp"
        self.is_imdp = self.model != "mdp"
        self.identifier = self.model[len("imdp"):] if self.model.startswith("imdp") else ""
        tolerance = re.search(r"--bisimulation:tolerance\s+(\S+)", cmd)
        # None if the configuration does not apply bisimulation quotienting
        self.tolerance = float(tolerance.group(1)) if tolerance else None
        self.tolerance_text = tolerance.group(1) if tolerance else None
        self.exports_quotient = bool(entry.get("output-files"))
        tokens = shlex.split(cmd)
        # The argument with the properties, which are checked in the order in which they are given.
        self.property_token = tokens[tokens.index("--prop") + 1] if "--prop" in tokens[:-1] else ""
        self.kinds = self.kinds_of(self.property_token.split(";"))

    @staticmethod
    def kinds_of(parts):
        kinds = []
        for part in parts:
            names = [name for name in placeholders(part) if name in PROPERTY_KINDS]
            if len(names) == 1:
                kinds.append(PROPERTY_KINDS[names[0]])
        return kinds

    def checked_kinds(self, benchmark_id, benchmark):
        """The kinds of the properties that are checked for the benchmark, in the order of checking."""
        return self.kinds_of(kept_parts(self.property_token, benchmark_values(benchmark_id, benchmark)))

    @property
    def label(self):
        model = "MDP" if self.model == "mdp" else f"iMDP {self.identifier}".rstrip()
        if self.tolerance is None:
            return model
        return f"{model} bisim" if self.tolerance == 0 else f"{model} \u03b5={self.tolerance_text}"

    @property
    def csv_label(self):
        if self.tolerance is None:
            return self.model
        return f"{self.model}-exact" if self.tolerance == 0 else f"{self.model}-{self.tolerance_text}"

    def sort_key(self):
        return (self.is_imdp, self.model, -1 if self.tolerance is None else self.tolerance)


class PropertyResult:
    """The outcome of checking a single property: its status, value and model checking time."""

    def __init__(self, status, value=None, time=None):
        self.status = status
        self.value = value
        self.time = time


class Run:
    """What the log file of an invocation tells about it.

    The parts of a run are evaluated independently: if, e.g., the time limit was exceeded while
    checking a property, the quotient and the results of the properties checked before are still read.
    """

    def __init__(self, log, kinds=()):
        self.log = log
        self.text = log.read_text(errors="replace") if log.is_file() else None
        # The output of the tool, without the result of evalquo
        self.tool_text = (self.text or "").split(EVALQUO_MARKER)[0]
        self.status = self.status_of()
        self.wall_time = self.number(r"^Wallclock time:\t(\S+)$", self.tool_text)
        self.bisim_time = self.number(r"^Time for bisimulation minimization: (\S+?)s\.$", self.tool_text)
        # The model is printed after its construction and again after preprocessing it.
        states = re.findall(r"^States: \t(\d+)$", self.tool_text, re.MULTILINE)
        self.quotient_states = int(states[1]) if len(states) > 1 and self.bisim_time is not None else None
        self.properties = self.property_results(kinds)
        self.relation = self.evalquo_relation()

    def status_of(self):
        """How the run ended: ok, timeout, killed, error or None (if there is no (complete) log)."""
        return_code = re.search(r"^Return code:\t(\S+)$", self.tool_text, re.MULTILINE)
        if return_code is None:
            return None
        if return_code.group(1) == "None":
            return "timeout"
        if return_code.group(1) == "-9":
            return "killed"
        return "ok" if return_code.group(1) == "0" else "error"

    @staticmethod
    def number(pattern, text):
        match = re.search(pattern, text, re.MULTILINE)
        try:
            return float(match.group(1)) if match else None
        except ValueError:
            return None

    def property_results(self, kinds):
        """The result for each kind of property, where the i-th property that is checked has the i-th kind."""
        # The output for a property reaches from its announcement to the one of the next property.
        blocks = re.split(r'^Model checking property "[^"\n]*": ', self.tool_text, flags=re.MULTILINE)[1:]
        results = {}
        for i, kind in enumerate(kinds):
            block = blocks[i].split("\n" + "-" * 40)[0] if i < len(blocks) else ""
            value = self.number(r"^Result \(for initial states\): (\S+)$", block)
            if value is not None:
                results[kind] = PropertyResult("ok", value, self.number(r"^Time for model checking: (\S+?)s\.$", block))
            elif any(UNSUPPORTED.search(error) for error in ERROR_LINE.findall(block)):
                results[kind] = PropertyResult("unsupported")
            elif self.status in ("timeout", "killed", None):
                # The run ended while checking this property or before getting to it.
                results[kind] = PropertyResult(self.status)
            else:
                results[kind] = PropertyResult("error")
        return results

    def evalquo_relation(self):
        """How the iMDP quotient of this run relates to the MDP quotient: equal, finer, coarser or incomparable."""
        if self.text is None or EVALQUO_MARKER not in self.text:
            return None
        match = EVALQUO_RELATION.search(self.text.split(EVALQUO_MARKER)[-1])
        return match.group(1).split()[0] if match else None


def load_dict(path):
    with open(path) as f:
        return json.load(f)


def log_file(logdir, config, benchmark_id):
    return logdir / f"{config.id}_{benchmark_id}.log"


def quotient_file(outdir, config, benchmark_id, benchmark):
    """The quotient that the configuration produces for the benchmark, or None if it is not applicable."""
    values = benchmark_values(benchmark_id, benchmark)
    if not is_applicable(config.entry, values):
        return None
    output_files = resolve(config.entry, values)[2]
    return outdir / output_files[0]


def run_evalquo(evalquo, logdir, outdir, configs, benchmarks):
    """Compare each iMDP quotient with the MDP quotient and append the result to the log of the iMDP quotient."""
    mdp_configs = [c for c in configs if c.exports_quotient and c.model == "mdp"]
    imdp_configs = [c for c in configs if c.exports_quotient and c.is_imdp]
    if not mdp_configs or not imdp_configs:
        return
    if len(mdp_configs) > 1:
        sys.exit(f"expected a single configuration producing the MDP quotient, got {len(mdp_configs)}")
    counts = {"computed": 0, "present": 0, "missing": 0, "failed": 0}
    for benchmark_id, benchmark in benchmarks.items():
        mdp_quotient = quotient_file(outdir, mdp_configs[0], benchmark_id, benchmark)
        for config in imdp_configs:
            log = log_file(logdir, config, benchmark_id)
            imdp_quotient = quotient_file(outdir, config, benchmark_id, benchmark)
            if not log.is_file() or imdp_quotient is None:
                continue
            # Do not run evalquo again if the log already contains its result, e.g., from a former run.
            if Run(log).relation is not None:
                counts["present"] += 1
                continue
            if mdp_quotient is None or not mdp_quotient.is_file() or not imdp_quotient.is_file():
                counts["missing"] += 1
                continue
            if not evalquo.is_file():
                sys.exit(f"evalquo not found: {evalquo}")
            command = [str(evalquo), str(mdp_quotient), str(imdp_quotient)]
            print(f"evalquo {mdp_quotient.name} {imdp_quotient.name}", flush=True)
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.returncode != 0:
                counts["failed"] += 1
                print(f"  failed with return code {result.returncode}: {result.stdout.strip()}")
                continue
            counts["computed"] += 1
            with open(log, "a") as f:
                f.write(f"\n{'-' * 40}\n{EVALQUO_MARKER}{' '.join(command)}\nEvalquo output:\n{result.stdout}")
    print(f"evalquo: {counts['computed']} computed, {counts['present']} already in the log, "
          f"{counts['missing']} without both quotients, {counts['failed']} failed")


# A cell of the table consists of the values for the csv (one per csv column), the text for the html,
# the log file it links to and optionally a css class and a tooltip.
class Cell:
    def __init__(self, csv_values, text, run=None, css="", title=""):
        self.csv_values = csv_values
        self.text = text
        self.log = run.log if run is not None and run.text is not None else None
        self.css = css
        self.title = title


STATUS_TEXT = {"timeout": "TO", "killed": "killed", "unsupported": "n/s", "error": "ERR", None: "–"}


def failed_cell(run, csv_columns, status=None):
    """The cell for something that is not available, by default because of how the run ended.

    In the csv, the first column of the cell gets the status.
    """
    status = status or (run.status if run.status != "ok" else None)
    return Cell([status or ""] + [""] * (csv_columns - 1), STATUS_TEXT[status], run, "failed" if status else "none",
                title=status or "not available")


def format_time(seconds):
    return f"{seconds:.2f}s" if seconds < 10 else f"{seconds:.1f}s" if seconds < 100 else f"{seconds:.0f}s"


def quotient_cell(run, with_relation):
    """The number of states of the quotient.

    For an iMDP quotient, the cell also tells how the quotient relates to the MDP quotient (as determined by evalquo).
    """
    csv_columns = 2 if with_relation else 1
    if run.quotient_states is None:
        return failed_cell(run, csv_columns)
    text = f"{run.quotient_states:,}"
    if not with_relation:
        return Cell([run.quotient_states], text, run)
    if run.relation is None:
        return Cell([run.quotient_states, ""], text, run, title="not compared with the MDP quotient")
    article = {"equal": "equal to", "incomparable": "incomparable with"}.get(run.relation, f"{run.relation} than")
    return Cell([run.quotient_states, run.relation], text, run, RELATION_CSS[run.relation],
                f"{article} the MDP quotient")


def bisimulation_time_cell(run):
    if run.bisim_time is None:
        return failed_cell(run, 1)
    return Cell([run.bisim_time], format_time(run.bisim_time), run)


def property_type(benchmark):
    """The type of the property of a benchmark: Pmin, Pmax, Rmin or Rmax. Expected time counts as reward."""
    match = re.match(r"\s*([PRT])(?:\{[^}]*\})?(min|max)", benchmark.get("property", ""))
    return ("R" if match.group(1) == "T" else match.group(1)) + match.group(2) if match else ""


def difference_cells(run, exact_run, kind):
    """The absolute and the relative difference between the value of the given run and the one of the exact run."""
    result, exact_result = run.properties.get(kind), exact_run.properties.get(kind)
    if result is None:
        return [Cell([""], "–", run, "none", title="property not available")] * 2
    if result.status != "ok":
        return [failed_cell(run, 1, result.status)] * 2
    if exact_result is None or exact_result.status != "ok":
        return [Cell([""], "–", run, "none", title=f"no exact value ({exact_result.status if exact_result else 'not run'}), "
                                                        f"value: {result.value}")] * 2
    value, exact = result.value, exact_result.value
    absolute = abs(value - exact)
    if absolute == 0:
        relative = 0.0
    else:
        relative = absolute / abs(exact) if exact != 0 else float("inf")
    title = f"value: {value}, exact value: {exact}"
    return [Cell([difference], "0" if difference == 0 else f"{difference:.2e}", run, title=title)
            for difference in (absolute, relative)]


def value_cell(run, kind):
    """The value of the property of the given kind."""
    result = run.properties.get(kind)
    if result is None:
        return Cell([""], "–", run, "none", title="property not available")
    if result.status != "ok":
        return failed_cell(run, 1, result.status)
    return Cell([result.value], f"{result.value:.6g}", run, title=f"value: {result.value}")


def checking_time_cell(run, kind):
    """The time for model checking the property of the given kind."""
    result = run.properties.get(kind)
    if result is None:
        return Cell([""], "–", run, "none", title="property not available")
    if result.status != "ok" or result.time is None:
        return failed_cell(run, 1, result.status if result.status != "ok" else "error")
    return Cell([result.time], format_time(result.time), run, title=f"value: {result.value}")


def wall_time_cell(run):
    """The wallclock time of the whole run."""
    if run.status in ("timeout", "killed", None) or run.wall_time is None:
        return failed_cell(run, 1)
    return Cell([run.wall_time], format_time(run.wall_time), run, title="" if run.status == "ok" else run.status)


def build_table(logdir, configs, benchmarks):
    """The column groups, the columns and the rows of the table.

    A column is a tuple (group, html header, csv headers) and a row is a list with a Cell per column.
    """
    configs = sorted(configs, key=Config.sort_key)
    quotients = [c for c in configs if c.tolerance is not None]
    imdp_quotients = [c for c in quotients if c.is_imdp and c.exports_quotient]
    imdp_models = list(dict.fromkeys(c.model for c in configs if c.is_imdp))
    kinds = [kind for kind in ("indef", "fin") if any(kind in c.kinds for c in configs)]
    by_kind = {kind: [c for c in configs if kind in c.kinds] for kind in kinds}

    columns = [("", "benchmark", ["benchmark"]), ("", "type", ["property-type"]), ("", "states", ["states"])]
    # What mdp_to_imdp.py recorded about the learned iMDPs
    imdp_statistics = [(f"{model}-maxl1", "max. L1 diameter") for model in imdp_models] + \
                      [(f"{model}-learning-accuracy", "learning accuracy") for model in imdp_models]
    for key, group in imdp_statistics:
        model = key.split("-")[0]
        columns.append((group, f"iMDP {model[len('imdp'):]}".rstrip(), [key]))
    for config in quotients:
        with_relation = config in imdp_quotients
        columns.append(("quotient states", config.label, [f"quotient-states-{config.csv_label}"] +
                        ([f"quotient-relation-{config.csv_label}"] if with_relation else [])))
    for config in quotients:
        columns.append(("bisimulation time", config.label, [f"bisimulation-time-{config.csv_label}"]))
    for kind in kinds:
        for config in by_kind[kind]:
            columns.append((f"value, {KIND_TEXT[kind]}", config.label, [f"value-{kind}-{config.csv_label}"]))
    # The values obtained with bisimulation are compared with the one of the same iMDP without quotienting.
    # Without a configuration for that, they are compared with the value obtained with exact bisimulation.
    # compared[kind] consists of pairs of a configuration and the configuration it is compared with.
    compared = {}
    for kind in kinds:
        compared[kind] = []
        for model in imdp_models:
            imdp = [c for c in by_kind[kind] if c.model == model]
            exact = next((c for c in imdp if c.tolerance is None), None) or next((c for c in imdp if c.tolerance == 0), None)
            compared[kind] += [(c, exact) for c in imdp if exact is not None and c is not exact]
    # Index 0 is the absolute difference and index 1 the relative one.
    differences = [(index, kind) for kind in kinds for index in (0, 1)]
    for index, kind in differences:
        name = ("absolute", "absdiff") if index == 0 else ("relative", "reldiff")
        for config, _ in compared[kind]:
            columns.append((f"{name[0]} difference to exact iMDP value, {KIND_TEXT[kind]}",
                            config.label, [f"{name[1]}-{kind}-{config.csv_label}"]))
    for kind in kinds:
        for config in by_kind[kind]:
            columns.append((f"model checking time, {KIND_TEXT[kind]}", config.label,
                            [f"checking-time-{kind}-{config.csv_label}"]))
    for config in configs:
        columns.append(("wallclock time (whole run)", config.label, [f"wallclock-time-{config.csv_label}"]))

    rows = []
    for benchmark_id, benchmark in benchmarks.items():
        runs = {c.id: Run(log_file(logdir, c, benchmark_id), c.checked_kinds(benchmark_id, benchmark)) for c in configs}
        if all(run.text is None for run in runs.values()):
            continue
        states = benchmark.get("input-model", {}).get("states", "")
        ptype = property_type(benchmark)
        row = [Cell([benchmark_id], benchmark_id, css=ptype.lower()), Cell([ptype], ptype, css=ptype.lower()),
               Cell([states], f"{states:,}" if isinstance(states, int) else str(states))]
        for key, _ in imdp_statistics:
            value = benchmark.get(key, "")
            row.append(Cell([value], f"{value:.4g}" if isinstance(value, float) else str(value) or "\u2013",
                            css="" if value != "" else "none"))
        row += [quotient_cell(runs[c.id], c in imdp_quotients) for c in quotients]
        row += [bisimulation_time_cell(runs[c.id]) for c in quotients]
        for kind in kinds:
            row += [value_cell(runs[c.id], kind) for c in by_kind[kind]]
        for index, kind in differences:
            row += [difference_cells(runs[c.id], runs[exact.id], kind)[index] for c, exact in compared[kind]]
        for kind in kinds:
            row += [checking_time_cell(runs[c.id], kind) for c in by_kind[kind]]
        row += [wall_time_cell(runs[c.id]) for c in configs]
        rows.append(row)
    return columns, rows


def write_csv(path, columns, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([header for _, _, headers in columns for header in headers])
        for row in rows:
            writer.writerow([value for cell in row for value in cell.csv_values])


def write_plot_csv(path, columns, rows, benchmarks):
    """The table in a form that pgfplots can read.

    Numeric columns contain nan wherever there is no value (unsupported, ...), text columns contain none.
    In the columns with runtimes, a run that exceeded the time or memory limit has the value PLOT_TIMEOUT.
    These columns are added: benchmark-type is the type of the benchmark (e.g. mdpqvbs), property-class
    is P or R, depending on whether the property is about probabilities or rewards, and error-class-<configuration>
    classifies the largest absolute error of the configuration over the kinds of properties (see ERROR_CLASSES).
    """
    headers = [header for _, _, headers in columns for header in headers]
    is_text = [header in ("benchmark", "property-type") or header.startswith("quotient-relation-") for header in headers]

    def plot_value(header, value, text):
        if text:
            return value or "none"
        if isinstance(value, (int, float)):
            return value
        return PLOT_TIMEOUT if value in ("timeout", "killed") and header.startswith(TIME_COLUMNS) else "nan"

    # The columns with the absolute errors of each configuration
    error_columns = {}
    for index, header in enumerate(headers):
        match = re.fullmatch("absdiff-(?:" + "|".join(KIND_TEXT) + ")-(.*)", header)
        if match:
            error_columns.setdefault(match.group(1), []).append(index)

    def error_class(values, indices):
        errors = [values[index] for index in indices if isinstance(values[index], (int, float))]
        if not errors:
            return "none"
        return next((name for name, bound in ERROR_CLASSES if max(errors) > bound), "low")

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers + ["benchmark-type", "property-class"] + [f"error-class-{config}" for config in error_columns])
        for row in rows:
            raw_values = [value for cell in row for value in cell.csv_values]
            values = [plot_value(header, value, text) for header, value, text in zip(headers, raw_values, is_text)]
            benchmark = benchmarks[values[0]]
            writer.writerow(values + [benchmark.get("type", "unknown"), property_type(benchmark)[:1] or "none"] +
                            [error_class(raw_values, indices) for indices in error_columns.values()])


def write_quantile_csv(path, columns, rows, prefix):
    """The data for a quantile plot of the columns whose csv header starts with the given prefix.

    Such a header is <prefix>-<kind>-<configuration>. The file has a column for each configuration with its
    values for all benchmarks and all kinds of properties in ascending order: the value v in row i means
    that there are i properties with a value of at most v. Properties without a value, e.g. because
    of a timeout, do not occur. Values below PLOT_MIN_VALUE (in particular 0) are
    replaced by PLOT_MIN_VALUE so that they can be shown on a logarithmic axis.
    """
    headers = [header for _, _, headers in columns for header in headers]
    values = {}
    for index, header in enumerate(headers):
        match = re.fullmatch(re.escape(prefix) + "-(?:" + "|".join(KIND_TEXT) + ")-(.*)", header)
        if match:
            cells = [[value for cell in row for value in cell.csv_values][index] for row in rows]
            values.setdefault(match.group(1), []).extend(v for v in cells if isinstance(v, (int, float)))
    for column in values.values():
        column.sort()
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["i"] + list(values))
        for i in range(max((len(column) for column in values.values()), default=0)):
            writer.writerow([i + 1] + [max(column[i], PLOT_MIN_VALUE) if i < len(column) else "nan"
                                       for column in values.values()])


STYLE = """
body { font: 13px/1.35 system-ui, sans-serif; color: #1c1c1c; background: #fff; margin: 16px; }
h1 { font-size: 18px; }
p, ul { max-width: 70em; }
.legend span { padding: 1px 6px; border-radius: 3px; }
.scroll { overflow: auto; max-height: 85vh; border: 1px solid #c8c8c8; }
table { border-collapse: separate; border-spacing: 0; white-space: nowrap; font-variant-numeric: tabular-nums; }
th, td { padding: 3px 8px; border-right: 1px solid #e0e0e0; border-bottom: 1px solid #e0e0e0; text-align: right; }
thead th { position: sticky; top: 0; background: #f0f0f0; z-index: 2; text-align: center; }
thead tr:nth-child(2) th { top: 25px; cursor: pointer; }
thead tr:first-child th { height: 18px; border-left: 2px solid #9a9a9a; }
td:first-child, thead tr:nth-child(2) th:first-child { position: sticky; left: 0; background: #f7f7f7; text-align: left; z-index: 1; }
thead tr:nth-child(2) th:first-child { z-index: 3; }
.first { border-left: 2px solid #9a9a9a; }
a { color: inherit; text-decoration: none; }
a:hover { text-decoration: underline; }
td.pmax, span.pmax { background: #d9c8f2; }
td.pmin, span.pmin { background: #c4ebe3; }
td.rmax, span.rmax { background: #f7eba6; }
td.rmin, span.rmin { background: #d6d6d6; }
.agrees { background: #c8e6c9; }
.refines { background: #bbdefb; }
.differs { background: #ef9a9a; }
.coarser { background: #ffcc80; }
.failed { color: #a33; background: #f6f1f1; }
.none { color: #999; }
.toggles { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 10px 0; }
.toggles div { display: flex; flex-wrap: wrap; gap: 3px; align-items: center; }
.toggles button { font: inherit; font-size: 12px; padding: 1px 7px; border: 1px solid #9a9a9a; border-radius: 3px;
                  background: #dfe9f5; cursor: pointer; }
.toggles button.group { font-weight: 600; background: #c9d8ea; }
.toggles button.off { background: #fff; color: #999; text-decoration: line-through; }
.hidden { display: none; }
pre { font: 12px/1.4 ui-monospace, monospace; white-space: pre-wrap; }
"""

SORT_SCRIPT = """
document.querySelectorAll('thead tr:nth-child(2) th').forEach((th, column) => th.addEventListener('click', () => {
  const body = document.querySelector('tbody');
  const descending = th.dataset.order === 'asc';
  document.querySelectorAll('thead th').forEach(other => delete other.dataset.order);
  th.dataset.order = descending ? 'desc' : 'asc';
  const key = row => row.children[column].dataset.sort;
  const rows = Array.from(body.rows).sort((a, b) => {
    const x = key(a), y = key(b);
    if (x === '' || y === '') return (x === '') - (y === '');  // cells without a value come last
    const order = isNaN(x) || isNaN(y) ? x.localeCompare(y) : x - y;
    return descending ? -order : order;
  });
  rows.forEach(row => body.appendChild(row));
}));

// Buttons to show and hide columns. A group button toggles all columns of its group.
const groupHeaders = Array.from(document.querySelectorAll('thead tr:first-child th'));
const columnHeaders = Array.from(document.querySelectorAll('thead tr:nth-child(2) th'));
const sizes = groupHeaders.map(th => th.colSpan);
const groupOf = sizes.flatMap((size, group) => Array(size).fill(group));
const visible = columnHeaders.map(() => true);
const buttons = [];
function update() {
  document.querySelectorAll('thead tr:nth-child(2), tbody tr').forEach(row =>
    visible.forEach((v, column) => row.children[column].classList.toggle('hidden', !v)));
  groupHeaders.forEach((th, group) => {
    const count = visible.filter((v, column) => v && groupOf[column] === group).length;
    th.classList.toggle('hidden', count === 0);
    th.colSpan = Math.max(count, 1);
  });
  buttons.forEach(([button, columns]) => button.classList.toggle('off', !columns.some(column => visible[column])));
}
function addButton(parent, text, columns, css) {
  const button = document.createElement('button');
  button.textContent = text;
  button.className = css;
  button.addEventListener('click', () => {
    const show = !columns.some(column => visible[column]);
    columns.forEach(column => visible[column] = show);
    update();
  });
  parent.appendChild(button);
  buttons.push([button, columns]);
}
const toggles = document.querySelector('.toggles');
groupHeaders.forEach((th, group) => {
  const columns = columnHeaders.map((_, column) => column).filter(column => column > 0 && groupOf[column] === group);
  if (columns.length === 0) return;
  const box = document.createElement('div');
  if (th.textContent) addButton(box, th.textContent, columns, 'group');
  columns.forEach(column => addButton(box, columnHeaders[column].textContent, [column], ''));
  toggles.appendChild(box);
});
"""


def write_log_page(path, log):
    text = log.read_text(errors="replace")
    path.write_text(f"<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\"><title>{html.escape(log.name)}</title>"
                    f"<style>{STYLE}</style></head><body><h1>{html.escape(log.name)}</h1>"
                    f"<pre>{html.escape(text)}</pre></body></html>\n")


def write_html(path, page_dir, columns, rows):
    page_dir.mkdir(parents=True, exist_ok=True)
    pages = {}

    def page_of(log):
        if log not in pages:
            pages[log] = f"{page_dir.name}/{log.stem}.html"
            write_log_page(page_dir / f"{log.stem}.html", log)
        return pages[log]

    groups = []
    for group, _, _ in columns:
        if groups and groups[-1][0] == group:
            groups[-1][1] += 1
        else:
            groups.append([group, 1])
    first_of_group = {sum(size for _, size in groups[:i]) for i in range(len(groups))}

    def css_class(index, css=""):
        classes = (css + (" first" if index in first_of_group else "")).strip()
        return f' class="{classes}"' if classes else ""

    out = ["<!DOCTYPE html>", '<html><head><meta charset="utf-8"><title>Bisimulation results</title>',
           f"<style>{STYLE}</style></head><body>", "<h1>Bisimulation results</h1>",
           '<p class="legend">Each cell links to the log of the run it was taken from; hover over a cell for details. '
           "Click a column header to sort; use the buttons below to show or hide columns or groups of columns. "
           "The color of the benchmark name gives the type of its property: "
           '<span class="pmin">Pmin</span>, <span class="pmax">Pmax</span>, <span class="rmin">Rmin</span>, '
           '<span class="rmax">Rmax</span> (expected time counts as reward). '
           "The color of the number of states of an iMDP quotient tells how it relates to the MDP quotient: "
           '<span class="agrees">equal</span>, <span class="refines">finer</span>, '
           '<span class="coarser">coarser</span>, <span class="differs">incomparable</span>. '
           "TO: time limit exceeded, killed: terminated by signal 9 (e.g. out of memory), "
           "n/s: property not supported, ERR: other error, –: not run or not available.</p>",
           '<div class="toggles"></div>',
           '<div class="scroll"><table><thead><tr>']
    out += [f'<th colspan="{size}">{html.escape(group)}</th>' for group, size in groups]
    out.append("</tr><tr>")
    out += [f"<th{css_class(i)}>{html.escape(header)}</th>" for i, (_, header, _) in enumerate(columns)]
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            content = html.escape(cell.text)
            if cell.log is not None:
                content = f'<a href="{html.escape(page_of(cell.log))}">{content}</a>'
            sort_value = cell.csv_values[0] if isinstance(cell.csv_values[0], (int, float)) or i <= 1 else ""
            if sort_value == float("inf"):
                sort_value = "Infinity"  # as JavaScript spells it
            title = f' title="{html.escape(cell.title)}"' if cell.title else ""
            out.append(f'<td{css_class(i, cell.css)}{title} data-sort="{html.escape(str(sort_value))}">{content}</td>')
        out.append("</tr>")
    out += ["</tbody></table></div>", f"<script>{SORT_SCRIPT}</script>", "</body></html>"]
    path.write_text("\n".join(out) + "\n")
    return len(pages)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logdir", type=Path, help="directory with the logs written by run.py")
    parser.add_argument("outdir", type=Path, help="directory with the output files written by run.py")
    parser.add_argument("--tabledir", type=Path, default=Path("."),
                        help="directory that table.csv, table.html and the log pages are written to "
                             "(default: current directory)")
    parser.add_argument("--configs", type=Path, default=CONFIGS_FILE,
                        help=f"the configurations that were run (default: {CONFIGS_FILE})")
    parser.add_argument("--index", type=Path, default=INDEX_FILE,
                        help=f"the index of the benchmarks that were run (default: {INDEX_FILE})")
    parser.add_argument("--evalquo", type=Path, default=EVALQUO, help=f"the evalquo binary (default: {EVALQUO})")
    parser.add_argument("--no-evalquo", action="store_true",
                        help="do not run evalquo, only use the results that are already in the logs")
    args = parser.parse_args()

    if not args.logdir.is_dir():
        sys.exit(f"log directory not found: {args.logdir}")
    configs = [Config(id, entry) for id, entry in load_dict(args.configs).items()]
    benchmarks = load_dict(args.index)

    if not args.no_evalquo:
        run_evalquo(args.evalquo, args.logdir, args.outdir, configs, benchmarks)

    columns, rows = build_table(args.logdir, configs, benchmarks)
    args.tabledir.mkdir(parents=True, exist_ok=True)
    write_csv(args.tabledir / "table.csv", columns, rows)
    write_plot_csv(args.tabledir / "plotdata.csv", columns, rows, benchmarks)
    write_quantile_csv(args.tabledir / "quantile-absdiff.csv", columns, rows, "absdiff")
    pages = write_html(args.tabledir / "table.html", args.tabledir / "logpages", columns, rows)
    print(f"wrote {args.tabledir / 'table.csv'}, {args.tabledir / 'plotdata.csv'} and {args.tabledir / 'table.html'} "
          f"({len(rows)} benchmarks, {pages} log pages)")


if __name__ == "__main__":
    main()
