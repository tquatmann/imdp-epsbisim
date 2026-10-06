#!/usr/bin/env python3
"""Handling of the %placeholders used in configurations.json.

A placeholder %key is replaced by the value of that key in the index.json entry of
the benchmark; %name is replaced by the name of the benchmark.
"""

import re
import shlex
from pathlib import PurePosixPath

# Configuration keys that contain placeholders.
CMD_KEY = "cmd"
INPUT_FILES_KEY = "input-files"
OUTPUT_FILES_KEY = "output-files"

PLACEHOLDER = re.compile(r"%([A-Za-z][A-Za-z0-9-]*)")


def placeholders(text):
    """The placeholder names occurring in a string, in order of appearance."""
    result = []
    for name in PLACEHOLDER.findall(text):
        if name not in result:
            result.append(name)
    return result


def substitute(text, values):
    """Replace the placeholders in a string by their values."""
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def benchmark_values(benchmark_id, benchmark):
    """The placeholder values a benchmark provides."""
    values = {key: value for key, value in benchmark.items() if isinstance(value, str)}
    values["name"] = benchmark_id
    return values


def kept_parts(token, values):
    """The parts of a ';'-separated argument that the benchmark provides all placeholder values for.

    This way, a list of properties only contains those that the benchmark has.
    """
    parts = [part.strip() for part in token.split(";")]
    return [part for part in parts if all(name in values for name in placeholders(part))]


def is_applicable(config, values):
    """Whether the benchmark provides a value for every placeholder in the files of the configuration.

    This is not the case if, e.g., the configuration runs on an imdp that the benchmark
    does not have. Placeholders without a value in the command line do not matter here,
    see resolve.
    """
    files = [*config.get(INPUT_FILES_KEY, []), *config.get(OUTPUT_FILES_KEY, [])]
    return all(name in values for file in files for name in placeholders(file))


def resolve(config, values):
    """The arguments, input files and output files of a configuration for a benchmark.

    The input files are relative to the directory of the index.json. As the tool is
    run in a directory that the input files are copied to, the arguments refer to
    the input files by their file name only. The output files are relative to that
    directory as well.

    An argument can consist of several parts separated by ';', e.g. a list of properties
    given as '%property-finite-horizon; %property'. Parts with a placeholder that the
    benchmark has no value for are omitted. If no part remains, the argument is omitted
    together with the option preceding it.
    """
    input_files = [substitute(f, values) for f in config.get(INPUT_FILES_KEY, [])]
    output_files = [substitute(f, values) for f in config.get(OUTPUT_FILES_KEY, [])]
    cmd_values = dict(values)
    for file in config.get(INPUT_FILES_KEY, []):
        for name in placeholders(file):
            cmd_values[name] = PurePosixPath(values[name]).name
    # Substitute after splitting so that a value with spaces (a property) stays a single argument.
    args = []
    for token in shlex.split(config[CMD_KEY]):
        parts = kept_parts(token, cmd_values)
        if not parts:
            if args and args[-1].startswith("-"):
                args.pop()
            continue
        args.append("; ".join(substitute(part, cmd_values) for part in parts))
    return args, input_files, output_files
