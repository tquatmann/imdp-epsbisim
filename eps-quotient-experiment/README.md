# Recovering the quotient of a perturbed Markov chain

A rough reproduction of the experiments of S. Kiefer and Q. Tang, *Approximate Bisimulation
Minimisation* (FSTTCS 2021, full version: [arXiv:2110.00326](https://arxiv.org/abs/2110.00326))
with storm: given a perturbed Markov chain M', recover the bisimulation quotient of the unperturbed
chain M.

## Steps

```bash
./get_models.sh   # download the models of the paper and export them to umb with PRISM  -> models/
./perturb.sh      # perturb each model with ruffle                                       -> perturbed/
./run.sh          # quotient the perturbed chains with storm, compare with evalquo       -> results.csv
./make_table.py   # write the tables                                                     -> results.tex
pdflatex results.tex
```

All steps together take a few minutes.

## Settings

`settings.sh` lists the models with their perturbation `epsilon`, the bisimulation tolerances
`epsilon2` and the binaries (`../bin/prism`, `../bin/ruffle`, `../bin/storm`,
`../tools/evalquo/build/bin/evalquo`). Each setting can be overridden from the environment, e.g.
`STORM=/path/to/storm ./run.sh`.

## What is done

- **Models:** the 14 models that the full version of the paper shows results for (Table 1 and
  Appendix D), taken from the [repository of the authors](https://github.com/qiyitang71/approximate-quotienting).
  Herman15 is not in that repository; it is built from `models/herman.15.prism`. Each model is perturbed with the `epsilon` of its table in the
  paper.
- **Perturbation:** `ruffle --mode perturb-distribution` adds noise to each distribution such that
  its L1-distance to the real one is at most `epsilon` with probability 0.99 and `2 * epsilon`
  otherwise. The paper does this for its large models (and samples for its small ones).
  There is one perturbed chain per model; the paper has five.
- **Quotienting:** storm's bisimulation with `--bisimulation:tolerance epsilon2` and
  `--bisimulation:interval-abstraction`.
- **Check:** evalquo compares the partition of each quotient with the one of the exact quotient of
  the unperturbed chain. The quotient counts as recovered if the partitions are equal.
