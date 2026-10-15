#!/usr/bin/env bash
#SBATCH --job-name=mandel-mpi-teste
#SBATCH --nodes=2
#SBATCH --exclusive
#SBATCH --time=00:10:00
#SBATCH --output=slurm-teste-%j.out
#
# Ensaio de ~1 min ANTES do job de verdade: roda a bateria inteira do medir.sh
# em tamanho minimo, em resultados-teste/, para descobrir em minutos (e nao
# depois de meia hora) se o mpirun do cluster aceita as flags, se os ranks
# caem nos nos certos e se o checksum bate.
#
#   sbatch job-teste.sh ; depois: cat slurm-teste-*.out
# Se terminar com "ENSAIO OK", pode submeter o job.sh.
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"

make clean && make
RES=resultados-teste REPS=1 ITER=300 LADO=512 LADO_BASE=128 GRAOS="1 4" \
    LADO_INT=256 ITERS_INT="100 300" ./medir.sh
python3 analisar.py resultados-teste

# O checksum de toda execucao da forte tem de ser igual ao do sequencial.
if awk -F';' 'NR==2{ck=$8} NR>2 && $8!=ck{ruim=1} END{exit ruim}' resultados-teste/forte.csv
then echo "ENSAIO OK"
else echo "ENSAIO FALHOU: checksum difere"; exit 1
fi
