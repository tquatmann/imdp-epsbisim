# Common settings of get_models.sh, perturb.sh and run.sh. All of them can also be set from the environment.

# The benchmarks, each of the form <model>:<epsilon>: the models for which the full version of the paper
# (arXiv:2110.00326) shows results (Table 1 and Appendix D), with the perturbation epsilon of M' given in the
# header of the respective table. The tables of the Leader models have no epsilon, as the results are the same
# for all of them; we take 0.001. Herman15 is not in the repository of the authors; it is built from
# models/herman.15.prism instead.
BENCHMARKS=${BENCHMARKS:-"Herman3:0.001 Herman5:0.0001 Herman7:0.001 Herman13:0.001 Herman15:0.0001 Leader5-5:0.001 Leader6-4:0.001
  BRP16-3:0.01 BRP32-2:0.0001 BRP64-4:0.001 Crowds4-5:0.0001 Crowds6-5:0.001 EGL5-2:0.0001 EGL5-4:0.001"}

DELTA=${DELTA:-0.01}                                     # probability that the perturbation of a distribution is larger
SEED=${SEED:-1}                                          # seed for perturbing
EPSILONS2=${EPSILONS2:-"0.00001 0.0001 0.001 0.01 0.1"}  # tolerance of the bisimulation

PRISM=${PRISM:-../bin/prism}
RUFFLE=${RUFFLE:-../bin/ruffle}
STORM=${STORM:-../bin/storm}
EVALQUO=${EVALQUO:-../tools/evalquo/build/bin/evalquo}

MODELDIR=${MODELDIR:-models}             # the unperturbed chains (get_models.sh)
PERTURBEDDIR=${PERTURBEDDIR:-perturbed}  # the perturbed chains (perturb.sh)
QUOTIENTDIR=${QUOTIENTDIR:-quotients}    # the partitions of the quotients (run.sh)
RESULTS=${RESULTS:-results.csv}          # the results (run.sh)

# The file with the perturbed chain of model $1.
perturbed_model() {
  echo "$PERTURBEDDIR/$1.umb"
}

# Stops if one of the given binaries does not exist.
require() {
  for binary in "$@"; do
    [ -x "$binary" ] || { echo "binary not found: $binary (see settings.sh)"; exit 1; }
  done
}
