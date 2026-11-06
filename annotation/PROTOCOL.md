# Inter-annotator agreement (IAA) protocol

This directory documents the annotation study that checks how reproducible the gold standard of
`benchmark/benchmark_queries_final_v2.json` is. It reports two things: agreement among independent
annotators (is the task well defined?) and agreement of each annotator with the gold standard
(is the gold standard idiosyncratic?).

## Files

| File | Content |
|---|---|
| `labels.csv` | 1,536 labels: `annotator, query_id, source_id, label` (P, C or N; N = blank cell). 4 annotators × 24 queries × 16 sources. |
| `IAA_template.xlsx` | Empty annotation workbook generated from the redacted `catalogs/v4/catalog_v4_base.json` (no participant name). |
| `gerar_material_iaa.py` | Generates the workbook (sample of 24 queries, seed 2026). |
| `calcular_iaa.py` | Fleiss and Cohen kappa, raw agreement and set-F1, unchanged from the version used in the study. Reads workbooks. |
| `labels_to_workbooks.py` | Rebuilds minimal workbooks from `labels.csv` so that `calcular_iaa.py` can run on the published labels. |
| `extract_labels.py` | Produces `labels.csv` from the filled workbooks (which are not published). |
| `recall_primarias.py` | Recall of the gold primary sources per annotator. |
| `results_ABC.json`, `results_ABCD.json` | Output of `calcular_iaa.py` with annotators A, B, C and with A, B, C, D. |

## Design

- 24 queries sampled from the 80-query benchmark, stratified by difficulty (6 per each of the 4 levels),
  `random.Random(2026)`, as implemented in `gerar_material_iaa.py`.
- 16 sources per query: 384 judgments per annotator.
- Labels: P (primary, indispensable), C (complementary), blank (do not use). The distinction matters
  because the benchmark recall uses only the primary sources, and precision uses the union of primary
  and complementary sources.
- Reference given to annotators (sheet "Fontes"): field names, types and categorical values only,
  extracted from `catalog_v4_base.json`. The curated `embedding_hint` descriptors were not shown, so
  that the study measures reproducibility from the data and not the reproduction of the author's prose.

## Annotators

No information that identifies a person is published.

| Id | Profile |
|---|---|
| A | Daily user of the system that originates the sources. |
| B | Military, working knowledge of the system and of logistics processes, no daily use. |
| C | Military, working knowledge of the system and of logistics processes, no daily use. |
| D | External to the organization, no contact with the system or with logistics. |

Inclusion criterion, defined before the annotation: belong to the organization and know the system.
D does not meet it. The paper therefore reports agreement for A, B and C. D's labels are published and
the kappa with D is reported as a sensitivity analysis.

## Instructions received by the annotators

The workbook's first sheet ("Instruções", reproduced in `IAA_template.xlsx`) states, in Portuguese:

1. For each question, mark which sources would be needed to answer it; the question itself is not to be answered.
2. P = primary source (without it the question cannot be answered), C = complementary source, blank = not to be consulted.
3. Work alone; do not combine answers with other participants.
4. Do not ask the study's author for help and do not consult any gold standard.
5. In case of doubt, decide by best judgment; do not leave a question without a primary source.
6. The "Fontes" sheet is the only reference to be used.
7. Mark "Sim" in the last column when a question is finished.

The message that accompanied the workbook (WhatsApp, same text to the four participants, in Portuguese; the text is
retained by the author) said, in summary: the author is evaluating a component that decides in which data source the
data to answer a logistics question would be; there are 24 questions; the participant should indicate which source or
sources would be needed, not answer the question; the attached workbook lists the sources and their fields; the data
were described as masked; three requests: avoid asking about specific cases and decide by best judgment, do not leave
a question blank because every question has at least one primary source, and send observations about the process
afterwards; no individual result will be identified; a deadline of one day. The instruction to work alone was in the
workbook's first sheet but was not repeated in the message.

The author did not answer questions about specific cases and did not show the gold standard to anyone
before all workbooks were returned. The author did not annotate. No annotator was discarded after seeing
results. Observation from the labels: annotator A used only P (no C), and did not fill the "Revisado" column;
B, C and D marked all 24 questions as reviewed.

## Definition of the primary-source recall used in the paper

For each annotator and each of the 24 queries, a gold primary source (`expected_primary`) counts as
recovered if the annotator labeled it P or C. The per-query recall is the fraction of gold primary
sources recovered, and the reported value is the mean over queries (macro). The variant that counts only P is
also reported by `recall_primarias.py`.

## Provenance of the files

- The workbooks returned by the participants carry the participants' names. The author renamed them to
  A to D. The original workbooks are retained by the author and are not published, because their metadata
  contain real names and because the reference sheet they contain includes values later removed by the
  redaction described in `NOTA_ARTEFATOS.md`.
- Workbooks were sent and returned by WhatsApp. The dates are recorded in the conversation, which is retained
  by the author and not published.
- The reference sheet that the annotators saw was generated from the catalog before the 2026-10-12 redaction.
  `IAA_template.xlsx` was generated from the redacted catalog, so the "Fontes" sheet differs from the one the
  annotators saw in the redacted values (checked: 7 of the 16 sources have different text; the 6 API sources
  are explained by the redaction, the cause for `spreadsheets.fornecimento` is not yet confirmed).
  The sample of queries and the sources are the same.
- The gold standard used is `benchmark/benchmark_queries_final_v2.json`, as it was at the time of the annotation.

SHA-256 of the files. The original workbooks, as returned by the participants and downloaded again from the
conversations on 2026-11-02 (so their file-system dates are not the dates of the study), are byte-identical to the
copies renamed to A to D; the renaming did not change the content. The hashes were computed over both sets and match.

| Annotator | SHA-256 (original = anonymized copy) |
|---|---|
| A | `f6f191cdf4705eae558ba5a327aae73d879124de8abeec403b05cc1ef184cd26` |
| B | `7d34acafc85f92d4b0c8fd35f5a7c87617c78edeea6815884a7a2f9209b2cbff` |
| C | `a3baac9ece6a283a94d05cb7ea2b402a774890f88d0e004e621d23489d669ede` |
| D | `184739203d4ffff0935f72f728ed8d57cb1e1c95eb5514e1056290d99a0fd86c` |

The copies named A to D therefore still carry the participants' names inside the workbook (sheet "Instruções",
file properties). They are not published for that reason.

## How to reproduce

```bash
cd annotation
# workbooks rebuilt from the published labels
python labels_to_workbooks.py --labels labels.csv --saida-dir tmp_wb --anotadores A B C D
python calcular_iaa.py --planilhas "tmp_wb/IAA_[ABC].xlsx"  --benchmark ../benchmark/benchmark_queries_final_v2.json --saida results_ABC.json
python calcular_iaa.py --planilhas "tmp_wb/IAA_[ABCD].xlsx" --benchmark ../benchmark/benchmark_queries_final_v2.json --saida results_ABCD.json
python recall_primarias.py --labels labels.csv --benchmark ../benchmark/benchmark_queries_final_v2.json
# empty template
python gerar_material_iaa.py
```

The rebuilt workbooks have no "Revisado" column filled, so `calcular_iaa.py` prints "0 revisadas"; this does
not affect any computed value.

## Results

| | A, B, C | A, B, C, D |
|---|---|---|
| Fleiss κ, 3 classes (P/C/N) | 0,322 | 0,282 |
| Fleiss κ, binary (relevant / not) | 0,385 | 0,327 |

Primary-source recall (macro over 24 queries):

| Annotator | P or C | P only |
|---|---|---|
| A | 0,840 | 0,840 |
| B | 0,924 | 0,632 |
| C | 0,792 | 0,653 |
| D | 0,500 | 0,500 |

With 87 to 92% of the judgments left blank (depending on the annotator), kappa is subject to the prevalence effect, which is
why `calcular_iaa.py` also reports raw agreement and the set-F1 between annotators and against the gold standard.
