#!/bin/bash
# Generates the perturbed Markov chains M' for the experiments (see run.sh): for each model M and its epsilon,
# ruffle adds noise to each distribution of M such that, with probability 1 - delta, its L1-distance to the
# real one is at most epsilon and otherwise it is 2 * epsilon (mode perturb-distribution). This is what the
# paper does for its large models. The seed is fixed, so the chains are reproducible.
#
# Usage: ./perturb.sh       (models and parameters: see settings.sh)
cd "$(dirname "$0")" || exit 1
. ./settings.sh
require "$RUFFLE"
[ -d "$MODELDIR" ] || { echo "models not found, run ./get_models.sh first"; exit 1; }

mkdir -p "$PERTURBEDDIR"
SECONDS=0
for benchmark in $BENCHMARKS; do
  model=${benchmark%:*}
  epsilon=${benchmark#*:}
  [ -f "$MODELDIR/$model.umb" ] || { echo "model not found: $MODELDIR/$model.umb"; exit 1; }
  output=$(perturbed_model "$model")
  "$RUFFLE" --input "$MODELDIR/$model.umb" --output "$output" --mode perturb-distribution \
            --delta "$epsilon" --lambda "$DELTA" --seed "$SEED" > "${output%.umb}.log" 2>&1 \
    || { echo "ruffle failed, see ${output%.umb}.log"; exit 1; }
  echo "$model (epsilon=$epsilon)"
done
echo "Total time for perturbing: ${SECONDS}s"
