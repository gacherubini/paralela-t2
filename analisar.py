#!/usr/bin/env python3
"""Le os CSVs de medir.sh e imprime as tabelas da analise do T2.

    python3 analisar.py [diretorio_de_resultados]

So usa a biblioteca padrao, para rodar no proprio no do cluster. As funcoes de
calculo sao reaproveitadas por graficos.py, para que tabela e grafico saiam
sempre dos mesmos numeros.

Convencoes (p conta TODOS os processos, inclusive o coordenador):
    forte: S(p) = Tseq / T(p)          E(p) = S(p) / p
    fraca: S(p) = p * Tseq / T(p)      E(p) = Tseq / T(p)
"""
import csv
import os
import statistics
import sys

DIR = sys.argv[1] if len(sys.argv) > 1 else "resultados"


# ------------------------------------------------------------------ leitura --
def le(nome):
    caminho = os.path.join(DIR, nome)
    if not os.path.exists(caminho):
        return None
    with open(caminho) as f:
        return list(csv.DictReader(f, delimiter=";"))


def execucoes(nome):
    """(linha_seq, [linhas_mpi]) com os campos numericos convertidos."""
    linhas = le(nome) or []
    for r in linhas:
        for c in ("processos", "linhas_por_tarefa", "largura", "altura",
                  "max_iter"):
            r[c] = int(r[c])
        for c in ("tempo", "tmin", "tmax"):
            r[c] = float(r[c])
    seq = [r for r in linhas if r["modo"] == "seq"]
    mpi = [r for r in linhas if r["modo"] == "mpi"]
    return seq, mpi


def cargas():
    """{(p, k): {'coord': linha_rank0, 'trab': [linhas dos trabalhadores]}}"""
    grupos = {}
    for r in le("carga.csv") or []:
        p, k, rank = int(r["processos"]), int(r["k"]), int(r["rank"])
        reg = {c: float(r[c]) for c in ("tarefas", "linhas", "ocupado",
                                        "espera", "envio", "fim", "tempo")}
        reg["rank"] = rank
        g = grupos.setdefault((p, k), {"coord": None, "trab": []})
        if rank == 0:
            g["coord"] = reg
        else:
            g["trab"].append(reg)
    return grupos


# ------------------------------------------------------------------ calculo --
def escala(nome, fraca):
    """Pontos [(p, T, S, E, S_min, S_max)] de forte.csv ou fraca.csv.
    S_min/S_max vem de tmax/tmin: a faixa de variacao entre as repeticoes."""
    seq, mpi = execucoes(nome)
    if not seq:
        return None, []
    tseq = seq[0]["tempo"]
    pts = []
    for r in sorted(mpi, key=lambda r: r["processos"]):
        p = r["processos"]
        num = p * tseq if fraca else tseq
        s = num / r["tempo"]
        e = (tseq / r["tempo"]) if fraca else s / p
        pts.append((p, r["tempo"], s, e, num / r["tmax"], num / r["tmin"]))
    return seq[0], pts


PARCELAS = ("util", "inflacao", "coordenador", "comunicacao", "cauda", "outros")


def decomposicao(g, tseq):
    """Divide os recursos gastos, p * T, em parcelas que somam 1.

    util         Tseq: o trabalho que o sequencial tambem faria
    inflacao     soma(ocupado) - Tseq: o mesmo calculo ficou mais lento em
                 paralelo (HT dividindo o nucleo, cache, frequencia)
    coordenador  T inteiro do rank 0, que nao calcula
    comunicacao  soma do tempo dos trabalhadores dentro do MPI: esperando
                 tarefa (Recv) e devolvendo resultado (Send)
    cauda        soma de (T - fim_i): trabalhador ja dispensado esperando o
                 ultimo terminar -> desbalanceamento no final
    outros       o resto: laco, copias, medicao e preempcao pelo SO
    A parcela 'util' e exatamente a eficiencia E = Tseq / (p T).
    """
    trab = g["trab"]
    p = len(trab) + 1
    t = g["coord"]["tempo"]
    total = p * t
    ocupado = sum(w["ocupado"] for w in trab)
    partes = {
        "util": tseq,
        "inflacao": ocupado - tseq,
        "coordenador": t,
        "comunicacao": sum(w["espera"] + w["envio"] for w in trab),
        "cauda": sum(t - w["fim"] for w in trab),
    }
    partes["outros"] = total - sum(partes.values())
    return {k: v / total for k, v in partes.items()}


def balanceamento(g):
    """Metricas de equilibrio entre os trabalhadores de uma execucao."""
    ocup = [w["ocupado"] for w in g["trab"]]
    lin = [w["linhas"] for w in g["trab"]]
    media = statistics.mean(ocup)
    return {
        "ocup_min": min(ocup), "ocup_max": max(ocup),
        "max_med": max(ocup) / media,                    # 1.0 = perfeito
        "cv": statistics.pstdev(ocup) / media,           # dispersao relativa
        "lin_min": min(lin), "lin_max": max(lin),
        "coord_ocioso": g["coord"]["espera"] / g["coord"]["tempo"],
    }


def perfil():
    """Custo (iteracoes) de cada linha da imagem, na ordem."""
    return [int(r["iteracoes"]) for r in le("perfil.csv") or []]


def previsao_estatica(custos, trabalhadores, tseq):
    """Tempo previsto se cada trabalhador recebe um bloco contiguo fixo: o
    mais caro dita o fim. Comparado ao medido, valida que o desbalanceamento
    vem do custo das linhas e nao de outro efeito."""
    bloco = -(-len(custos) // trabalhadores)
    somas = [sum(custos[i:i + bloco]) for i in range(0, len(custos), bloco)]
    return tseq * max(somas) / sum(custos), max(somas) / statistics.mean(somas)


# ------------------------------------------------------------------ tabelas --
def tabela_escala(titulo, nome, fraca):
    seq, pts = escala(nome, fraca)
    if not seq:
        return
    print("=" * 18, titulo, "=" * 18)
    print("%-5s %-11s %9s %8s %9s %8s" % ("p", "imagem", "tempo(s)", "speedup",
                                          "efic.", "faixa S"))
    print("%-5s %-11s %9.3f" % ("seq", "%dx%d" % (seq["largura"], seq["altura"]),
                                seq["tempo"]))
    _, mpi = execucoes(nome)
    imagens = {r["processos"]: "%dx%d" % (r["largura"], r["altura"]) for r in mpi}
    for p, t, s, e, smin, smax in pts:
        print("%-5d %-11s %9.3f %8.2f %8.1f%% %4.2f-%.2f" %
              (p, imagens[p], t, s, 100 * e, smin, smax))
    # Corretude: na forte a imagem e a mesma, logo o checksum tambem.
    if not fraca:
        ruins = [r["processos"] for r in mpi if r["checksum"] != seq["checksum"]]
        print("checksum:", "OK, identico ao sequencial (%s)" % seq["checksum"]
              if not ruins else "DIFERE em p=%s" % ruins)
    print()


def main():
    tabela_escala("ESCALABILIDADE FORTE", "forte.csv", False)
    tabela_escala("ESCALABILIDADE FRACA", "fraca.csv", True)

    seq, _ = execucoes("forte.csv")
    tseq = seq[0]["tempo"] if seq else None
    grupos = cargas()

    if grupos and tseq:
        print("=" * 10, "DECOMPOSICAO DA EFICIENCIA (k=1, % de p*T)", "=" * 10)
        print("%-4s" % "p" + "".join("%12s" % c for c in PARCELAS)
              + "%10s" % "teto p-1")
        for (p, k) in sorted(grupos):
            if k != 1:
                continue
            d = decomposicao(grupos[(p, k)], tseq)
            print("%-4d" % p + "".join("%11.1f%%" % (100 * d[c]) for c in PARCELAS)
                  + "%9.1f%%" % (100 * (p - 1) / p))
        print("  util = eficiencia; teto p-1 = eficiencia maxima com 1 coordenador ocioso")
        print()

        print("=" * 14, "BALANCEAMENTO POR EXECUCAO", "=" * 14)
        print("%-4s %-5s %9s %9s %8s %7s %8s %8s %10s" %
              ("p", "k", "ocup.min", "ocup.max", "max/med", "CV", "lin.min",
               "lin.max", "coord.ocio"))
        for (p, k) in sorted(grupos):
            b = balanceamento(grupos[(p, k)])
            print("%-4d %-5d %9.3f %9.3f %8.3f %6.1f%% %8d %8d %9.1f%%" %
                  (p, k, b["ocup_min"], b["ocup_max"], b["max_med"],
                   100 * b["cv"], b["lin_min"], b["lin_max"],
                   100 * b["coord_ocioso"]))
        print()

    _, grao = execucoes("grao.csv")
    if grao:
        melhor = min(r["tempo"] for r in grao)
        p = grao[0]["processos"]
        print("=" * 12, "GRANULARIDADE (p=%d, linhas por tarefa)" % p, "=" * 12)
        print("%-6s %8s %9s %9s %10s" % ("k", "tarefas", "tempo(s)", "efic.",
                                         "vs melhor"))
        for r in grao:
            k = r["linhas_por_tarefa"]
            print("%-6d %8d %9.3f %8.1f%% %9.2fx" %
                  (k, -(-r["altura"] // k), r["tempo"],
                   100 * tseq / r["tempo"] / p if tseq else 0, r["tempo"] / melhor))
        custos = perfil()
        if custos and tseq:
            k_est = max(r["linhas_por_tarefa"] for r in grao)
            medido = max(grao, key=lambda r: r["linhas_por_tarefa"])["tempo"]
            prev, razao = previsao_estatica(custos, p - 1, tseq)
            print("estatico (k=%d): previsto pelo perfil %.3f s (bloco mais caro"
                  " = %.2fx a media), medido %.3f s" % (k_est, prev, razao, medido))
            print("saco ideal: Tseq/(p-1) = %.3f s" % (tseq / (p - 1)))
        print()

    _, inten = execucoes("intensidade.csv")
    seq_i, _ = execucoes("intensidade.csv")
    if inten:
        tseq_it = {r["max_iter"]: r["tempo"] for r in seq_i}
        print("=" * 12, "INTENSIDADE (computacao por mensagem)", "=" * 12)
        print("%-8s %10s %10s %8s %8s %16s" % ("max_iter", "seq(s)", "mpi(s)",
                                              "speedup", "efic.", "us calc/msg"))
        for r in inten:
            it, p = r["max_iter"], r["processos"]
            s = tseq_it[it] / r["tempo"]
            # tempo de calculo sequencial por linha = trabalho entregue por mensagem
            us = 1e6 * tseq_it[it] / r["altura"]
            print("%-8d %10.3f %10.3f %8.2f %7.1f%% %16.0f" %
                  (it, tseq_it[it], r["tempo"], s, 100 * s / p, us))
        print()

    local = le("local.csv")
    if local and tseq:
        print("=" * 16, "1 NO x 2 NOS", "=" * 16)
        print("%-4s %-6s %9s %8s %9s" % ("p", "onde", "tempo(s)", "speedup", "efic."))
        for r in local:
            p, t = int(r["processos"]), float(r["tempo"])
            print("%-4d %-6s %9.3f %8.2f %8.1f%%" % (p, r["onde"], t, tseq / t,
                                                    100 * tseq / t / p))
        print()


if __name__ == "__main__":
    main()
