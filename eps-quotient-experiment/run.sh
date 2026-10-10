#!/bin/bash
# Rough reproduction of the experiments of
#   S. Kiefer and Q. Tang: Approximate Bisimulation Minimisation. FSTTCS 2021 (full version: arXiv:2110.00326)
# with storm: given a perturbed Markov chain M', recover the bisimulation quotient of the unperturbed chain M.
#
# For each model M (get_models.sh) and its perturbed chain M' (perturb.sh):
#   1. compute the exact quotient M/~
#   2. compute the exact quotient M'/~ and, for each epsilon2, the quotient of M' for tolerance epsilon2 with
#      interval abstraction; compare each of them with M/~ (evalquo)
# The results are written to results.csv, which make_table.py turns into a tex document.
#
# Usage: ./run.sh       (models and parameters: see settings.sh)
cd "$(dirname "$0")" || exit 1
. ./settings.sh
require "$STORM" "$EVALQUO"

# Runs storm with the given arguments and prints "<states>,<transitions>" of the last model it reports.
sizes() {
  "$STORM" "$@" 2>&1 | awk '/^States:/ { s = $2 } /^Transitions:/ { t = $2 } /^ERROR/ { print > "/dev/stderr" } END { printf "%s,%s", s, t }'
}

# Prints how the quotient $2 relates to the quotient $1: equal, finer, coarser or incomparable.
relation() {
  "$EVALQUO" "$1" "$2" | sed -n 's/^Quotient 2 is \([a-z]*\) .*/\1/p'
}

mkdir -p "$QUOTIENTDIR"
echo "model,epsilon,epsilon2,states,transitions,relation" > "$RESULTS"
SECONDS=0
for benchmark in $BENCHMARKS; do
  model=${benchmark%:*}
  epsilon=${benchmark#*:}
  m="$MODELDIR/$model.umb"
  p=$(perturbed_model "$model")
  [ -f "$m" ] || { echo "model not found: $m (run ./get_models.sh)"; exit 1; }
  [ -f "$p" ] || { echo "perturbed model not found: $p (run ./perturb.sh)"; exit 1; }

  # 1. the unperturbed chain M and its quotient
  original="$QUOTIENTDIR/$model.tar.gz"
  echo "$model,-,none,$(sizes --explicit-umb "$m"),-" >> "$RESULTS"
  echo "$model,-,exact,$(sizes --explicit-umb "$m" --bisimulation --bisimulation:tolerance 0 --bisimulation:exportquotient "$original"),equal" >> "$RESULTS"

  # 2. the quotients of the perturbed chain M'
  q="$QUOTIENTDIR/$model.perturbed"
  echo "$model,$epsilon,none,$(sizes --explicit-umb "$p"),-" >> "$RESULTS"
  result=$(sizes --explicit-umb "$p" --bisimulation --bisimulation:tolerance 0 --bisimulation:exportquotient "$q.exact.tar.gz")
  echo "$model,$epsilon,exact,$result,$(relation "$original" "$q.exact.tar.gz")" >> "$RESULTS"
  for epsilon2 in $EPSILONS2; do
    result=$(sizes --explicit-umb "$p" --bisimulation --bisimulation:tolerance "$epsilon2" --bisimulation:interval-abstraction \
                   --bisimulation:exportquotient "$q.$epsilon2.tar.gz")
    echo "$model,$epsilon,$epsilon2,$result,$(relation "$original" "$q.$epsilon2.tar.gz")" >> "$RESULTS"
  done
  echo "$model (epsilon=$epsilon) done after ${SECONDS}s"
done
echo "Total time for all experiments: ${SECONDS}s"
python3 make_table.py