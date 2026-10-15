# Artifact notes

Date: 2026-10-12. This note describes two changes/observations about the artifacts in this repository. It contains no
values from the underlying data.

## 1. Redaction of 2026-10-12

A review of this repository found that, outside the `embedding_hint` fields, some catalog files carried real values of
location and equipment description (single records per endpoint, value lists, and a generation transcript). The
repository history was rewritten into a single commit and those values were replaced by consistent pseudonyms
(`IP_nnn`, `PONTO_nnn`, `LOC_nnn`, `SITE_nnn`, `MOD_nnn`, `SYS_nnn`, `GRP_nnn`, `LNK_nnn`, `UNI_nnn`, `CID_nnn`,
`TL_nnn`, `IDU_nnn`, `PN_nnn`, `DESC_nnn`, `TYP_nnn`, `TWR_nnn`); coordinates were replaced by `null` in examples and
rounded to whole degrees in ranges. The original-to-pseudonym map is not published.

**Fields redacted (names are unchanged), by source and location:**

| Source (API endpoint) | Fields | Where |
|---|---|---|
| `monitoramento_sistema_hf_list` | `ip`, `nome`, `latitude`, `longitude` | `example_response`, `result_object_fields.*.example`, `value_profile.values` |
| `monitoramento_sites_sistema_radio_list` | `endereco`, `localization`, `site`, `modelo`, `release`, `sysid`, `system`, `type`, `latitude`, `latitude_decimal`, `longitude`, `longitude_decimal` | `example_response`, `result_object_fields.*.example` |
| `monitoramento_sites_sistema_radio_list` | `grupo_freq`, `link`, `master_site_l1`, `modelo`, `release`, `sysid`, `tipo_torre`, `type` | `value_profile.values` |
| `monitoramento_starlink_list` | `unidade`, `cidade`, `latitude`, `longitude` | `example_response`, `result_object_fields.*.example`; `value_profile.range` of the coordinates rounded to whole degrees |
| `monitoramento_sistema_satelital_list` | `LOCALIDADE_DA_ENTREGA`, `LOCAL_HOJE`, `NUMERO_DO_TL`, `IDU_NMS` | `example_response`, `result_object_fields.*.example` |
| `manutencao_ap_direto_list` | `CIDADE` | `example_response`, `result_object_fields.*.example` |
| `manutencao_ap_direto_list` | `PN` (values in real part-number format) | `value_profile.values` |
| `distribuicao_list` | `descricao` | `value_profile.values` |

The files affected are the catalogs under `catalogs/` (v1, v2, v3 and its truncation variants, v3-doc, v4: base, gen,
gen_norm, min and the raw extraction), `catalogs/v4/catalog_v4_gen_transcript.json`, and
`results/current/comparativo_resultados/catalog_v3.json` (a copy of a catalog). In the transcript only the `prompt_user`
texts were redacted; a `redacao` field at the top records this. **The saved descriptor (`raw_output`,
`descriptor_final`) was generated over the original values**, so regenerating the v4-gen descriptors from the redacted
catalogs would not reproduce the saved text.

`catalog_generation/build_catalog_v4.py` no longer contains a literal list of values to drop from value profiles; it
reads `catalog_generation/value_redaction.local.json` (not versioned; see `value_redaction.example.json`) and stops with
an explicit message if the file is missing.

**Not changed:** `embedding_hint`, `description`, `business_role`, `when_to_use`, `when_NOT_to_use`, all field and
column names, `columns`, the benchmark, all `results_*.json` and the selector code. `sample_rows` and `value_profile` of
the SQL sources `unidades` and `materiais` were kept as published.

**The selectors do not read the redacted fields** (they use the `embedding_hint`, `description`, `business_role`,
`when_to_use`, `when_NOT_to_use` and column names/descriptions). After the redaction, running the selectors again on
`catalogs/v4/catalog_v4_min.json` and `catalogs/v3/catalog_v3.json` of this repository reproduces the published
selections: 80/80 queries with the same selected set and the same order, and the same F1, for each of BM25, MiniLM, BGE-M3 and Llama 3.2 (`compressed` and `full`, `temperature=0`, Ollama `llama3.2:latest`, id `a80c4f17acd5`), on both catalogs (80 queries, 5 folds, seed 42, top-k 3; Python 3.12.6, sentence-transformers 5.5.1, torch 2.10.0 CPU). F1 on `catalog_v4_min.json`: 0.1946 / 0.4552 / 0.5882 / 0.6452 / 0.6780; on `catalog_v3.json`: 0.5946 / 0.4603 / 0.6778 / 0.7605 / 0.3079.

Institutional acronyms that appear in the public descriptions were kept.

## 2. Spelling of two `fornecimento` column names in the v4 catalogs

In `catalogs/v4/catalog_v4_base.json`, the structure `sources.spreadsheets.files.fornecimento.sheets.Sheet1.columns`
uses the `catalog_v3` spelling, `numero_documento_fornecimento` and `Retifica o DF`, but the profile blocks use other
spellings:

| Where | `numero_do_fornecimento` (instead of `numero_documento_fornecimento`) | `Retifica O DF` (instead of `Retifica o DF`) |
|---|---|---|
| `value_profile` keys | yes | yes |
| `sample_rows` keys | yes | no (already `Retifica o DF`) |

The same keys propagate to `catalog_v4_gen.json`, `catalog_v4_gen_norm.json` and `catalog_v4_min.json`, and to the
`prompt_user` text of the transcript. In `catalog_v4_min.json` the generated `embedding_hint` of the `fornecimento`
source is derived from the `value_profile` keys, so it carries the two spellings; the `embedding_hint` of every
`catalog_v4_gen*.json` source contains neither spelling. Catalogs v1, v2, v3 and v3-doc are not affected.

**The catalogs are kept as they were used** to produce the published results. Sensitivity test: a copy of the base
catalog with only those keys renamed, and the v4-min rendered from it with `build_catalog_v4.py render-min`, were run
with the same selectors and configuration (80 queries, 5 folds, seed 42, top-k 3; LLM `temperature=0`, Ollama
`llama3.2:latest`, id `a80c4f17acd5`). Only the keys of the `fornecimento` source and its `embedding_hint` change.
GPT-4o was not repeated. Difference = standardised minus original (the catalog used); paired bootstrap with 10,000
resamples and Holm correction over the four non-lexical selectors (`analysis/stat_compare.py ablation`):

| Selector | Queries whose selected set changed | F1 original | F1 standardised | ΔF1 [95% CI] | p (Holm) |
|---|---|---|---|---|---|
| BM25 | none | 0.1946 | 0.1946 | 0.0000 [0.0000, 0.0000] | n/a (no change) |
| MiniLM | Q23, Q24, Q37, Q45, Q56 (Q31, Q50, Q73: order only) | 0.4552 | 0.4677 | +0.0125 [0.0000, +0.0312] | 0.80 |
| BGE-M3 | Q04, Q15, Q58 | 0.5882 | 0.5668 | −0.0214 [−0.0504, 0.0000] | 0.39 |
| Llama 3.2, compressed | Q09, Q21, Q29, Q31, Q35, Q41, Q56, Q59, Q79 (Q47: order only) | 0.6452 | 0.6548 | +0.0095 [−0.0112, +0.0312] | 0.80 |
| Llama 3.2, full | Q01, Q21, Q31, Q45 | 0.6780 | 0.6739 | −0.0042 [−0.0158, +0.0050] | 0.80 |

No difference is significant. The lexical containment of `analysis/lexical_overlap.py` does not change for any of the
80 queries. Several changed queries do not select the `fornecimento` source at all, so the effect is indirect
(per-fold threshold calibration of the dense encoders; a different prompt for the LLM). Of the eight queries that have
`fornecimento` as gold source, only Q15 changed its selected set (BGE-M3, lower F1 with the standardised catalog); Q50
changed order only (MiniLM). The published results are correct for the catalogs that were actually used; this note
only quantifies how much the spelling could have mattered.
