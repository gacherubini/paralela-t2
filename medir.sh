#!/usr/bin/env bash
# Coleta todos os dados do T2 em resultados/. Deve rodar dentro da alocacao de
# 2 nos exclusivos do job.sh. Experimentos:
#
#   forte.csv        imagem fixa, p = 2..32                  -> speed-up forte
#   fraca.csv        pixels por processo fixos                -> speed-up fraco
#   carga.csv        medidas de cada rank, para cada p        -> decomposicao da eficiencia
#   grao.csv         linhas por tarefa (k) com p maximo       -> granularidade/balanceamento
#   intensidade.csv  max_iter variando com p maximo           -> computacao x comunicacao
#   local.csv        mesmo p em 1 no x 2 nos                  -> custo da rede x HT
#   perfil.csv       custo de cada linha da imagem            -> origem do desbalanceamento
#   rastro_*.csv     linha do tempo de cada tarefa            -> Gantt
#
# Cada tempo e a MEDIANA de REPS execucoes; o CSV guarda tambem min e max para
# as barras de variabilidade.
set -euo pipefail
cd "$(dirname "$0")"

PROCS=${PROCS:-"2 4 8 16 32"}
REPS=${REPS:-5}
ITER=${ITER:-2000}
LADO=${LADO:-4096}              # imagem da escalabilidade forte (mesma do T1)
LADO_BASE=${LADO_BASE:-1024}    # lado por processo na escalabilidade fraca
GRAOS=${GRAOS:-"1 2 4 8 16 64"}
LADO_INT=${LADO_INT:-2048}      # imagem do experimento de intensidade
ITERS_INT=${ITERS_INT:-"250 500 1000 2000 4000 8000"}
PROCS_LOCAL=${PROCS_LOCAL:-"8 16"}
LOCAL=${LOCAL:-0}               # 1 = teste no notebook, sem Slurm

maior=$(echo $PROCS | tr ' ' '\n' | sort -n | tail -1)
estatico=$(( (LADO + maior - 2) / (maior - 1) ))   # 1 bloco por trabalhador

# ------------------------------------------------------------- lancador -----
# Nucleos FISICOS por no: acima disso por no, os ranks passam a dividir nucleo
# com hyper-threading e o Open MPI precisa contar as threads HT como slots.
if [ "$LOCAL" = 1 ]; then
    NOS=(localhost); NUC=64
else
    NOS=($(scontrol show hostnames "$SLURM_JOB_NODELIST"))
    NUC=$(LC_ALL=C lscpu | awk -F: '/^Core\(s\) per socket/{c=$2} /^Socket\(s\)/{s=$2} END{print c*s}')
fi

# lanca NP ONDE programa args...    ONDE = 2nos (round-robin) ou 1no
# Se MPIRUN estiver definido no ambiente, ele e usado como esta (ex.: srun).
lanca() {
    local np=$1 onde=$2; shift 2
    if [ -n "${MPIRUN:-}" ]; then $MPIRUN -n "$np" "$@"; return; fi
    if [ "$LOCAL" = 1 ]; then mpirun --oversubscribe -n "$np" "$@"; return; fi

    local por_no=$np ht=""
    [ "$onde" = 2nos ] && por_no=$(( (np + 1) / 2 ))
    [ "$por_no" -gt "$NUC" ] && ht="--use-hwthread-cpus"
    if [ "$onde" = 2nos ]; then
        mpirun --oversubscribe --map-by node $ht -n "$np" "$@"
    else
        mpirun --oversubscribe --host "${NOS[0]}:$((2 * NUC))" $ht -n "$np" "$@"
    fi
}

# Roda REPS vezes e imprime a linha da mediana + ;tmin;tmax.
mediana() {
    local i
    for ((i = 0; i < REPS; i++)); do "$@"; done | sort -t';' -k7 -g |
        awk -F";" -v n="$REPS" '{l[NR]=$0; t[NR]=$7}
             END {print l[int((n+1)/2)] ";" t[1] ";" t[n]}'
}

CAB='modo;processos;linhas_por_tarefa;largura;altura;max_iter;tempo;checksum;tmin;tmax'
mkdir -p resultados
tempo_de() { tail -1 "$1" | awk -F';' '{print $(NF-3)}'; }   # coluna tempo

echo "nos: ${NOS[*]} | nucleos fisicos/no: $NUC | p: $PROCS | reps: $REPS"
echo ">> onde cai cada rank com p=$maior (2 nos) e p=16 (1 no):"
lanca "$maior" 2nos hostname | sort | uniq -c
lanca 16 1no hostname | sort | uniq -c

# ---------------------------------------------------------- forte+carga -----
echo "$CAB" > resultados/forte.csv
echo "processos;k;rank;tarefas;linhas;ocupado;espera;envio;fim;tempo" > resultados/carga.csv
echo ">> forte ${LADO}x${LADO}, ${ITER} iter"
mediana ./mandelbrot_seq -w "$LADO" -a "$LADO" -i "$ITER" >> resultados/forte.csv
echo "   seq $(tempo_de resultados/forte.csv) s"
./mandelbrot_seq -w "$LADO" -a "$LADO" -i "$ITER" -l resultados/perfil.csv > /dev/null

# Uma execucao extra com -b: e dela que sai a decomposicao da eficiencia.
carga() {  # np k [args extras]
    local np=$1 k=$2; shift 2
    lanca "$np" 2nos ./mandelbrot_mpi -w "$LADO" -a "$LADO" -i "$ITER" -k "$k" -b "$@" \
        2>&1 >/dev/null | awk '/^carga;/{sub(/^carga;/,""); print}' >> resultados/carga.csv
}

for np in $PROCS; do
    mediana lanca "$np" 2nos ./mandelbrot_mpi -w "$LADO" -a "$LADO" -i "$ITER" \
        >> resultados/forte.csv
    echo "   p=$np $(tempo_de resultados/forte.csv) s"
done

# ----------------------------------------------------------------- grao -----
# O ultimo k da um unico bloco a cada trabalhador: distribuicao ESTATICA, sem
# saco de trabalho. E o contraste que mostra o ganho do balanceamento.
echo "$CAB" > resultados/grao.csv
echo ">> grao com p=$maior"
for k in $GRAOS $estatico; do
    mediana lanca "$maior" 2nos ./mandelbrot_mpi -w "$LADO" -a "$LADO" -i "$ITER" -k "$k" \
        >> resultados/grao.csv
    echo "   k=$k $(tempo_de resultados/grao.csv) s"
done

# ---------------------------------------------------------------- carga -----
# Por p com k=1 (decomposicao da eficiencia) e por k com p maximo (grao).
echo ">> carga por rank"
for np in $PROCS; do carga "$np" 1; done
for k in $GRAOS $estatico; do [ "$k" != 1 ] && carga "$maior" "$k"; done
# Linha do tempo (Gantt): saco de trabalho x um bloco fixo por trabalhador.
for k in 1 "$estatico"; do
    lanca "$maior" 2nos ./mandelbrot_mpi -w "$LADO" -a "$LADO" -i "$ITER" -k "$k" \
        -r "resultados/rastro_p${maior}_k${k}.csv" > /dev/null
done

# ---------------------------------------------------------------- fraca -----
# Pixels crescem por p (lado por sqrt(p)) sobre a mesma janela do plano: o
# custo medio por pixel fica constante.
echo "$CAB" > resultados/fraca.csv
echo ">> fraca ${LADO_BASE}x${LADO_BASE} por processo"
mediana ./mandelbrot_seq -w "$LADO_BASE" -a "$LADO_BASE" -i "$ITER" >> resultados/fraca.csv
for np in $PROCS; do
    lado=$(awk -v b="$LADO_BASE" -v p="$np" 'BEGIN{printf "%d", int(b*sqrt(p)+0.5)}')
    mediana lanca "$np" 2nos ./mandelbrot_mpi -w "$lado" -a "$lado" -i "$ITER" \
        >> resultados/fraca.csv
    echo "   p=$np ${lado}x${lado} $(tempo_de resultados/fraca.csv) s"
done

# ---------------------------------------------------------- intensidade -----
# Mesmo numero de mensagens e bytes, computacao por mensagem variando com
# max_iter: mostra a partir de que ponto a comunicacao domina.
echo "$CAB" > resultados/intensidade.csv
echo ">> intensidade ${LADO_INT}x${LADO_INT}, p=$maior"
for it in $ITERS_INT; do
    mediana ./mandelbrot_seq -w "$LADO_INT" -a "$LADO_INT" -i "$it" >> resultados/intensidade.csv
    mediana lanca "$maior" 2nos ./mandelbrot_mpi -w "$LADO_INT" -a "$LADO_INT" -i "$it" \
        >> resultados/intensidade.csv
    echo "   iter=$it $(tempo_de resultados/intensidade.csv) s"
done

# ---------------------------------------------------------------- local -----
# p=8:  1 no (1 rank/nucleo)          x 2 nos (4+4)    -> custo so da rede
# p=16: 1 no (2 ranks/nucleo, com HT) x 2 nos (8+8)    -> HT x rede
echo "onde;$CAB" > resultados/local.csv
echo ">> 1 no x 2 nos"
for np in $PROCS_LOCAL; do
    for onde in 1no 2nos; do
        linha=$(mediana lanca "$np" "$onde" ./mandelbrot_mpi -w "$LADO" -a "$LADO" -i "$ITER")
        echo "$onde;$linha" >> resultados/local.csv
        echo "   p=$np $onde $(tempo_de resultados/local.csv) s"
    done
done

echo "pronto. CSVs em resultados/"
