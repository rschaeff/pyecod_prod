# Deficiency Report: pyecod_prod / pyecod_mini

**Date**: 2026-06-14
**Scope**: `~/dev/pyecod_mini` (v2.2.0 algorithm) + `~/dev/pyecod_prod` (production pipeline) + their integration
**Method**: Static + behavioral audit of `src/`, `tests/`, `docs/`, `sql/`; test suites run; API-spec diff.

## Executive summary

The science happy-path is sound: when `from pyecod_mini import partition_protein` succeeds and the cached
`Partitioner` route runs, the interface is largely correct and the recent reference-caching work resolves the
headline performance defect. **But almost every safety net and failure path is broken, and—critically—none of
them raise.** Parse errors, version skew, SLURM task failures, mini failures, and malformed inputs all degrade
into *plausible-but-wrong* output (`0 domains`, `coverage=0.0`, `unknown_unknown`, `fragmentary`, mislabeled
domains) that flows downstream into curation/accession unflagged. In a domain-classification pipeline this is
worse than a crash. Combined with non-idempotent resume counters and unreliable job-failure detection, the
system is a **functional prototype, not production-ready** for unattended weekly operation.

### Test baseline
- **pyecod_mini**: 269 collected; runnable subset **216 passed / 0 failed**; ~53 integration tests gated on
  `/data/ecod/...` batch data. No test asserts domains are non-overlapping or that the batch path renumbers IDs.
- **pyecod_prod**: `pytest -q` → **2 failed / 121 passed**. One real failure (version-propagation test), one
  test-hygiene failure (a live-DB integration test runs by default and errors with no DB).

### Cross-cutting theme (the root issue)
**Silent degradation.** 55 broad `except Exception` sites (32 mini + 23 prod) plus sentinel-return patterns
convert failures into valid-shaped results. Diagnostics are `verbose`-gated or `print`-only, so at 3,677-chain
batch scale a systematic input/version problem produces clean-looking output with nothing surfaced.

---

## CRITICAL

### C1. CLI fallback parses a schema mini never emits → silent coverage=0 / mislabeling
`pyecod_prod/core/partition_runner.py:530-579` (`_parse_partition_xml`). It reads `root.get("algorithm_version")`,
`<protein>/<coverage>`, `<domain size=...>`. Mini's writer (`pyecod_mini/core/writer.py:129-197`) emits root
`<domain_partition>`, version under `<metadata><version>`, coverage under `<metadata><statistics total_coverage>`,
and `<domain>` with **no `size` attr and no `<coverage>`**. ⇒ every CLI-fallback result parses to `coverage=0.0`,
`algorithm_version=None`, `size=0`, and well-covered chains get labeled `fragmentary`. Prod already has a *correct*
parser (`parsers/partition_parser.py:106-188`) it doesn't use here. **Fix**: route the fallback through
`partition_parser.py` or delete the fallback.

### C2. CLI fallback cannot pass reference CSVs → silent v291-vs-v294.2 reference skew
`partition_runner.py:347-404` (`_partition_via_cli`); mini CLI `cli/main.py:53-118`. Prod is configured for
**v294.2** reference data (passed to the library path), but mini's CLI exposes no `--domain-definitions/...`
flags and hardwires the range cache to `/data/ecod/database_versions/v291/...` (`cli/main.py:117`). If the library
import ever fails, mini silently partitions against **bundled v291** while BLAST/HHsearch/summaries are v294.2 —
mislabeled domains, no error. **Fix**: add reference flags to mini's CLI, or make the library a hard dependency
and remove the CLI fallback (unsafe as written).

### C3. Stale hardcoded DB password breaks the manifest→DB sync path
`pyecod_prod/database/sync.py:47` → `"password": "ecod#badmin"`. Auto-memory `dione-ecod-credentials` records
this password as **stale**; every other DB module reads `ECOD_DB_PASSWORD`/`~/.pgpass` (`curation_loader.py:31`,
`cluster_propagation.py:46`). ⇒ `DatabaseSync` fails to authenticate out of the box, and a secret is in source.
**Fix**: read from env/`~/.pgpass`; raise if unset.

### C4. All three advertised CLIs are dead entry points
`pyproject.toml:33-36` declares `pyecod-weekly/-repair/-status = pyecod_prod.cli.*:main`, but **no
`src/pyecod_prod/cli/` package exists** → `ModuleNotFoundError`. The documented operator interface doesn't exist;
only `python -m pyecod_prod.batch.weekly_batch` works. **Fix**: create the `cli` package or repoint entry points.

### C5. Non-idempotent manifest counters corrupt on resume
`pyecod_prod/batch/manifest.py:175-273`; driven by `weekly_batch.py:310-358,554-613`. `mark_*_complete`
unconditionally does `processing_status[...] += 1` (and `+= hhsearch_needed`) with no "already complete" guard,
and the official resume path (`scripts/resume_batch.py:40`) re-runs the processors over all chains. ⇒ resume
inflates `blast_complete`/`partition_complete`/`hhsearch_needed` past `total_structures`; `get_summary()` reports
>100% and batch-status logic misclassifies. The progress source-of-truth corrupts on the exact operation it
exists to support. **Fix**: make marks idempotent (increment only on state transition) or recompute counters
from per-chain status on save.

---

## HIGH

### H1. SLURM array failure detection is unreliable → concrete silent-data-loss path
`blast_runner.py:288-386` / `hhsearch_runner.py:230-283`. While the array is in `squeue`, completed tasks have
already left the queue, so `failed` is derived only from still-queued tasks (live path never observes FAILED);
the `sacct` fallback counts substrings incl. per-task `.batch/.extern` rows (`COMPLETED`/`FAILED` inflated/unreliable).
No "expected N outputs vs produced N" reconciliation. ⇒ a partially-failed array can report `failed==0`; the
workflow proceeds and `process_*_results` just logs `WARNING: missing` and `continue`s — the chain is dropped
silently. (Corroborated: `BACKFILL_STATUS_REPORT.md` notes 259 timeout failures, no auto-retry.) **Fix**: parse
`sacct --parsable2 --format=JobID,State`, filter to array-task rows, reconcile against produced files, retry.

### H2. Whole-batch abort on any task failure discards all successes
`weekly_batch.py:636-655`. If `run_blast`/`run_hhsearch` returns `success=False` (per H1, "≥1 of up to 1000 tasks
failed"), the workflow prints ERROR and `return`s, throwing away the hundreds of succeeded chains. **Fix**: process
completed chains, collect failures into a retry set, hard-stop only on infra errors (sbatch failure).

### H3. No real resume; resume is an interactive one-off hardcoded to one batch
`weekly_batch.py:701-704` (`--resume` only prints a summary, `# Could add resume logic here`);
`scripts/resume_batch.py` hardcodes `release_date="2025-09-05"`, `develop291`, uses `input()`, and re-invokes the
non-idempotent processors (C5). No generic "re-run only failed/missing chains." **Fix**: status-driven idempotent
resume that resubmits only outstanding chains.

### H4. Broad `except` → failures masquerade as empty/zero/unknown results (the core theme)
- `summary_generator.py:205,360` — any BLAST/HHsearch parse error → `[]`; chain partitions to "no_domains",
  indistinguishable from a genuinely undomained chain.
- `blast_runner.py:432` / `hhsearch_runner.py:374` — parse failure → `coverage=0.0`; `0.0 < 0.90` silently routes
  to HHsearch (wasted compute) and conflates "parse failed" with "no coverage."
- `partition_runner.py:526` — metadata parse failure → `("unknown","unknown",0)` → output written as
  `unknown_unknown.partition.xml`, detached from its chain.
- mini `core/parser.py` (6 broad excepts; whole-file `ParseError → return []` at 122-129) — a corrupt summary is
  indistinguishable from a domainless protein; skip diagnostics are `verbose`-only and never returned to callers.
- mini `api.py:253-271,651-665` — entire algorithm wrapped in `except Exception`; raise-vs-return is gated on
  `output_path.exists()`, so a stale leftover file can suppress a real exception.
**Fix**: narrow to expected exceptions (`ET.ParseError`, `OSError`); record a distinct `parse_error`/`failed`
status instead of a valid-looking sentinel; never emit `unknown_unknown`; return parse diagnostics.

### H5. mini `success=False` is not detected by prod
mini `api.py:253-269` can **return** `PartitionResult(success=False, coverage=0.0)` (not raise) on a post-write
exception. Prod `partition_runner.py:289-313` only treats raised exceptions as failure; for a returned
`success=False` it derives quality from `coverage` (0.0 → `no_domains`/`fragmentary`) and never branches on
`mini_result.success`. ⇒ a failed partition is recorded as a low-coverage *success*. **Fix**: branch on
`mini_result.success`; set `partition_quality="failed"`.

### H6. Overlap "fix" masks the coverage number but leaves domains overlapping
mini `core/boundary_optimizer.py:131-133` only trims overlaps `≤ 5` residues (`resolve_small_overlaps(max_overlap_size=5)`),
while coverage is now computed as a position union (`writer.py:167-176`). Every case in the prior overlap report
(6–21 res; 9mni_R +21) **exceeds the threshold and is never resolved** — output `<domain>` elements still claim
the same residues; only the statistic is masked. No test asserts disjoint domains. **Fix**: implement large-overlap
resolution (prevent extension into occupied positions, or trim by confidence); add a pairwise-disjoint regression test.

### H7. Batch/library partition path emits duplicate, unsorted domain IDs (regression)
mini: the legacy `partitioner.py:186-191` renumbers (`d{i}`) and sorts by start position in PHASE 4; the
production `Partitioner.partition` (`api.py:584-633`) and CLI (`cli/partition.py`) call `optimize_boundaries`
directly and **never renumber/sort**, so per-phase `f"d{len+1}"` naming yields multiple `d1`s written verbatim
(`writer.py:193`). The recommended batch path can emit duplicate `id` attrs and out-of-order domains. **Fix**:
hoist the renumber+sort finalizer into a shared function called by all three entry points.

### H8. Large unassigned gaps (≥ min_domain_size) are silently dropped — the "missed domain" case
mini `core/boundary_optimizer.py:174-181`: segments ≥25 aa are counted in `large_gaps_skipped` and abandoned
("left for external domain parser (not implemented in mini)"). An evidence-less but real domain between two
assigned domains is silently lost — a primary contributor to the ~80% boundary-accuracy ceiling. **Fix**: emit
large gaps as explicit `<unassigned_region>` annotations in output + `PartitionResult` so consumers can route them.

### H9. Two divergent copies of the mini-output parser inside prod
`partition_runner.py:530-579` (wrong, C1) vs `parsers/partition_parser.py:106-188` (correct). They already disagree
and will drift independently on any mini schema change. **Fix**: single source of truth.

### H10. Version inconsistency (2.0.0 vs 2.2.0) defeats prod's dependency pin
mini `pyproject.toml:17` = `2.0.0` but `__init__.py:22` = `__version__ = "2.2.0"` (runtime/CLI report 2.2.0; pip
metadata reports 2.0.0). Prod pins `pyecod-mini>=2.0.0,<3.0.0`, satisfied by 2.0.0 — so the v2.1.0 exclusion API
and v2.2.0 reference-override API that prod **depends on** are not actually guaranteed. Provenance `algorithm_version`
stamped into outputs is ambiguous. **Fix**: bump pyproject to 2.2.0 (or dynamic-version from `__init__`); tighten
prod pin to `>=2.2.0`.

---

## MEDIUM

- **M1. Inter-domain boundaries are a non-structural midpoint split.** mini `boundary_optimizer.py:35-76,409-459`:
  interstitial fragments split at `len//2`; `StructuralContactAnalyzer.load_structure` returns `False` (CA–CA
  logic unimplemented). Direct cause of the multi-domain boundary-accuracy ceiling. Document as a limitation or
  implement the CA–CA path.
- **M2. mini fallback coverage uses the buggy `sum(length)` + fabricated length.** `api.py:213-221`:
  `sequence_length = int(max_pos*1.1)`, `coverage = sum(d.length)/seqlen` (can exceed 1.0). Use position-union;
  treat unknown length as error.
- **M3. Conflicting-evidence curation check unimplemented.** prod `database/curation_loader.py:366-367` TODO:
  multi-strong-discordant-hit proteins can be auto-accepted instead of queued for human curation — a correctness
  risk for downstream accession. Route any multi-strong-hit protein to the queue until implemented.
- **M4. Live-DB integration tests run by default.** prod `tests/test_curation_loader.py:242,258` use an unregistered
  `@pytest.mark.integration`; no `-m "not integration"` default ⇒ `pytest -q` is red without DB creds; CI signal
  unusable. Register the marker + default-deselect.
- **M5. API spec drift / under-documentation.** Two diverging committed copies of `PYECOD_MINI_API_SPEC.md`
  (mini 21126 B Oct-19 vs prod 23651 B Jun-08). Prod's (consumer) copy is newer and documents v2.1.0 exclusions;
  mini's (producer) copy is stale re its own code; **neither documents the v2.2.0 reference-override kwargs** that
  are the linchpin of version correctness. Single-source it in mini, bring to v2.2.0.
- **M6. HHsearch routing conflates parse-failure with low coverage.** prod `manifest.py:199-203` consuming
  `parse_blast_coverage` (0.0 on error). Distinguish `blast_status="failed"` from low coverage.
- **M7. Version-propagation test failure = reproducibility gap.** prod `manifest.py:266-267` stores caller-supplied
  `algorithm_version` only `if algorithm_version:` (None silently dropped); test expects the actually-run mini
  version. Decide source of truth (mini's reported version), require it.
- **M8. mini provenance stamps an inconsistent version** (same root as H10): `writer.get_git_version()` prefers
  `__version__` (2.2.0) ≠ package metadata (2.0.0).
- **M9. `develop291` filename token frozen.** mini `cli/config.py:114`, `writer.py:374` hardwire the
  `.develop291.` infix; prod `references.yaml` sets `summary_suffix: develop291` even inside the **v294.2** block —
  provenance suffix is decoupled from true reference version. Parameterize or document.
- **M10. Hardcoded host/port/tool paths.** prod: `host="dione",port=45000` scattered (`sync.py:43`,
  `curation_loader.py:39`, `domain_overlap.py:350`, `auto_accession.py:231`); tool paths
  `blast_runner.py:164`, `hhsearch_runner.py:131`; per-user `pyecod_mini_path="/home/rschaeff/.local/bin/pyecod-mini"`
  (`weekly_batch.py:135`). mini: 7 hardcoded `/data/ecod/...`, `/usr2/pdb/data`, `/tmp` paths in `cli/config.py`,
  `core/visualization.py`. `cluster_propagation.py:46` already shows the right env pattern — apply consistently.

---

## LOW

- **L1.** SQL migrations (`sql/01..04_*.sql`) are unversioned, non-transactional, no `applied_migrations` table;
  `DATABASE_DEPLOYMENT_STATUS.md` lists several schema features as not implemented. Adopt a migration tool / tracking table.
- **L2.** Orchestrator uses `print` not `logging` (mixed with `partition_runner` which uses `logging`); no output
  validation or input↔output reconciliation. Uniform logging + end-of-run reconciliation.
- **L3.** mini test gaps: no `test_boundary_optimizer.py`; no disjoint-domains invariant; no duplicate-ID test on
  the batch path; no malformed-XML-vs-no-evidence test (H4/H6/H7 went undetected).
- **L4.** mini decomposition size floors inconsistent (20 in `decomposer.py:287` vs 25 `min_domain_size`); small
  domains silently dropped. Unify + surface counts.
- **L5.** Duplicated coverage/classification-mapping logic across mini/prod (legacy `f_group`=T-group remap); add a
  summary→partition→exclusion contract test asserting masking hits the intended level.

---

## Status of prior deficiency docs
- `pyecod_mini/docs/DEFICIENCY_OVERLAP_BUG.md` — **partially fixed**: coverage number corrected, overlapping
  *assignments* persist (H6).
- `pyecod_mini/docs/DEFICIENCY_BATCH_LOADING.md` / `DEFICIENCY_REPORT_REFERENCE_CACHING.md` — **fixed**:
  `PartitionRunner` builds a cached `Partitioner` once and reuses it (`partition_runner.py:104-133,246-258`).
  **Caveat**: caching only engages when reference CSVs are present; `v291` sets them `null` in `references.yaml`,
  so v291 batches silently fall back to the slow per-chain reload — and `--reference` still defaults to `develop291`.

## Recommended fix order
1. **Stop silent corruption first** (C1, C2, H4, H5) — make failures fail loudly; these poison curation/accession.
2. **Restore safe operation** (C3, C4, C5, H1, H2, H3) — credentials, CLIs, idempotent resume, real failure
   detection/retry.
3. **Algorithm correctness** (H6, H7, H8) — disjoint domains, ID renumbering on the batch path, surface missed gaps.
4. **Contract hygiene** (H9, H10, M5, M7) — one parser, one version, one up-to-date API spec.
5. The rest (M/L) as cleanup; make both test suites green and DB-independent so they can gate regressions.
