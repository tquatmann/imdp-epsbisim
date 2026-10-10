#!/bin/bash
# Gets the models of
#   S. Kiefer and Q. Tang: Approximate Bisimulation Minimisation. FSTTCS 2021 (full version: arXiv:2110.00326)
# as umb files: downloads the repository of the authors, in which the models are labelled Markov chains in the
# explicit format of PRISM (.tra and .lab files), lets PRISM export the models listed in settings.sh to umb
# and removes the repository again. A model that is given as a PRISM program in the model directory (Herman15,
# which is not in the repository, as herman.15.prism) is built and exported from that program instead.
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

# The PRISM program of a model in the model directory, which may not exist.
prism_program() {
  case "$1" in
    Herman*) echo "$MODELDIR/herman.${1#Herman}.prism" ;;
    *)       echo "$MODELDIR/$1.prism" ;;
  esac
}

# Runs PRISM with the given arguments to export model $1 to umb.
export_model() {
  model=$1; shift
  echo "$model"
  "$PRISM" "$@" -exportmodel "$MODELDIR/$model.umb" > "$MODELDIR/$model.prism.log" 2>&1 \
    && [ -s "$MODELDIR/$model.umb" ] || { echo "PRISM failed, see $MODELDIR/$model.prism.log"; exit 1; }
  rm "${MODELDIR:?}/${model:?}.prism.log"
}

repository=$(mktemp -d "${TMPDIR:-/tmp}/approximate-quotienting.XXXXXX") || exit 1
trap 'rm -rf "${repository:?}"' EXIT
git clone --quiet --depth 1 https://github.com/qiyitang71/approximate-quotienting.git "$repository" || exit 1

mkdir -p "$MODELDIR"
for benchmark in $BENCHMARKS; do
  model=${benchmark%:*}
  if [ -f "$(prism_program "$model")" ]; then
    export_model "$model" "$(prism_program "$model")"
    continue
  fi
  files="$repository/models/$(repository_path "$model")"
  [ -f "$files.tra" ] || { echo "$model is neither in the repository nor given as $(prism_program "$model")"; exit 1; }
  # The explicit engine imports large models much faster than the default one.
  export_model "$model" -ex -dtmc -importtrans "$files.tra" -importlabels "$files.lab"
done
