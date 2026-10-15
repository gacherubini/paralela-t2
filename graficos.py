#!/usr/bin/env python3
"""Gera os graficos do T2 a partir dos CSVs de medir.sh.

    python3 graficos.py [diretorio_de_resultados]

Os numeros vem das mesmas funcoes de analisar.py, entao grafico e tabela nunca
divergem. Produz em resultados/ (PDF vetorial para o LaTeX, PNG para conferir):

    grafico_escala         speed-up e eficiencia, forte e fraca, com faixa min-max
    grafico_decomposicao   para onde vai cada fatia de p*T, por numero de processos
    grafico_balanceamento  custo por linha + tempo ocupado de cada trabalhador
    grafico_gantt          linha do tempo: saco de trabalho x bloco estatico
    grafico_comunicacao    eficiencia x computacao por mensagem; 1 no x 2 nos
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import analisar as a

# Paleta categorica validada (ordem fixa; adjacentes passam no teste de
# daltonismo), a mesma do T1.
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
AZUL, LARANJA = CORES[0], CORES[1]
TINTA_FORTE, TINTA_FRACA = "#0b0b0b", "#52514e"
REFERENCIA, SUPERFICIE, GRADE = "#9a9892", "#fcfcfb", "#ebe9e3"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5,
    "axes.edgecolor": "#d6d4cd", "axes.labelcolor": TINTA_FRACA,
    "xtick.color": TINTA_FRACA, "ytick.color": TINTA_FRACA,
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 7.5,
})


def titulo(ax, texto):
    ax.set_title(texto, fontsize=9, color=TINTA_FORTE, loc="left", pad=6)


def grade(ax, eixo="both"):
    ax.grid(True, axis=eixo, color=GRADE, linewidth=0.8)
    ax.set_axisbelow(True)


def eixo_procs(ax, procs):
    """log2 no x: os p dobram, em escala linear os pontos baixos se espremem."""
    ax.set_xscale("log", base=2)
    ax.set_xticks(procs)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: "%d" % v))
    ax.minorticks_off()
    ax.set_xlabel("Processos p (1 coordenador + p−1 trabalhadores)")
    grade(ax)


def salva(fig, nome):
    fig.tight_layout()
    for ext in ("pdf", "png"):
        caminho = os.path.join(a.DIR, "%s.%s" % (nome, ext))
        fig.savefig(caminho, dpi=200, facecolor=SUPERFICIE)
        print("gerado:", caminho)
    plt.close(fig)


# ---------------------------------------------------------------- escala ----
def grafico_escala():
    _, forte = a.escala("forte.csv", False)
    _, fraca = a.escala("fraca.csv", True)
    if not forte:
        return
    procs = [pt[0] for pt in forte]

    fig, (ax_s, ax_e) = plt.subplots(1, 2, figsize=(7.4, 2.7))
    ax_s.plot(procs, procs, "--", color=REFERENCIA, lw=1, label="ideal S=p")
    ax_s.plot(procs, [p - 1 for p in procs], ":", color=REFERENCIA, lw=1.2,
              label="teto do modelo S=p−1")
    ax_e.plot(procs, [100 * (p - 1) / p for p in procs], ":", color=REFERENCIA,
              lw=1.2, label="teto (p−1)/p")

    for rot, cor, pts in (("forte", AZUL, forte), ("fraca", LARANJA, fraca)):
        if not pts:
            continue
        xs = [pt[0] for pt in pts]
        sp = [pt[2] for pt in pts]
        ef = [100 * pt[3] for pt in pts]
        # Faixa min-max das repeticoes: mostra se a diferenca entre pontos e
        # maior que o ruido de medicao.
        erro = [[s - pt[4] for s, pt in zip(sp, pts)],
                [pt[5] - s for s, pt in zip(sp, pts)]]
        ax_s.errorbar(xs, sp, yerr=erro, marker="o", ms=4.5, lw=2, color=cor,
                      capsize=2, label=rot, markeredgecolor=SUPERFICIE, zorder=3)
        ax_e.plot(xs, ef, marker="o", ms=4.5, lw=2, color=cor, label=rot,
                  markeredgecolor=SUPERFICIE, zorder=3)

    ax_s.set_ylabel("Speed-up")
    ax_s.set_ylim(0, max(procs) * 1.05)
    ax_e.set_ylabel("Eficiência (%)")
    ax_e.set_ylim(0, 105)
    for ax, t in ((ax_s, "Speed-up"), (ax_e, "Eficiência")):
        eixo_procs(ax, procs)
        titulo(ax, t)
    ax_s.legend(loc="upper left")
    ax_e.legend(loc="lower left")
    salva(fig, "grafico_escala")


# ---------------------------------------------------------- decomposicao ----
ROTULOS = {
    "util": "trabalho útil (= eficiência)",
    "inflacao": "cálculo mais lento (HT/cache)",
    "coordenador": "coordenador (não calcula)",
    "comunicacao": "comunicação (Send/Recv)",
    "cauda": "ocioso no fim (desbalanceamento)",
    "outros": "outros",
}


def grafico_decomposicao():
    seq, _ = a.execucoes("forte.csv")
    grupos = a.cargas()
    ps = sorted(p for (p, k) in grupos if k == 1)
    if not seq or not ps:
        return
    tseq = seq[0]["tempo"]
    decs = [a.decomposicao(grupos[(p, 1)], tseq) for p in ps]

    fig, ax = plt.subplots(figsize=(7.4, 2.5))
    esquerda = [0.0] * len(ps)
    ys = list(range(len(ps)))
    for cor, parcela in zip(CORES, a.PARCELAS):
        larg = [max(0.0, 100 * d[parcela]) for d in decs]
        ax.barh(ys, larg, left=esquerda, color=cor, height=0.62,
                edgecolor=SUPERFICIE, linewidth=1.5, label=ROTULOS[parcela])
        # Rotulo so nas fatias largas: numero em toda fatia vira ruido.
        for y, l, w in zip(ys, esquerda, larg):
            if w >= 7:
                ax.text(l + w / 2, y, "%.0f%%" % w, ha="center", va="center",
                        fontsize=7, color=TINTA_FORTE)
        esquerda = [l + w for l, w in zip(esquerda, larg)]

    ax.set_yticks(ys)
    ax.set_yticklabels(["p=%d" % p for p in ps])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% dos recursos alocados (p × T)")
    grade(ax, "x")
    titulo(ax, "Para onde vai o tempo dos p processos")
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.28))
    salva(fig, "grafico_decomposicao")


# --------------------------------------------------------- balanceamento ----
def grafico_balanceamento():
    custos = a.perfil()
    grupos = a.cargas()
    if not custos or not grupos:
        return
    maior = max(p for (p, k) in grupos)
    ks = sorted(k for (p, k) in grupos if p == maior)
    k_saco, k_est = ks[0], ks[-1]

    fig, (ax_p, ax_c) = plt.subplots(1, 2, figsize=(7.4, 2.6),
                                     gridspec_kw={"width_ratios": [1, 1.3]})

    # Custo de cada linha, com as fronteiras dos blocos estaticos: o bloco que
    # cai no centro da imagem custa varias vezes a media.
    total = float(sum(custos))
    rel = [100 * c / total for c in custos]
    ax_p.fill_between(range(len(rel)), rel, color=AZUL, alpha=0.25, lw=0)
    ax_p.plot(range(len(rel)), rel, color=AZUL, lw=1)
    for i in range(0, len(custos), k_est):
        ax_p.axvline(i, color=REFERENCIA, lw=0.5, alpha=0.6)
    ax_p.set_xlim(0, len(custos))
    ax_p.set_ylim(bottom=0)
    ax_p.set_xlabel("Linha da imagem (cinza: blocos de k=%d)" % k_est)
    ax_p.set_ylabel("% do custo total")
    grade(ax_p, "y")
    titulo(ax_p, "Custo de cada linha (vetor)")

    largura = 0.42
    for i, (k, cor, rot) in enumerate((
            (k_saco, AZUL, "saco de trabalho, k=%d" % k_saco),
            (k_est, LARANJA, "1 bloco fixo por trabalhador, k=%d" % k_est))):
        trab = sorted(grupos[(maior, k)]["trab"], key=lambda w: w["rank"])
        ax_c.bar([w["rank"] + (i - 0.5) * largura for w in trab],
                 [w["ocupado"] for w in trab], width=largura, color=cor,
                 label=rot)
    ax_c.set_xlabel("Rank do trabalhador")
    ax_c.set_ylabel("Tempo calculando (s)")
    grade(ax_c, "y")
    titulo(ax_c, "Carga por trabalhador, p=%d" % maior)
    ax_c.legend(loc="upper left")
    salva(fig, "grafico_balanceamento")


# ------------------------------------------------------------------ gantt ---
def k_do_rastro(nome):
    """rastro_p<p>_k<k>.csv -> k"""
    return int(nome.rsplit("_k", 1)[1][:-4])


def grafico_gantt():
    arquivos = sorted((f for f in os.listdir(a.DIR)
                       if f.startswith("rastro_") and f.endswith(".csv")),
                      key=k_do_rastro)
    if len(arquivos) < 2:
        return
    rastros = []
    for f in (arquivos[0], arquivos[-1]):   # menor k (saco) e o estatico
        rastros.append((k_do_rastro(f), [
            (int(r["rank"]), int(r["linha"]), float(r["inicio"]), float(r["fim"]))
            for r in a.le(f)]))
    fim = max(t[3] for _, r in rastros for t in r)
    altura = max(t[1] for _, r in rastros for t in r) + 1

    fig, eixos = plt.subplots(1, 2, figsize=(7.4, 2.9), sharey=True)
    cmap = plt.get_cmap("Blues")
    for ax, (k, rastro) in zip(eixos, rastros):
        # Cor pela posicao da linha na imagem: claro = bordas, escuro = centro,
        # que e onde estao as linhas caras.
        for rank, linha, ini, fim_t in rastro:
            centro = 1 - abs(linha - altura / 2) / (altura / 2)
            ax.barh(rank, fim_t - ini, left=ini, height=0.8,
                    color=cmap(0.3 + 0.65 * centro), linewidth=0)
        ax.axvline(max(t[3] for t in rastro), color=LARANJA, lw=1, ls="--")
        ax.set_xlim(0, fim * 1.02)
        ax.set_xlabel("Tempo desde o início (s)")
        grade(ax, "x")
        titulo(ax, ("Saco de trabalho, k=%d" if k == 1 else
                    "1 bloco fixo por trabalhador, k=%d") % k)
    eixos[0].set_ylabel("Rank do trabalhador")
    eixos[0].invert_yaxis()
    fig.text(0.99, 0.01, "cor: claro = linhas da borda, escuro = centro da "
             "imagem · tracejado: fim do último", ha="right", fontsize=7,
             color=TINTA_FRACA)
    salva(fig, "grafico_gantt")


# ------------------------------------------------------------ comunicacao ---
def grafico_comunicacao():
    seq_i, inten = a.execucoes("intensidade.csv")
    local = a.le("local.csv")
    seq, _ = a.execucoes("forte.csv")
    if not inten or not seq:
        return
    tseq_it = {r["max_iter"]: r["tempo"] for r in seq_i}

    fig, (ax_i, ax_l) = plt.subplots(1, 2, figsize=(7.4, 2.5))

    # Mesmas mensagens, mais calculo por mensagem: a eficiencia sobe ate o
    # teto (p-1)/p quando a comunicacao fica desprezivel.
    p = inten[0]["processos"]
    us = [1e6 * tseq_it[r["max_iter"]] / r["altura"] for r in inten]
    ef = [100 * tseq_it[r["max_iter"]] / r["tempo"] / p for r in inten]
    ax_i.plot(us, ef, marker="o", ms=4.5, lw=2, color=AZUL,
              markeredgecolor=SUPERFICIE)
    for r, x, y in zip(inten, us, ef):
        ax_i.annotate("%d it" % r["max_iter"], (x, y), textcoords="offset points",
                      xytext=(0, -11), ha="center", fontsize=6.5,
                      color=TINTA_FRACA)
    ax_i.axhline(100 * (p - 1) / p, ls=":", color=REFERENCIA, lw=1.2)
    ax_i.set_xscale("log")
    ax_i.set_ylim(0, 105)
    ax_i.set_xlabel("Cálculo por mensagem (µs por linha)")
    ax_i.set_ylabel("Eficiência (%)")
    grade(ax_i)
    titulo(ax_i, "Computação × comunicação, p=%d" % p)

    if local:
        tseq = seq[0]["tempo"]
        ps = sorted({int(r["processos"]) for r in local})
        largura = 0.38
        for i, (onde, cor, rot) in enumerate((("1no", AZUL, "1 nó"),
                                              ("2nos", LARANJA, "2 nós"))):
            vals = []
            for pp in ps:
                t = [float(r["tempo"]) for r in local
                     if r["onde"] == onde and int(r["processos"]) == pp]
                vals.append(100 * tseq / t[0] / pp if t else 0)
            xs = [j + (i - 0.5) * largura for j in range(len(ps))]
            ax_l.bar(xs, vals, width=largura, color=cor, label=rot)
            for x, v in zip(xs, vals):
                ax_l.text(x, v + 1.5, "%.0f%%" % v, ha="center", fontsize=7,
                          color=TINTA_FORTE)
        ax_l.set_xticks(range(len(ps)))
        ax_l.set_xticklabels(["p=%d" % pp for pp in ps])
        ax_l.set_ylim(0, 118)
        ax_l.set_ylabel("Eficiência (%)")
        grade(ax_l, "y")
        titulo(ax_l, "Mesmo p em 1 nó × 2 nós")
        ax_l.legend(loc="upper right", ncol=2)
    salva(fig, "grafico_comunicacao")


if __name__ == "__main__":
    grafico_escala()
    grafico_decomposicao()
    grafico_balanceamento()
    grafico_gantt()
    grafico_comunicacao()
