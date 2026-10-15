# Trabalho 2 - Computacao Paralela - Grupo 20
# Mesmo fonte, mesmas flags: a versao MPI so acrescenta -DPARALELO e o mpicc.

CC      = gcc
MPICC   = mpicc
CFLAGS  = -O2 -Wall -Wextra -std=gnu11

all: mandelbrot_seq mandelbrot_mpi

mandelbrot_seq: mandelbrot.c
	$(CC) $(CFLAGS) -o $@ $<

mandelbrot_mpi: mandelbrot.c
	$(MPICC) $(CFLAGS) -DPARALELO -o $@ $<

# Corretude: o checksum do MPI tem de bater com o sequencial, com varios
# numeros de processos e granularidades. Roda local (oversubscribe).
teste: all
	@ref=$$(./mandelbrot_seq -w 512 -a 512 -i 500 | cut -d';' -f8); \
	for np in 2 3 5 8; do for k in 1 7; do \
	  ck=$$(mpirun --oversubscribe -np $$np ./mandelbrot_mpi -w 512 -a 512 -i 500 -k $$k | cut -d';' -f8); \
	  [ "$$ck" = "$$ref" ] && echo "OK   np=$$np k=$$k" || { echo "FALHOU np=$$np k=$$k ($$ck != $$ref)"; exit 1; }; \
	done; done

clean:
	rm -f mandelbrot_seq mandelbrot_mpi

.PHONY: all teste clean
