# T2 Paralela — Mandelbrot MPI coordenador/trabalhador (Grupo 20, cp32020)

Mesmo problema do T1 (Mandelbrot), agora em MPI com saco de trabalho.

| Modelo do enunciado | Aqui |
|---|---|
| saco de trabalho (matriz) | a imagem, `int saco[altura][largura]`, só no coordenador |
| unidade de trabalho (vetor) | uma linha da imagem (`-k` agrupa k linhas por tarefa) |
| processamento do vetor | iterações de Mandelbrot de cada pixel da linha |

**Protocolo** (tags em `mandelbrot.c`): trabalhador manda `PEDIDO` → coordenador
responde `TAREFA` (índice da linha) → trabalhador devolve `RESULTADO`
(`[índice, pixels...]`), que já vale como novo pedido → quando o saco esvazia,
o coordenador responde `FIM`. Recepção com `MPI_ANY_SOURCE` (ordem de chegada);
o índice que vai junto do vetor recoloca-o na linha original, mantendo a ordem.

## Arquivos

| Arquivo | O que é |
|---|---|
| `mandelbrot.c` | Fonte único: `gcc` → sequencial, `mpicc -DPARALELO` → MPI. Instrumentado (`-b`, `-r`, `-l`) |
| `Makefile` | `make`; `make teste` confere checksum MPI = sequencial (np 2,3,5,8; k 1,7) |
| `medir.sh` | Roda todos os experimentos → `resultados/*.csv` (mediana de 5, com min/max) |
| `analisar.py` | Tabelas: escala, decomposição da eficiência, balanceamento, grão, intensidade, 1×2 nós |
| `graficos.py` | Os 5 gráficos (usa as mesmas contas do `analisar.py`) |
| `job.sh` | `sbatch job.sh`: 2 nós exclusivos, make + medir + analisar + gráficos |
| `relatorio/relatorio.tex` | Relatório; `[?]` em vermelho = falta número do cluster |

## Rodar no cluster

```bash
ssh cp32020@atlantica.lad.pucrs.br          # via sparta se estiver fora da PUCRS
git clone https://github.com/gacherubini/paralela-t2 && cd paralela-t2
which mpicc mpirun && mpirun --version      # confirmar o MPI disponível
make                                        # compilar na hospedeira (não executar lá!)
sbatch job.sh                               # ~30 min
squeue -u $USER ; tail -f slurm-*.out
```

Depois, trazer `resultados/` para a máquina local (ou dar commit lá) e rodar
`python3 graficos.py` se o nó não tiver matplotlib.

**Conferir no início do `slurm-*.out`** (não deu para testar fora do LAD):

- Quantos ranks caíram em cada nó: com 32 em 2 nós, esperado 16 + 16; com 16 em
  1 nó, 16 no mesmo nó.
- Se o `mpirun` recusar alguma flag (MPI antigo ou MPICH), rode com outro
  lançador: `MPIRUN="srun --mpi=pmi2" sbatch job.sh` (perde só o experimento
  1 nó × 2 nós, que vira 2 nós nos dois casos).
- Se `mpicc` não existir: `module avail` / `module load openmpi`.

## Experimentos e o que cada um responde

| Experimento | Configuração | Pergunta |
|---|---|---|
| Forte | 4096², 2000 it, p = 2..32 | quanto acelera com mais processos? |
| Fraca | 1024² por processo (lado × √p) | o tempo fica constante se o problema cresce junto? |
| Decomposição | uma execução instrumentada por p | **por que** a eficiência não é 100%: útil, coordenador, comunicação, cálculo mais lento (HT), ociosidade final |
| Perfil | custo de cada linha (seq) | de onde vem o desbalanceamento |
| Grão | p = 32, k = 1..64 e k = 133 (1 bloco fixo por trabalhador = estático) | quanto o saco ganha da divisão estática, e qual grão é melhor |
| Gantt | linha do tempo de cada tarefa, k = 1 × k = 133 | o balanceamento visto no tempo |
| Intensidade | p = 32, 2048², max_iter 250..8000 | a partir de quanto cálculo por mensagem a comunicação deixa de pesar |
| 1 × 2 nós | p = 8 e 16 em 1 nó e em 2 nós | custo da rede × custo do HT |

`p` conta todos os processos, inclusive o coordenador, que não calcula: o teto
do speed-up é p−1 (eficiência máxima (p−1)/p).

## Teste local (macOS)

```bash
brew install open-mpi
make teste
LOCAL=1 PROCS="2 4 8" REPS=3 LADO=1024 LADO_BASE=256 LADO_INT=512 \
  ITERS_INT="100 1000" PROCS_LOCAL=4 GRAOS="1 4 16" ./medir.sh
python3 analisar.py && python3 graficos.py
```

Os números do notebook não valem para o relatório: o Mac tem 6 núcleos de
desempenho e o MPI faz espera ativa, então com 8 processos há preempção.
