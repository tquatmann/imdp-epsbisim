#!/usr/bin/env python3
"""Turn results.csv (written by run.sh) into a tex document with a table of the results, for the models of

    S. Kiefer and Q. Tang: Approximate Bisimulation Minimisation. FSTTCS 2021.

Usage: ./make_table.py [results.csv [results.tex]]      and then e.g.  pdflatex results.tex
"""

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

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


def color(row):
    """The color of a quotient by how its partition relates to the one of the quotient of the unperturbed chain:
    none if it is finer, yellow if it is equal and pink otherwise (coarser or incomparable)."""
    if row["relation"] == "finer":
        return None
    return "recovered" if row["relation"] == "equal" else "notfiner"


def summary_table(results):
    """One row per model and perturbation with the number of states of all quotients."""
    runs = [run for model in results.values() for epsilon, run in model.items() if epsilon != "-"]
    all_tolerances = tolerances(runs)
    lines = ["\\begin{center}\n\\begin{tabular}{lrr@{\\quad}lr@{\\quad}" + "r" * len(all_tolerances) + "}", "\\toprule",
             " & & & & & \\multicolumn{" + str(len(all_tolerances)) + "}{c}{states of the quotient of $\\mathcal{M}'$ for $\\epsilon_2 = {}$} \\\\",
             "model & $|\\mathcal{M}|$ & $|\\mathcal{M}/{\\sim}|$ & $\\epsilon$ & $|\\mathcal{M}'/{\\sim}|$ & " +
             " & ".join(epsilon_text(e) for e in all_tolerances) + " \\\\", "\\midrule"]
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
                cell_color = color(row)
                cells.append((f"\\cellcolor{{{cell_color}}}" if cell_color else "") + number(row["states"]))
            first = [model, number(original["none"]["states"]), number(original["exact"]["states"])] if i == 0 else ["", "", ""]
            lines.append(" & ".join(first + [epsilon_text(epsilon)] + cells) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}\n\\end{center}"]
    return "\n".join(lines)


def main():
    results_file = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "results.csv"
    tex_file = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "results.tex"
    results = load(results_file)

    document = ["\\documentclass[a4paper]{article}", "\\usepackage[margin=2cm]{geometry}", "\\usepackage{amsmath}",
                "\\usepackage{booktabs}", "\\usepackage[table]{xcolor}",
                "\\usepackage[Tol,keep-defaults]{colorblind}",
                "\\colorlet{recovered}{T-Q-L6}", "\\colorlet{notfiner}{T-Q-L8}",  # light yellow and pink
                "\\begin{document}", "\\section*{Recovering the quotient of a perturbed Markov chain}",
                "A rough reproduction of the experiments of Kiefer and Tang (\\emph{Approximate Bisimulation Minimisation}, "
                "FSTTCS 2021) with storm. $\\mathcal{M}$ is a labelled Markov chain from their benchmark set and "
                "$\\mathcal{M}'$ is a perturbed version of it, obtained as they do it for their large models: noise is added "
                "to each successor distribution such that its $L_1$-distance to the real distribution is at most "
                "$\\epsilon$ with probability $0.99$ and $2\\epsilon$ otherwise. "
                "We quotient $\\mathcal{M}'$ with storm's bisimulation minimisation with tolerance $\\epsilon_2$ and interval "
                "abstraction, and compare the resulting partition of the states with the one of the exact quotient "
                "$\\mathcal{M}/{\\sim}$ of the unperturbed chain. "
                "No color: the partition is finer. "
                "\\colorbox{recovered}{Yellow}: the partition is the same, i.e.\\ the quotient of the unperturbed chain is "
                "recovered. \\colorbox{notfiner}{Pink}: the partition is coarser than or incomparable with the one of "
                "$\\mathcal{M}/{\\sim}$.", ""]
    document += ["\\subsection*{All models}",
                 "Number of states of the quotients for all models and tolerances $\\epsilon_2$. "
                 "The perturbation $\\epsilon$ of each model is the one of the respective table of Kiefer and Tang.", "",
                 summary_table(results), ""]
    document += ["\\end{document}", ""]
    tex_file.write_text("\n".join(document))
    print(f"wrote {tex_file}")


if __name__ == "__main__":
    main()
