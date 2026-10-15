/*
 * Conjunto de Mandelbrot - Trabalho 2 de Computacao Paralela
 * MPI no modelo coordenador/trabalhador (saco de trabalho)
 * Grupo 20 (cp32020) - PUCRS 2026/2
 *
 * Mesmo problema do T1 (OpenMP). Um unico arquivo gera as DUAS versoes:
 *
 *   gcc   -O2            -o mandelbrot_seq mandelbrot.c   -> sequencial
 *   mpicc -O2 -DPARALELO -o mandelbrot_mpi mandelbrot.c   -> MPI coord/trab
 *
 * Mapeamento para o modelo do enunciado (Figura 1):
 *
 *   saco de trabalho  = a imagem, uma matriz saco[altura][largura] de int
 *   unidade (vetor)   = uma LINHA da imagem (largura pixels); com -k agrupa
 *                       k linhas consecutivas numa mesma tarefa
 *   processamento     = calcular as iteracoes de Mandelbrot de cada pixel
 *
 * O coordenador (rank 0) nao calcula: so gerencia o saco. Os trabalhadores
 * (ranks 1..np-1) tomam a iniciativa, pedindo trabalho; recebem o indice da
 * proxima tarefa, calculam o vetor e devolvem o resultado, que ja serve como
 * o pedido seguinte. O coordenador recebe de MPI_ANY_SOURCE, ou seja, por
 * ordem de chegada, e guarda cada vetor na sua linha original do saco, o que
 * mantem a ordem da matriz independente de quem terminou primeiro. Quando o
 * saco esvazia, responde cada novo pedido com uma mensagem de termino.
 *
 * Saida no stdout, uma linha CSV:
 *   modo;processos;linhas_por_tarefa;largura;altura;max_iter;tempo;checksum
 * O checksum (soma de todas as iteracoes) deve ser IDENTICO entre a versao
 * sequencial e a paralela: e a prova de corretude.
 *
 * Instrumentacao para a analise (nao altera o calculo; so mede):
 *   -b      carga de cada processo no stderr (ver imprime_carga)
 *   -r arq  linha do tempo de cada tarefa (rank;linha;inicio;fim), para o Gantt
 *   -l arq  (so no sequencial) custo de cada linha em iteracoes
 */

/* Habilita clock_gettime/getopt mesmo sob -std=c11 estrito. */
#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef PARALELO
#include <mpi.h>
#endif

/* Janela do plano complexo, igual ao T1. Fixa em todos os experimentos. */
#define RE_MIN -2.0
#define RE_MAX  0.6
#define IM_MIN -1.3
#define IM_MAX  1.3

/* Rank do coordenador e as etiquetas (tags) das mensagens do protocolo. */
#define COORDENADOR   0
#define TAG_PEDIDO    1   /* trab -> coord: "estou livre", sem dados        */
#define TAG_RESULTADO 2   /* trab -> coord: vetor calculado (e novo pedido) */
#define TAG_TAREFA    3   /* coord -> trab: indice da primeira linha        */
#define TAG_FIM       4   /* coord -> trab: saco vazio, pode terminar       */

/* Parametros do problema, lidos da linha de comando. */
typedef struct {
    int largura;
    int altura;
    int max_iter;
    int linhas_por_tarefa;   /* granularidade da unidade de trabalho */
    int mostrar_carga;       /* -b */
    const char *arq_rastro;  /* -r: linha do tempo das tarefas      */
    const char *arq_perfil;  /* -l: custo por linha (sequencial)    */
} Parametros;

/*
 * Nucleo do calculo: itera z = z^2 + c e devolve em quantos passos o ponto
 * escapou do disco de raio 2, ou max_iter se nunca escapou. Pontos dentro do
 * conjunto custam max_iter iteracoes, pontos de fora escapam em poucas: o
 * custo de cada linha varia muito e nao da para prever, e por isso o saco de
 * trabalho com distribuicao sob demanda faz diferenca.
 */
static inline int mandel_ponto(double cr, double ci, int max_iter)
{
    double zr = 0.0, zi = 0.0;
    int it = 0;

    while (it < max_iter && zr * zr + zi * zi <= 4.0) {
        double zr_novo = zr * zr - zi * zi + cr;
        zi = 2.0 * zr * zi + ci;
        zr = zr_novo;
        it++;
    }
    return it;
}

/* Processa um vetor: calcula a linha y inteira e grava em vetor[0..largura). */
static void processa_linha(int y, int *vetor, const Parametros *p)
{
    const double passo_re = (RE_MAX - RE_MIN) / p->largura;
    const double passo_im = (IM_MAX - IM_MIN) / p->altura;
    const double ci = IM_MIN + y * passo_im;

    for (int x = 0; x < p->largura; x++)
        vetor[x] = mandel_ponto(RE_MIN + x * passo_re, ci, p->max_iter);
}

static long long soma_saco(const int *saco, const Parametros *p)
{
    long long soma = 0;
    for (size_t i = 0; i < (size_t)p->largura * p->altura; i++)
        soma += saco[i];
    return soma;
}

static int le_parametros(int argc, char **argv, Parametros *p)
{
    p->largura = 1024;
    p->altura = 1024;
    p->max_iter = 1000;
    p->linhas_por_tarefa = 1;
    p->mostrar_carga = 0;
    p->arq_rastro = NULL;
    p->arq_perfil = NULL;

    int opt;
    while ((opt = getopt(argc, argv, "w:a:i:k:br:l:")) != -1) {
        switch (opt) {
        case 'w': p->largura = atoi(optarg);           break;
        case 'a': p->altura = atoi(optarg);            break;
        case 'i': p->max_iter = atoi(optarg);          break;
        case 'k': p->linhas_por_tarefa = atoi(optarg); break;
        case 'b': p->mostrar_carga = 1;                break;
        case 'r': p->arq_rastro = optarg;              break;
        case 'l': p->arq_perfil = optarg;              break;
        default:  return -1;
        }
    }
    if (p->largura <= 0 || p->altura <= 0 || p->max_iter <= 0 ||
        p->linhas_por_tarefa <= 0)
        return -1;
    return 0;
}

#ifdef PARALELO

/* Medidas de um processo durante a execucao, em segundos desde o inicio. */
typedef struct {
    double tarefas;   /* quantas tarefas recebeu                             */
    double linhas;    /* quantas linhas (vetores) processou                  */
    double ocupado;   /* tempo calculando                                    */
    double espera;    /* tempo bloqueado em MPI_Recv, esperando o outro lado  */
    double envio;     /* tempo dentro de MPI_Send devolvendo resultados      */
    double fim;       /* instante em que recebeu FIM (trab) ou terminou (coord) */
} Carga;
#define CAMPOS_CARGA 6

/* Quantas linhas a tarefa que comeca em 'inicio' tem (a ultima pode ser menor). */
static int linhas_da_tarefa(int inicio, const Parametros *p)
{
    int resto = p->altura - inicio;
    return resto < p->linhas_por_tarefa ? resto : p->linhas_por_tarefa;
}

/*
 * Coordenador: gerencia o saco de trabalho.
 *
 * Mensagem de resultado = [indice_da_primeira_linha, pixels...]. O indice vai
 * junto do vetor para o coordenador saber onde guarda-lo no saco: como a
 * recepcao e por ordem de chegada, os vetores chegam fora de ordem.
 */
static void coordenador(int num_procs, const Parametros *p, int *saco,
                        double t0, Carga *c)
{
    const int tam_tarefa = p->largura * p->linhas_por_tarefa;
    int *buffer = malloc((size_t)(tam_tarefa + 1) * sizeof(int));

    int proxima_linha = 0;               /* topo do saco: proxima a entregar */
    int ativos = num_procs - 1;          /* trabalhadores ainda nao dispensados */

    while (ativos > 0) {
        MPI_Status st;

        /* Ordem de chegada: aceita pedido ou resultado de qualquer um. O tempo
         * parado aqui e o coordenador OCIOSO; se for alto, ele nao e gargalo. */
        double t_espera = MPI_Wtime();
        MPI_Recv(buffer, tam_tarefa + 1, MPI_INT, MPI_ANY_SOURCE,
                 MPI_ANY_TAG, MPI_COMM_WORLD, &st);
        c->espera += MPI_Wtime() - t_espera;
        int trabalhador = st.MPI_SOURCE;

        if (st.MPI_TAG == TAG_RESULTADO) {
            /* Devolve o vetor processado para a sua posicao original. */
            int inicio = buffer[0];
            int n = linhas_da_tarefa(inicio, p);
            memcpy(&saco[(size_t)inicio * p->largura], &buffer[1],
                   (size_t)n * p->largura * sizeof(int));
            c->linhas += n;
        }

        /* Todo pedido ou resultado e tambem um pedido de mais trabalho. */
        if (proxima_linha < p->altura) {
            MPI_Send(&proxima_linha, 1, MPI_INT, trabalhador, TAG_TAREFA,
                     MPI_COMM_WORLD);
            proxima_linha += p->linhas_por_tarefa;
            c->tarefas++;
        } else {
            MPI_Send(NULL, 0, MPI_INT, trabalhador, TAG_FIM, MPI_COMM_WORLD);
            ativos--;
        }
    }
    c->fim = MPI_Wtime() - t0;
    free(buffer);
}

/*
 * Trabalhador: pede trabalho, processa, devolve. A iniciativa e sempre dele;
 * o envio do resultado ja conta como o proximo pedido, economizando uma
 * mensagem por tarefa.
 *
 * rastro, se nao for NULL, recebe (linha, inicio, fim) de cada tarefa.
 */
static void trabalhador(const Parametros *p, double t0, Carga *c,
                        double *rastro)
{
    const int tam_tarefa = p->largura * p->linhas_por_tarefa;
    int *buffer = malloc((size_t)(tam_tarefa + 1) * sizeof(int));

    MPI_Send(NULL, 0, MPI_INT, COORDENADOR, TAG_PEDIDO, MPI_COMM_WORLD);

    for (;;) {
        MPI_Status st;
        int inicio;

        /* Tempo ate a tarefa chegar: latencia da rede + fila no coordenador. */
        double t_espera = MPI_Wtime();
        MPI_Recv(&inicio, 1, MPI_INT, COORDENADOR, MPI_ANY_TAG,
                 MPI_COMM_WORLD, &st);
        double t_chegou = MPI_Wtime();
        c->espera += t_chegou - t_espera;
        if (st.MPI_TAG == TAG_FIM) {
            c->fim = t_chegou - t0;
            break;
        }

        int n = linhas_da_tarefa(inicio, p);
        buffer[0] = inicio;
        for (int i = 0; i < n; i++)
            processa_linha(inicio + i, &buffer[1 + i * p->largura], p);
        double t_calculou = MPI_Wtime();
        c->ocupado += t_calculou - t_chegou;

        if (rastro) {
            double *r = &rastro[3 * (size_t)c->tarefas];
            r[0] = inicio;
            r[1] = t_chegou - t0;
            r[2] = t_calculou - t0;
        }
        c->tarefas++;
        c->linhas += n;

        MPI_Send(buffer, 1 + n * p->largura, MPI_INT, COORDENADOR,
                 TAG_RESULTADO, MPI_COMM_WORLD);
        c->envio += MPI_Wtime() - t_calculou;
    }
    free(buffer);
}

/*
 * Carga de todos os processos, no stderr, uma linha por rank:
 *   carga;processos;k;rank;tarefas;linhas;ocupado;espera;envio;fim;tempo_total
 * Para o coordenador (rank 0) "tarefas" e "linhas" sao as entregues/recebidas.
 */
static void imprime_carga(const Carga *cargas, int num_procs,
                          const Parametros *p, double tempo)
{
    for (int r = 0; r < num_procs; r++) {
        const Carga *c = &cargas[r];
        fprintf(stderr, "carga;%d;%d;%d;%.0f;%.0f;%.6f;%.6f;%.6f;%.6f;%.6f\n",
                num_procs, p->linhas_por_tarefa, r, c->tarefas, c->linhas,
                c->ocupado, c->espera, c->envio, c->fim, tempo);
    }
}

/*
 * Junta no coordenador a linha do tempo de todos os trabalhadores e grava
 * rank;linha;inicio;fim. Cada trabalhador fez um numero diferente de tarefas
 * (e o ponto do saco de trabalho), entao o tamanho vem da carga de cada um.
 */
static void grava_rastro(const Parametros *p, int rank, int num_procs,
                         const Carga *minha, const Carga *cargas,
                         const double *rastro)
{
    int *tam = NULL, *desl = NULL;
    double *todos = NULL;
    int meu_tam = 3 * (int)minha->tarefas;
    if (rank == COORDENADOR)
        meu_tam = 0;   /* o coordenador nao executa tarefas */

    if (rank == COORDENADOR) {
        tam = malloc(num_procs * sizeof(int));
        desl = malloc(num_procs * sizeof(int));
        int total = 0;
        for (int r = 0; r < num_procs; r++) {
            tam[r] = r == COORDENADOR ? 0 : 3 * (int)cargas[r].tarefas;
            desl[r] = total;
            total += tam[r];
        }
        todos = malloc((size_t)(total > 0 ? total : 1) * sizeof(double));
    }
    MPI_Gatherv(rastro, meu_tam, MPI_DOUBLE, todos, tam, desl, MPI_DOUBLE,
                COORDENADOR, MPI_COMM_WORLD);

    if (rank == COORDENADOR) {
        FILE *f = fopen(p->arq_rastro, "w");
        if (f) {
            fprintf(f, "rank;linha;inicio;fim\n");
            for (int r = 1; r < num_procs; r++)
                for (int i = 0; i < tam[r]; i += 3) {
                    const double *t = &todos[desl[r] + i];
                    fprintf(f, "%d;%.0f;%.6f;%.6f\n", r, t[0], t[1], t[2]);
                }
            fclose(f);
        } else {
            perror(p->arq_rastro);
        }
        free(tam);
        free(desl);
        free(todos);
    }
}

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);

    int rank, num_procs;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &num_procs);

    Parametros p;
    if (le_parametros(argc, argv, &p) != 0 || num_procs < 2) {
        if (rank == COORDENADOR)
            fprintf(stderr, "uso: mpirun -np N (N>=2) %s [-w largura] "
                    "[-a altura] [-i max_iter] [-k linhas_por_tarefa] [-b] "
                    "[-r rastro.csv]\n", argv[0]);
        MPI_Finalize();
        return 1;
    }

    int *saco = NULL;
    if (rank == COORDENADOR) {
        saco = malloc((size_t)p.largura * p.altura * sizeof(int));
        if (!saco) {
            fprintf(stderr, "memoria insuficiente para %dx%d\n",
                    p.largura, p.altura);
            MPI_Abort(MPI_COMM_WORLD, 1);
        }
    }

    /* Espaco para a linha do tempo: no pior caso um trabalhador faz todas. */
    double *rastro = NULL;
    if (p.arq_rastro && rank != COORDENADOR) {
        int max_tarefas = (p.altura + p.linhas_por_tarefa - 1)
                          / p.linhas_por_tarefa;
        rastro = malloc((size_t)max_tarefas * 3 * sizeof(double));
    }

    /* Todos partem juntos: o tempo mede so a distribuicao e o calculo. */
    MPI_Barrier(MPI_COMM_WORLD);
    double t0 = MPI_Wtime();

    Carga minha = {0};
    if (rank == COORDENADOR)
        coordenador(num_procs, &p, saco, t0, &minha);
    else
        trabalhador(&p, t0, &minha, rastro);

    double tempo = MPI_Wtime() - t0;

    /* Daqui em diante, fora do tempo medido: coleta das medidas de analise. */
    Carga *cargas = NULL;
    if (rank == COORDENADOR)
        cargas = malloc((size_t)num_procs * sizeof(Carga));
    MPI_Gather(&minha, CAMPOS_CARGA, MPI_DOUBLE, cargas, CAMPOS_CARGA,
               MPI_DOUBLE, COORDENADOR, MPI_COMM_WORLD);

    if (p.arq_rastro)
        grava_rastro(&p, rank, num_procs, &minha, cargas, rastro);

    if (rank == COORDENADOR) {
        printf("mpi;%d;%d;%d;%d;%d;%.6f;%lld\n", num_procs,
               p.linhas_por_tarefa, p.largura, p.altura, p.max_iter, tempo,
               soma_saco(saco, &p));
        if (p.mostrar_carga)
            imprime_carga(cargas, num_procs, &p, tempo);
        free(cargas);
        free(saco);
    }
    free(rastro);

    MPI_Finalize();
    return 0;
}

#else /* versao sequencial: o mesmo saco, processado vetor a vetor */

/* Relogio monotonico (MPI_Wtime nao existe sem MPI). */
static double agora_segundos(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

/* Custo de cada linha (soma das iteracoes dos seus pixels): mostra de onde
 * vem o desbalanceamento e permite prever a distribuicao estatica. */
static void grava_perfil(const int *saco, const Parametros *p)
{
    FILE *f = fopen(p->arq_perfil, "w");
    if (!f) {
        perror(p->arq_perfil);
        return;
    }
    fprintf(f, "linha;iteracoes\n");
    for (int y = 0; y < p->altura; y++) {
        long long soma = 0;
        for (int x = 0; x < p->largura; x++)
            soma += saco[(size_t)y * p->largura + x];
        fprintf(f, "%d;%lld\n", y, soma);
    }
    fclose(f);
}

int main(int argc, char **argv)
{
    Parametros p;
    if (le_parametros(argc, argv, &p) != 0) {
        fprintf(stderr, "uso: %s [-w largura] [-a altura] [-i max_iter] "
                "[-l perfil.csv]\n", argv[0]);
        return 1;
    }

    int *saco = malloc((size_t)p.largura * p.altura * sizeof(int));
    if (!saco) {
        fprintf(stderr, "memoria insuficiente para %dx%d\n",
                p.largura, p.altura);
        return 1;
    }

    double t0 = agora_segundos();
    for (int y = 0; y < p.altura; y++)
        processa_linha(y, &saco[(size_t)y * p.largura], &p);
    double tempo = agora_segundos() - t0;

    printf("seq;1;1;%d;%d;%d;%.6f;%lld\n", p.largura, p.altura, p.max_iter,
           tempo, soma_saco(saco, &p));
    if (p.arq_perfil)
        grava_perfil(saco, &p);
    free(saco);
    return 0;
}

#endif
