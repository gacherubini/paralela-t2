#!/usr/bin/env bash
#SBATCH --job-name=mandel-mpi-g20
#SBATCH --nodes=2
#SBATCH --exclusive
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%j.out
#
# 2 nos exclusivos da atlantica (8 nucleos / 16 threads HT cada), como pede o
# enunciado. --exclusive garante que ninguem divide os nos com a medicao.
# A bateria completa (medir.sh) leva em torno de 30 min.
# Se o sbatch reclamar de particao, veja "sinfo" e acrescente --partition.
#
# submeter:  sbatch job.sh      acompanhar:  squeue -u $USER ; tail -f slurm-*.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"

mkdir -p resultados
{ echo "nos: $SLURM_JOB_NODELIST"; LC_ALL=C lscpu; free -g; gcc --version | head -1;
  mpirun --version 2>&1 | head -1; } > resultados/maquina.txt 2>&1

make clean && make
./medir.sh
python3 analisar.py | tee resultados/tabelas.txt

# matplotlib pode nao existir no no; nesse caso gere os graficos localmente.
if python3 -c "import matplotlib" 2>/dev/null; then
    python3 graficos.py
else
    echo "matplotlib ausente: rode 'python3 graficos.py' na maquina local"
fi
