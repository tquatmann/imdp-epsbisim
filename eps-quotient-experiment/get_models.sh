#!/bin/bash
# Gets the models of
#   S. Kiefer and Q. Tang: Approximate Bisimulation Minimisation. FSTTCS 2021 (full version: arXiv:2110.00326)
# as umb files: downloads the repository of the authors, in which the models are labelled Markov chains in the
# explicit format of PRISM (.tra and .lab files), lets PRISM export the models listed in settings.sh to umb
# and removes the repository again.
#
# Usage: ./get_models.sh
cd "$(dirname "$0")" || exit 1
. ./settings.sh
require "$PRISM"

# Where a model is in the repository (below models/, without extension).
repository_path() {
  case "$1" in
    Herman*) echo "HermanSmall/herman${1#Herman}" ;;
    Leader[3-5]-2|Leader3-*|Leader4-3) echo "LeaderSmall/${1#Leader}" ;;
    Leader*) echo "LeaderLarge/${1#Leader}" ;;
    BRP*)    echo "BRP/brp${1#BRP}" ;;
    Crowds*) runs=${1#Crowds}; echo "Crowds/0${runs%-*}-0${runs#*-}" ;;
    EGL*)    echo "EGL/${1#EGL}" ;;
  esac
}

repository=$(mktemp -d "${TMPDIR:-/tmp}/approximate-quotienting.XXXXXX") || exit 1
trap 'rm -rf "${repository:?}"' EXIT
git clone --quiet --depth 1 https://github.com/qiyitang71/approximate-quotienting.git "$repository" || exit 1

mkdir -p "$MODELDIR"
for benchmark in $BENCHMARKS; do
  model=${benchmark%:*}
  files="$repository/models/$(repository_path "$model")"
  [ -f "$files.tra" ] || { echo "$model is not in the repository"; exit 1; }
  echo "$model"
  # The explicit engine imports large models much faster than the default one.
  "$PRISM" -ex -dtmc -importtrans "$files.tra" -importlabels "$files.lab" -exportmodel "$MODELDIR/$model.umb" > "$MODELDIR/$model.prism.log" 2>&1 \
    && [ -s "$MODELDIR/$model.umb" ] || { echo "PRISM failed, see $MODELDIR/$model.prism.log"; exit 1; }
  rm "${MODELDIR:?}/${model:?}.prism.log"
done
