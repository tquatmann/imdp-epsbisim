#!/bin/zsh


# (re-)creating learned idtmc models
# From JANI to UMB (requires stormpy). Approx. 1 hour
python3 scripts/jani_to_umb.py
# Sample MDP to get IMDP. Approx 5 hours (depending on how many cores available)
python3 scripts/mdp_to_imdp.py --lambda 0.01 --samples 2000 --seed 0 --identifier a
# Sample MDP to get IMDP. Approx 50 hours (depending on how many cores available)
python3 scripts/mdp_to_imdp.py --lambda 0.01 --samples 20000 --seed 0 --identifier b

# Running the actual experiments
mkdir experiments
cd experiments
python3 ../scripts/generate_invocations.py --invfile inv.json --logdir logs --outdir out --timelimit 7200
# approx 50 hours
python3 ../scripts/run.py inv.json

# Postprocessing data
python3 ../scripts/postprocess.py  --tabledir table logs out
# copy over relevant data for plots
cp table/plotdata.csv ../latex/results/
cp table/quantile-absdiff.csv ../latex/results/