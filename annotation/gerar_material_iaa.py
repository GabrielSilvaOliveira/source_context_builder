#!/usr/bin/env python3
"""
gerar_material_iaa.py
─────────────────────────────────────────────────────────────────────────────
Gera a planilha de anotação para o estudo de concordância entre anotadores
(IAA) do benchmark do SCB.

Desenho:
  - Amostra ESTRATIFICADA de 24 consultas (6 por nível de dificuldade),
    seed fixa = 2026, para ser reproduzível e declarável na Metodologia.
  - Referência de fontes NEUTRA: só nomes de coluna, tipos e valores
    categóricos reais, extraídos do catalog_v4_base.json. NUNCA os
    embedding_hint do v3 — mostrá-los tornaria o IAA circular, pois mediria
    se o anotador reproduz a prosa do autor do gabarito.
  - Rótulos por par (consulta, fonte): P (primária), C (complementar),
    vazio (não usar). A distinção P/C importa porque o recall do benchmark
    usa SOMENTE as primárias.

Saída original: uma planilha por anotador, idêntica, com o nome dele no arquivo.

Versão do repositório: diferença única em relação ao script usado na anotação é a
interface de linha de comando (main). Sem o argumento --anotadores gera um único modelo
vazio, sem nome de participante (IAA_template.xlsx), a partir do catálogo base redigido.
"""

import json
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

SEED = 2026
POR_ESTRATO = 6
FONTE = "Arial"

AZUL = "1F4E79"
CINZA = "D9D9D9"
CINZA_CLARO = "F2F2F2"
AMARELO = "FFF2CC"
VERDE = "E2EFDA"

BORDA = Border(*[Side(style="thin", color="BFBFBF")] * 4)


def carregar_fontes(caminho_catalogo):
    """Extrai a descrição NEUTRA das 16 fontes a partir do catálogo base."""
    cat = json.load(open(caminho_catalogo, encoding="utf-8"))
    fontes = []
    for tipo, sub in (("sql", "tables"), ("api", "endpoints"),
                      ("spreadsheets", "files")):
        for nome, meta in (cat["sources"].get(tipo, {}).get(sub, {}) or {}).items():
            perfil = meta.get("value_profile") or {}
            colunas = []
            for col, v in perfil.items():
                kind = v.get("kind")
                if kind == "categorical" and v.get("values"):
                    vals = [x for x in v["values"] if str(x).strip() not in ("", "0")]
                    amostra = ", ".join(vals[:6])
                    colunas.append(f"{col} = {amostra}" if amostra else col)
                elif kind == "numeric" and v.get("range"):
                    colunas.append(f"{col} (numérico: {v['range'][0]}–{v['range'][1]})")
                else:
                    colunas.append(col)
            fontes.append({
                "id": f"{tipo}.{nome}",
                "tipo": {"sql": "Tabela SQL", "api": "Endpoint REST",
                         "spreadsheets": "Planilha"}[tipo],
                "n_campos": len(perfil),
                "colunas": colunas,
            })
    return fontes


def amostrar_consultas(caminho_benchmark):
    """Amostra estratificada por dificuldade, seed fixa."""
    queries = json.load(open(caminho_benchmark, encoding="utf-8"))["queries"]
    por_dif = {}
    for q in queries:
        por_dif.setdefault(q["difficulty"], []).append(q)
    rnd = random.Random(SEED)
    amostra = []
    for dif in sorted(por_dif):
        amostra += rnd.sample(por_dif[dif], POR_ESTRATO)
    amostra.sort(key=lambda q: q["id"])
    return amostra


# ─────────────────────────────────────────────────────────────────────────────

def aba_instrucoes(wb):
    ws = wb.create_sheet("Instruções", 0)
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 105

    linhas = [
        ("TÍTULO", "Estudo de concordância — seleção de fontes de dados"),
        ("", ""),
        ("H", "O que você vai fazer"),
        ("T", "Para cada pergunta, indicar QUAIS fontes de dados seriam necessárias para respondê-la."),
        ("T", "Você NÃO precisa responder a pergunta. Só dizer onde o dado estaria."),
        ("", ""),
        ("H", "Como preencher"),
        ("T", "Aba «Anotação»: cada linha é uma pergunta, cada coluna é uma fonte."),
        ("T", "Marque P  = fonte PRIMÁRIA. Sem ela a pergunta não pode ser respondida."),
        ("T", "Marque C  = fonte COMPLEMENTAR. Enriquece a resposta, mas não é indispensável."),
        ("T", "DEIXE EM BRANCO = a fonte não deve ser consultada para essa pergunta."),
        ("T", "Ao terminar cada pergunta, marque «Sim» na última coluna (Revisado)."),
        ("", ""),
        ("H", "Regras que tornam o estudo válido"),
        ("R", "1. Trabalhe SOZINHO. Não combine respostas com os outros participantes."),
        ("R", "2. Não peça ajuda a quem montou o estudo, nem consulte gabarito algum."),
        ("R", "3. Se ficar em dúvida, decida pelo seu melhor julgamento. Não deixe pergunta em branco."),
        ("R", "4. Toda pergunta tem pelo menos uma fonte PRIMÁRIA. Não existe resposta «nenhuma fonte»."),
        ("R", "5. Não há limite de fontes por pergunta, mas na maioria dos casos são 1 a 3."),
        ("", ""),
        ("H", "Onde consultar o que cada fonte contém"),
        ("T", "Aba «Fontes»: lista as 16 fontes com seus campos e exemplos de valores reais."),
        ("T", "É a única referência que você deve usar. Consulte à vontade, quantas vezes quiser."),
        ("", ""),
        ("H", "Tempo estimado"),
        ("T", "40 a 60 minutos. Pode fazer em mais de uma sessão."),
        ("", ""),
        ("H", "Ao terminar"),
        ("T", "Salve o arquivo mantendo o nome original e devolva ao responsável pelo estudo."),
        ("", ""),
        ("N", "Suas respostas serão usadas apenas de forma agregada, para medir se a tarefa é"),
        ("N", "bem definida. Não há resposta certa individual sendo avaliada, e o desempenho"),
        ("N", "de nenhum participante será identificado."),
    ]

    r = 1
    for tag, txt in linhas:
        c = ws.cell(row=r, column=2, value=txt)
        if tag == "TÍTULO":
            c.font = Font(name=FONTE, size=14, bold=True, color=AZUL)
        elif tag == "H":
            c.font = Font(name=FONTE, size=11, bold=True, color=AZUL)
        elif tag == "R":
            c.font = Font(name=FONTE, size=10, bold=True)
        elif tag == "N":
            c.font = Font(name=FONTE, size=9, italic=True, color="808080")
        else:
            c.font = Font(name=FONTE, size=10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    return ws


def aba_fontes(wb, fontes):
    ws = wb.create_sheet("Fontes")
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 100

    ws["A1"] = "As 16 fontes de dados disponíveis"
    ws["A1"].font = Font(name=FONTE, size=13, bold=True, color=AZUL)
    ws["A2"] = ("Campos e valores extraídos automaticamente do sistema. "
                "Use esta aba como referência ao preencher a aba «Anotação».")
    ws["A2"].font = Font(name=FONTE, size=9, italic=True, color="808080")

    cab = ["Identificador da fonte", "Tipo", "Campos que ela contém"]
    for j, t in enumerate(cab, start=1):
        c = ws.cell(row=4, column=j, value=t)
        c.font = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center")

    r = 5
    for f in fontes:
        ws.cell(row=r, column=1, value=f["id"]).font = Font(name=FONTE, size=10, bold=True)
        ws.cell(row=r, column=2, value=f["tipo"]).font = Font(name=FONTE, size=10)
        texto = " · ".join(f["colunas"])
        if len(texto) > 1800:
            texto = texto[:1800] + " … (demais campos omitidos)"
        cc = ws.cell(row=r, column=3, value=texto)
        cc.font = Font(name=FONTE, size=9)
        cc.alignment = Alignment(wrap_text=True, vertical="top")
        for j in range(1, 4):
            ws.cell(row=r, column=j).border = BORDA
            if (r % 2) == 0:
                ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=CINZA_CLARO)
        ws.row_dimensions[r].height = 58
        r += 1
    ws.freeze_panes = "A5"
    return ws


def aba_anotacao(wb, consultas, fontes):
    ws = wb.create_sheet("Anotação")

    ws["A1"] = "Marque P (primária) ou C (complementar). Deixe em branco se a fonte não deve ser usada."
    ws["A1"].font = Font(name=FONTE, size=11, bold=True, color=AZUL)
    ws["A2"] = ("Consulte a aba «Fontes» para ver o que cada uma contém. "
                "Toda pergunta tem pelo menos uma fonte PRIMÁRIA.")
    ws["A2"].font = Font(name=FONTE, size=9, italic=True, color="808080")

    LIN_CAB = 4
    ws.cell(row=LIN_CAB, column=1, value="ID").font = Font(name=FONTE, size=9, bold=True, color="FFFFFF")
    ws.cell(row=LIN_CAB, column=2, value="Pergunta").font = Font(name=FONTE, size=9, bold=True, color="FFFFFF")
    for j in (1, 2):
        ws.cell(row=LIN_CAB, column=j).fill = PatternFill("solid", fgColor=AZUL)
        ws.cell(row=LIN_CAB, column=j).alignment = Alignment(horizontal="center", vertical="bottom")

    for k, f in enumerate(fontes):
        col = 3 + k
        c = ws.cell(row=LIN_CAB, column=col, value=f["id"])
        c.font = Font(name=FONTE, size=8, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(text_rotation=90, horizontal="center", vertical="bottom")
        ws.column_dimensions[get_column_letter(col)].width = 4.6

    col_rev = 3 + len(fontes)
    c = ws.cell(row=LIN_CAB, column=col_rev, value="Revisado")
    c.font = Font(name=FONTE, size=8, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="548235")
    c.alignment = Alignment(text_rotation=90, horizontal="center", vertical="bottom")
    ws.column_dimensions[get_column_letter(col_rev)].width = 6
    ws.row_dimensions[LIN_CAB].height = 138

    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 62

    # Linha de exemplo — formato, sem revelar nada sobre as consultas reais.
    r = LIN_CAB + 1
    ws.cell(row=r, column=1, value="EXEMPLO").font = Font(name=FONTE, size=9, bold=True, italic=True)
    ex = ws.cell(row=r, column=2,
                 value="EXEMPLO (não preencher): Quais unidades existem na organização?")
    ex.font = Font(name=FONTE, size=9, italic=True)
    ex.alignment = Alignment(wrap_text=True, vertical="center")
    idx_unid = next((i for i, f in enumerate(fontes) if f["id"] == "sql.unidades"), 0)
    ws.cell(row=r, column=3 + idx_unid, value="P").font = Font(name=FONTE, size=10, bold=True, italic=True)
    ws.cell(row=r, column=col_rev, value="Sim").font = Font(name=FONTE, size=9, italic=True)
    for j in range(1, col_rev + 1):
        ws.cell(row=r, column=j).fill = PatternFill("solid", fgColor=CINZA)
        ws.cell(row=r, column=j).border = BORDA
        if j >= 3:
            ws.cell(row=r, column=j).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[r].height = 30

    prim_dados = r + 1
    for i, q in enumerate(consultas):
        r = prim_dados + i
        ws.cell(row=r, column=1, value=q["id"]).font = Font(name=FONTE, size=9, bold=True)
        cq = ws.cell(row=r, column=2, value=q["query"])
        cq.font = Font(name=FONTE, size=10)
        cq.alignment = Alignment(wrap_text=True, vertical="center")
        for j in range(1, col_rev + 1):
            cel = ws.cell(row=r, column=j)
            cel.border = BORDA
            if j >= 3:
                cel.alignment = Alignment(horizontal="center", vertical="center")
                cel.font = Font(name=FONTE, size=10, bold=True)
                cel.fill = PatternFill("solid", fgColor=AMARELO if j < col_rev else VERDE)
        ws.row_dimensions[r].height = 34

    ult = prim_dados + len(consultas) - 1

    dv = DataValidation(type="list", formula1='"P,C"', allow_blank=True,
                        showErrorMessage=True,
                        errorTitle="Valor inválido",
                        error="Use apenas P (primária), C (complementar) ou deixe em branco.")
    ws.add_data_validation(dv)
    dv.add(f"C{prim_dados}:{get_column_letter(col_rev - 1)}{ult}")

    dv2 = DataValidation(type="list", formula1='"Sim"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add(f"{get_column_letter(col_rev)}{prim_dados}:{get_column_letter(col_rev)}{ult}")

    # Contador de progresso (fórmula, recalcula sozinho)
    lr = ult + 2
    ws.cell(row=lr, column=2, value="Perguntas revisadas:").font = Font(name=FONTE, size=10, bold=True)
    cel = ws.cell(row=lr, column=3,
                  value=f'=COUNTIF({get_column_letter(col_rev)}{prim_dados}:'
                        f'{get_column_letter(col_rev)}{ult},"Sim")&" de {len(consultas)}"')
    cel.font = Font(name=FONTE, size=10, bold=True, color="548235")

    ws.freeze_panes = ws.cell(row=prim_dados, column=3)
    return ws


def gerar(anotador, consultas, fontes, destino):
    wb = Workbook()
    wb.remove(wb.active)
    aba_instrucoes(wb)
    aba_fontes(wb, fontes)
    aba_anotacao(wb, consultas, fontes)

    if anotador:
        ws = wb["Instruções"]
        ws.cell(row=40, column=2, value=f"Participante: {anotador}").font = Font(
            name=FONTE, size=11, bold=True)

    wb.save(destino)
    return destino


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogo", default="../catalogs/v4/catalog_v4_base.json")
    ap.add_argument("--benchmark", default="../benchmark/benchmark_queries_final_v2.json")
    ap.add_argument("--saida", default="IAA_template.xlsx")
    ap.add_argument("--anotadores", nargs="*", default=None,
                    help="opcional: gera uma planilha por nome (uso original)")
    a = ap.parse_args()
    fontes = carregar_fontes(a.catalogo)
    consultas = amostrar_consultas(a.benchmark)
    print(f"{len(fontes)} fontes · {len(consultas)} consultas amostradas")
    if a.anotadores:
        saida = Path("material_iaa")
        saida.mkdir(exist_ok=True)
        for nome in a.anotadores:
            print("  ✓", gerar(nome, consultas, fontes, saida / f"IAA_{nome}.xlsx"))
    else:
        print("  ✓", gerar(None, consultas, fontes, Path(a.saida)))
