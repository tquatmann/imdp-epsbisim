#!/usr/bin/env python3
"""Turn results.csv (written by run.sh) into a tex document with tables like Table 1 of

    S. Kiefer and Q. Tang: Approximate Bisimulation Minimisation. FSTTCS 2021.

Usage: ./make_table.py [results.csv [results.tex]]      and then e.g.  pdflatex results.tex
"""

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The models that the paper shows detailed results for: Table 1 of the paper and the tables of Appendix D of its
# full version (arXiv:2110.00326). The perturbation (epsilon) of each model is the one of the paper, see
# settings.sh. Herman15 is not in the repository of the authors.
DETAILS = [
    ("The two models of Table~1 of Kiefer and Tang.", ["Herman5", "BRP32-2"]),
    ("The models of Appendix~D of the full version of Kiefer and Tang (arXiv:2110.00326).",
     ["Herman3", "Herman7", "Herman13", "Herman15", "Leader5-5", "Leader6-4", "BRP16-3", "BRP64-4",
      "Crowds4-5", "Crowds6-5", "EGL5-2", "EGL5-4"]),
]


def number(text):
    return f"{int(text):,}".replace(",", "\\,") if text.isdigit() else "--"


def epsilon_text(text):
    """An epsilon as it is written in the paper, e.g. 0.0001."""
    return f"{float(text):.5f}".rstrip("0")


def load(path):
    """The results as {model: {epsilon: {epsilon2: row}}}, where epsilon is "-" for the unperturbed chain."""
    results = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            results.setdefault(row["model"], {}).setdefault(row["epsilon"], {})[row["epsilon2"]] = row
    return results


def perturbations(model_results):
    """The perturbations (epsilon) that there are results for, in ascending order."""
    return sorted((epsilon for epsilon in model_results if epsilon != "-"), key=float)


def tolerances(runs):
    """The tolerances (epsilon2) that the given runs have results for, in ascending order."""
    return sorted({e for run in runs for e in run if e not in ("none", "exact")}, key=float)


def color(row, original):
    """Yellow if the quotient of the unperturbed chain is recovered, red if the quotient is smaller than that."""
    if row["relation"] == "equal":
        return "recovered"
    if row["states"].isdigit() and original["states"].isdigit() and int(row["states"]) < int(original["states"]):
        return "toosmall"
    return None


def detail_table(model, results, epsilon):
    """A table like one half of Table 1 of the paper."""
    original, run = results[model]["-"], results[model][epsilon]
    lines = ["\\begin{tabular}{lrrl}", "\\toprule",
             f"\\textbf{{{model}}} & \\# states & \\# trans & vs.\\ $\\mathcal{{M}}/{{\\sim}}$ \\\\", "\\midrule",
             f"$\\mathcal{{M}}$ \\& $\\mathcal{{M}}'$ & {number(original['none']['states'])} & {number(original['none']['transitions'])} & \\\\",
             f"$\\mathcal{{M}}/{{\\sim}}$ & {number(original['exact']['states'])} & {number(original['exact']['transitions'])} & \\\\",
             f"$\\mathcal{{M}}'/{{\\sim}}$ & {number(run['exact']['states'])} & {number(run['exact']['transitions'])} & {run['exact']['relation']} \\\\",
             "\\midrule",
             f"\\multicolumn{{4}}{{c}}{{Perturbed chain with $\\epsilon = {epsilon_text(epsilon)}$}} \\\\"]
    # As in the paper, consecutive tolerances with the same result share a row.
    groups = []
    for epsilon2 in tolerances([run]):
        row = run[epsilon2]
        key = (row["states"], row["transitions"], row["relation"])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(epsilon2)
        else:
            groups.append((key, [epsilon2]))
    for (states, transitions, relation), group in groups:
        values = ", ".join(epsilon_text(e) for e in group)
        header = f"$\\epsilon_2 = {values}$" if len(group) == 1 else f"$\\epsilon_2 \\in \\{{{values}\\}}$"
        row_color = color(run[group[0]], original["exact"])
        prefix = f"\\rowcolor{{{row_color}}} " if row_color else ""
        lines += [f"\\multicolumn{{4}}{{c}}{{{header}}} \\\\",
                  f"{prefix}storm & {number(states)} & {number(transitions)} & {relation} \\\\"]
    lines += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(lines)


def summary_table(results):
    """One row per model and perturbation with the number of states of all quotients."""
    runs = [run for model in results.values() for epsilon, run in model.items() if epsilon != "-"]
    all_tolerances = tolerances(runs)
    lines = ["\\begin{longtable}{lrr@{\\quad}lr@{\\quad}" + "r" * len(all_tolerances) + "}", "\\toprule",
             " & & & & & \\multicolumn{" + str(len(all_tolerances)) + "}{c}{states of the quotient of $\\mathcal{M}'$ for $\\epsilon_2 = {}$} \\\\",
             "model & $|\\mathcal{M}|$ & $|\\mathcal{M}/{\\sim}|$ & $\\epsilon$ & $|\\mathcal{M}'/{\\sim}|$ & " +
             " & ".join(epsilon_text(e) for e in all_tolerances) + " \\\\", "\\midrule", "\\endhead"]
    for model, model_results in results.items():
        original = model_results.get("-")
        if original is None:
            continue
        for i, epsilon in enumerate(perturbations(model_results)):
            run = model_results[epsilon]
            cells = []
            for epsilon2 in ["exact"] + all_tolerances:
                row = run.get(epsilon2)
                if row is None:
                    cells.append("--")
                    continue
                cell_color = color(row, original["exact"])
                cells.append((f"\\cellcolor{{{cell_color}}}" if cell_color else "") + number(row["states"]))
            first = [model, number(original["none"]["states"]), number(original["exact"]["states"])] if i == 0 else ["", "", ""]
            lines.append(" & ".join(first + [epsilon_text(epsilon)] + cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{longtable}"]
    return "\n".join(lines)


def main():
    results_file = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results.csv"
    tex_file = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "results.tex"
    results = load(results_file)

    detail_groups = []
    for caption, models in DETAILS:
        tables = []
        for model in models:
            for epsilon in perturbations(results.get(model, {})):
                tables.append(detail_table(model, results, epsilon))
        if tables:
            detail_groups.append((caption, tables))

    document = ["\\documentclass[a4paper]{article}", "\\usepackage[margin=2cm]{geometry}", "\\usepackage{amsmath}",
                "\\usepackage{booktabs}", "\\usepackage{longtable}", "\\usepackage[table]{xcolor}",
                "\\definecolor{recovered}{HTML}{FFF2A8}", "\\definecolor{toosmall}{HTML}{F4B6B6}",
                "\\begin{document}", "\\section*{Recovering the quotient of a perturbed Markov chain}",
                "A rough reproduction of the experiments of Kiefer and Tang (\\emph{Approximate Bisimulation Minimisation}, "
                "FSTTCS 2021) with storm. $\\mathcal{M}$ is a labelled Markov chain from their benchmark set and "
                "$\\mathcal{M}'$ is a perturbed version of it, obtained as they do it for their large models: noise is added "
                "to each successor distribution such that its $L_1$-distance to the real distribution is at most "
                "$\\epsilon$ with probability $0.99$ and $2\\epsilon$ otherwise. "
                "We quotient $\\mathcal{M}'$ with storm's bisimulation minimisation with tolerance $\\epsilon_2$ and interval "
                "abstraction, and compare the resulting partition of the states with the one of the exact quotient "
                "$\\mathcal{M}/{\\sim}$ of the unperturbed chain. "
                "\\colorbox{recovered}{Yellow}: the partition is the same, i.e.\\ the quotient of the unperturbed chain is "
                "recovered. \\colorbox{toosmall}{Red}: the quotient has fewer states than $\\mathcal{M}/{\\sim}$. "
                "Otherwise, the partition is finer than, coarser than or incomparable with the one of $\\mathcal{M}/{\\sim}$.", ""]
    document += ["\\subsection*{All models}",
                 "Number of states of the quotients for all models and tolerances $\\epsilon_2$. "
                 "The perturbation $\\epsilon$ of each model is the one of the respective table of Kiefer and Tang.", "",
                 summary_table(results), ""]
    for caption, tables in detail_groups:
        # Two tables next to each other, as in the paper
        rows = ["\n\\hfill\n".join(tables[i:i + 2]) for i in range(0, len(tables), 2)]
        document += ["\\begin{table}[p]", "\\centering", "\n\n\\bigskip\n\n".join(rows),
                     f"\\caption{{{caption} In contrast to their tables, there is no number of iterations, the last column "
                     "tells how the partition relates to the one of $\\mathcal{M}/{\\sim}$, and the perturbed chain is "
                     "not the same as theirs (it has the same $\\epsilon$).}",
                     "\\end{table}", ""]
    document += ["\\end{document}", ""]
    tex_file.write_text("\n".join(document))
    print(f"wrote {tex_file}")


if __name__ == "__main__":
    main()
