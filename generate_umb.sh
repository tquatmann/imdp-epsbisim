#!/bin/zsh

python3 scripts/jani_to_umb.py # approx 1h

# approx 5 hours (depending on how many cores available)
python3 scripts/mdp_to_imdp.py --lambda 0.01 --samples 2000 --seed 0 --identifier a

#approx 50 hours (depending on how many cores available)
python3 scripts/mdp_to_imdp.py --lambda 0.01 --samples 20000 --seed 0 --identifier b


 python3 ../scripts/generate_invocations.py --invfile inv.json --logdir logs --outdir out --timelimit 7200
