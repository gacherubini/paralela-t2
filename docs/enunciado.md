# Enunciado TPP2: MPI Coordenador/Trabalhador (CT)

Disciplina 4645J-04 — Computação Paralela — Turma 320 — 2026/2 — Prof. Cesar Augusto F. De Rose

O objetivo do trabalho é implementar, usando a biblioteca MPI, uma versão paralela seguindo o coordenador/trabalhador, do problema utilizado no primeiro trabalho de OpenMP (ou um novo problema caso o utilizado não seja adequado). Cada grupo deve entregar um relatório em .pdf de uma página com a análise dos resultados com o código em anexo (seguir modelo proposto).

O coordenador (mestre) ficará responsável pela gerência do saco de trabalho (normalmente uma matriz), distribuindo as unidades de trabalho (normalmente vetores) para os trabalhadores e recebendo de volta os vetores processados e guardando-os novamente no saco (a recepção deve ser por ordem de chegada, ou seja, de quem ficar pronto primeiro). A ordem original dos vetores no saco deve ser mantida. Os trabalhadores por sua vez, receberão os vetores a serem processados, realizarão o processamento com o algoritmo fornecido e retornarão o vetor para o mestre. A iniciativa deve ser dos trabalhadores, ou seja, eles que pedem trabalho ao coordenador que vai atendendo estas demandas até que o saco esteja vazio (balanceamento automático de carga). Neste momento são enviadas mensagens de término aos trabalhadores. O programa SPMD deve funcionar para qualquer numero de trabalhadores para permitir uma análise da curva do Speed-UP e Eficiência.

Figura 1: mestre p0 com o saco de trabalho (m vetores de n posições; no exemplo n = 40, m = np*2) e escravos p1..p(np-1), cada um recebendo um vetor de 0..n para ordenação.

Os itens para avaliação são:

- execução da versão sequencial;
- implementação da versão paralela SPMD do algoritmo em C e MPI seguindo o modelo coordenador/trabalhador;
- medição dos tempos de execução para a versão sequencial e da versão paralela no LAD (usando 2 nós exclusivos da máquina atlantica totalizando 16 e 32 processos (HT) - cada nó possui 8 processadores capazes de executar 16 threads);
- cálculo do speed up (forte e fraco) e da eficiência para o caso de teste e diferentes números de processadores;
- análise do balanceamento da carga na execução do programa paralelo;
- clareza do código (utilização de comentários e nomes de variáveis adequadas);
- relatório no formato .pdf com uma página (coluna dupla), gráficos e tabelas em anexo na segunda página e código a partir da terceira (sem limite)
