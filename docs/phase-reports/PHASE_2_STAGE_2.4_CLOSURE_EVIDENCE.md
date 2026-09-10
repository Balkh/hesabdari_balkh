# Stage 2.4 — Closure Evidence

**Stage:** 2.4 — Balances, Trial Balance & Source Traceability
**Branch:** `phase/2` (never `main`)
**Stage commit:** `ad5359bced0149807f27c3116c44f5aa213b800f` (short `ad5359b`)
**Baseline (Stage 2.3):** `720ac03` · **`main` untouched at:** `846a777438e1375331a7ce2821c9483ef5f77fc7`
**Date of execution:** 2026-09-10 (UTC)

> ## 🔒 STATUS: **APPROVED → FROZEN**
> **Frozen by explicit user verdict on 2026-09-10 18:35 UTC.**
> Frozen commit: `ad5359bced0149807f27c3116c44f5aa213b800f` (short `ad5359b`) on `phase/2`.
> From this point the Stage 2.4 surface is immutable: `balances.py`, `balance_tests.py`,
> `migrations/0006_source_trace_index.py`, the 3-line `Meta.indexes` addition in
> `models.py`, and this evidence pair. Any later change to it requires an explicit
> unfreeze ruling from the user — never a silent edit.
> (Recorded by the agent on the user's instruction; the verdict itself is the user's,
> not self-declared.)

This document closes the three items requested before Stage 2.4 may be frozen:

| # | Item | Verdict |
|---|------|---------|
| 1 | Real PostgreSQL regression executed | **PASS — EXECUTED** (PostgreSQL 17.11, live server) |
| 2 | "Document Sequence" = journal `number` under the current contract | **PASS — VERIFIED** (contract §2.8 + code proof) |
| 3 | Exact final commit hash recorded | **PASS — VERIFIED** (`ad5359bced0149807f27c3116c44f5aa213b800f`) |

Classification legend: `EXECUTED` = command actually run this session · `OBSERVED` = output
read from that run · `VERIFIED` = proven by artefact/inspection · `INFERRED` = reasoning,
not proven · `NOT EXECUTED` / `DEFERRED`.

---

## 1. Environment (`EXECUTED`)

The workspace snapshot excludes `.venv` and system packages, so both were rebuilt
before any claim below was produced. Nothing in the repository was changed to do so.

```
Debian GNU/Linux 13 (trixie)
postgres (PostgreSQL) 17.11 (Debian 17.11-0+deb13u1)     # installed via apt this session
Python 3.13.14  ·  Django 5.2.17  ·  psycopg 3.3.5  ·  pytest 8.4.2  ·  pytest-django 4.14.0
```

---

## 2. PostgreSQL server provisioning (`EXECUTED`)

Prior stages recorded PostgreSQL as `NOT EXECUTED` because no server existed in the
sandbox. This session installed and started a real one.

```
$ sudo apt-get install -y postgresql postgresql-client
$ sudo pg_ctlcluster 17 main start
Ver Cluster Port Status Owner    Data directory
17  main    5432 online postgres /var/lib/postgresql/17/main

$ sudo -u postgres psql -tAc "select version();"
PostgreSQL 17.11 (Debian 17.11-0+deb13u1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
```

Role and database created exactly as documented in `.env.example` (the values
`config.settings.postgres` defaults to):

```
CREATE ROLE erp_afghanistan LOGIN PASSWORD 'replace-me' CREATEDB;
CREATE DATABASE erp_afghanistan OWNER erp_afghanistan ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;

$ PGPASSWORD='replace-me' psql -h 127.0.0.1 -p 5432 -U erp_afghanistan -d erp_afghanistan \
      -tAc "select current_user, current_database(), version();"
erp_afghanistan|erp_afghanistan|PostgreSQL 17.11 (Debian 17.11-0+deb13u1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
```

TCP connectivity through the application role: **PASS**.

---

## 3. Schema and migrations on PostgreSQL (`EXECUTED`)

```
$ DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py check
System check identified no issues (0 silenced).

$ DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py migrate --no-input
  ... Applying accounting.0006_source_trace_index... OK

$ DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py showmigrations accounting
accounting
 [X] 0001_initial
 [X] 0002_account_name_fa
 [X] 0003_journal_currency_contract
 [X] 0004_backfill_journal_totals
 [X] 0005_posting_integrity_fields
 [X] 0006_source_trace_index

$ DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py makemigrations --check --dry-run
No changes detected
```

### 3.1 The Stage 2.4 index exists in the PostgreSQL catalogue (`OBSERVED`)

```
$ psql -c "select indexname, indexdef from pg_indexes where tablename='accounting_journalentry';"
 je_src_type_id_idx | CREATE INDEX je_src_type_id_idx ON public.accounting_journalentry USING btree (source_type, source_id)
 (9 rows)
```

Exactly one new index — the composite `(source_type, source_id)` — as committed in
`0006_source_trace_index.py`. No other index was added by Stage 2.4.

### 3.2 Migration is reversible on PostgreSQL (`EXECUTED`)

```
$ manage.py migrate accounting 0005
  Unapplying accounting.0006_source_trace_index... OK
$ psql -tAc "select count(*) from pg_indexes where indexname='je_src_type_id_idx';"   → 0
$ manage.py migrate accounting 0006
  Applying accounting.0006_source_trace_index... OK
$ psql -tAc "select indexname from pg_indexes where indexname='je_src_type_id_idx';"  → je_src_type_id_idx
```

Forward and reverse both clean on a real PostgreSQL server (previously proven only on SQLite).

---

## 4. Full test suites against PostgreSQL (`EXECUTED`)

```
$ DJANGO_SETTINGS_MODULE=config.settings.postgres manage.py test
Ran 17 tests in 0.512s
OK

$ DJANGO_SETTINGS_MODULE=config.settings.postgres python -m pytest -q --ds=config.settings.postgres
........................................................................ [ 56%]
.......................................................                  [100%]
127 passed in 6.79s

$ python -m pytest -q --ds=config.settings.postgres accounting/balance_tests.py
32 passed in 2.14s
```

### 4.1 Proof that this ran on PostgreSQL, not SQLite (`EXECUTED`)

A temporary probe test (created for this run, **deleted immediately afterwards** —
see §10) asserted the DB vendor from inside a pytest-run test:

```
PROBE vendor=postgresql  engine=django.db.backends.postgresql  name=test_erp_afghanistan
PROBE server_version: PostgreSQL 17.11 (Debian 17.11-0+deb13u1) on x86_64-pc-linux-gnu
PROBE current_database: test_erp_afghanistan
1 passed
```

Independent corroboration from the server log — a real PostgreSQL constraint
rejecting a duplicate base currency (the suite asserts this refusal):

```
2026-09-10 18:19:34 UTC [4841] erp_afghanistan@test_erp_afghanistan ERROR:
  duplicate key value violates unique constraint "one_base_currency"
```

---

## 5. Stage 2.4 behavioural regression on PostgreSQL (`EXECUTED`)

A temporary probe exercised the Stage 2.4 API end-to-end against PostgreSQL:
three posted journals (incl. a contra-account line and a back-dated entry), date-bounded
and full trial balances, contra overrides, a reversal, and source traceability.
Verbatim output:

```
=== [PG] SERVER ===
version: PostgreSQL 17.11 (Debian 17.11-0+deb13u1)

=== [PG] NUMERIC SCALE ===
line.debit repr = Decimal('1000.00') | str = 1000.00

=== [PG] TRIAL BALANCE (all history) ===
  1110 Cash in Hand               Dr 1000.00  Cr 100.00  bal 900.00 (DEBIT)
  1410 Main Warehouse             Dr 500.00  Cr 0  bal 500.00 (DEBIT)
  2110 Trade Payables             Dr 0  Cr 400.00  bal 400.00 (CREDIT)
  3100 Owner Capital              Dr 0  Cr 1000.00  bal 1000.00 (CREDIT)
  4200 Sales Returns              Dr 100.00  Cr 0  bal 100.00 (DEBIT)
  5200 Purchase Returns           Dr 0  Cr 100.00  bal 100.00 (CREDIT)
TOTAL DEBIT = 1600.00 | TOTAL CREDIT = 1600.00 | DIFFERENCE = 0.00 | balanced = True

=== [PG] TRIAL BALANCE (to 2026-01-31) ===
TOTAL DEBIT = 1500.00 | TOTAL CREDIT = 1500.00 | accounts = 5

=== [PG] CONTRA OVERRIDES ===
4200: 100.00 DEBIT is_contra = True
5200: 100.00 CREDIT is_contra = True

=== [PG] REVERSAL ===
original JE-PG1 status = REVERSED | reversal JE-1404-00001 status = POSTED reverses = JE-PG1
1110 balance before = 900.00 after = -100.00
expected after = -100.00

=== [PG] SOURCE TRACE ===
journals_by_source(DEMO, S-1) = ['JE-1404-00001', 'JE-PG1', 'JE-PG2']
trace_source(e1): type = DEMO id = S-1 entry_number = JE-PG1 document = None resolved = False

=== [PG] TRIAL BALANCE AFTER REVERSAL ===
TOTAL DEBIT = 2600.00 | TOTAL CREDIT = 2600.00 | DIFFERENCE = 0.00

=== [PG] STAGE 2.4 REGRESSION: ALL ASSERTIONS PASSED ===
1 passed
```

Honest notes on this run:

* **Three probe assertions failed first, and all three were defects in my throwaway
  probe, not in product code** (`OBSERVED`): (a) I expected 4 accounts in the
  January trial balance, actual 5; (b) I expected the 1110 balance to net to 0 after
  reversing `JE-PG1`, but 1110 also carries a 100 credit from `JE-PG3`, so −100 is
  correct; (c) I used a wrong key for `trace_source()`. Product behaviour was correct
  each time; only my expectations were wrong. No product code was touched.
* `trace_source()` returns `entry_number / source_type / source_id / document /
  resolved` — there is no `journals` key; `journals_by_source()` is the list-returning
  function. Documented here so the shape is on record.
* Reversals inherit `source_type` / `source_id` and the original posting date, so a
  reversal legitimately appears in `journals_by_source()` (3 documents, not 2).

### 5.1 PostgreSQL vs SQLite deltas (`OBSERVED`)

| Behaviour | PostgreSQL | SQLite |
|---|---|---|
| `DecimalField` scale on read-back | preserved — `str(line.debit)` → `1000.00` | scale dropped — `1000` |
| Zero-side totals in trial-balance rows | print as `0` (NULL `SUM` → `Decimal("0")`) | same |
| Debit = Credit invariant | `0.00` difference | `0.00` difference |
| Suite result | 127 passed | 127 passed |

The zero-side `0` (instead of `0.00`) is cosmetic only: it comes from `SUM` returning
`NULL` for the empty side and the code falling back to `Decimal("0")`. Values are
numerically exact and compare equal. **No functional difference between the two
backends was observed for Stage 2.4.**

---

## 6. Re-verification on SQLite in the rebuilt environment (`EXECUTED`)

Because `.venv` was recreated, the frozen baselines were re-run so nothing in this
report rests on a stale environment:

```
$ python -m pytest -q                                        # config.settings.test, sqlite
127 passed in 3.30s
$ DJANGO_SETTINGS_MODULE=config.settings.test manage.py test
Ran 17 tests — OK
$ DJANGO_SETTINGS_MODULE=config.settings.development manage.py check
System check identified no issues (0 silenced).
$ DJANGO_SETTINGS_MODULE=config.settings.development manage.py makemigrations --check --dry-run
No changes detected
```

Frontend (`node_modules` also absent from the snapshot; reinstalled with `npm ci`):

```
$ npm test          # 1..4 · tests 4 · pass 4 · fail 0
$ npm run build     # ✓ 31 modules transformed · ✓ built in 274ms
```

---

## 7. RULING — "Document Sequence" is the journal `number` (`VERIFIED`)

**Ruling: under the current contract and code, "Document Sequence" in §2.8 IS
`JournalEntry.number`.** This closes the item previously flagged as `INFERRED`
(item 3 in §23 of `PHASE_2_STAGE_2.4_EVIDENCE.md`).

Evidence, in order of authority:

1. **Contract `PHASE_0_CONTRACT_V2.1.md` §2.8 CHRONOLOGY** — the historical
   calculation order is stated verbatim as:

   ```text
   Posting Date
   → Document Sequence
   → Journal Entry ID
   ```

2. **The codebase has one — and only one — document sequence**, and the journal
   `number` is its output:

   * `backend/documents/models.py` → `class NumberSequence`: *"Backend-owned
     sequence state for document numbers."*
   * `backend/documents/services.py` → `next_document_number(document_type,
     jalali_year)` returns `f"{document_type}-{jalali_year}-{value:05d}"`, e.g.
     `JE-1404-00001`.
   * `backend/accounting/services.py` assigns that value to `JournalEntry.number`
     (`next_document_number("JE", _jalali_year(...))`), and `JournalEntry.number`
     is `unique=True`.
   * A grep for `sequence` across `backend/accounting/` returns no competing
     concept: only the `CHRONOLOGY_ORDER` comment in `balances.py` and the
     `NumberSequence` import in the frozen `integrity_tests.py`.

3. **The frozen model already orders this way**: `JournalEntry.Meta.ordering =
   ["posting_date", "number"]` — posting date, then document sequence.

4. **Stage 2.4 implements exactly the three contract levels**:
   `CHRONOLOGY_ORDER = ("posting_date", "number", "id")` — posting date → document
   sequence → journal entry id.

5. **Executed proof** (§5): journals came back in `(posting_date, number, id)` order,
   and the reversal — which inherits the original's posting date — sorted ahead of
   `JE-PG1` on the tie-break.

**Conclusion:** `number` is not merely the best available proxy; it is the value the
document-number sequence produces and the unique key the frozen model already sorts
by. No other field in the schema can serve as §2.8's middle level.

### 7.1 One ordering nuance, disclosed (`OBSERVED`)

`number` is a text column, so ties on `posting_date` break **lexicographically**:
`JE-1404-00001` < `JE-PG1` < `JE-PG2`. Inside one Jalali year the sequence is
zero-padded to 5 digits, so generated numbers sort numerically and correctly; the
nuance only shows up when numbers of different formats (e.g. hand-made test numbers
like `JE-PG1`) share a posting date — and `id` remains the final deterministic
tie-break in that case. The contract does not define cross-format ordering, so this
is recorded as an `OBSERVED` property, not a defect.

---

## 8. RULING — mixed-currency refusal (`OBSERVED`, acknowledgement still outstanding)

Stage 2.4 raises `JournalValidationError` when an account's posted lines span more
than one transaction currency, rather than summing them. Rationale: §16.6-5 —
amounts in different currencies are never merged numerically; NULL/unknown counts as
its own bucket. Currency-parameterised balances are a later-ledger extension point.
**This item is still awaiting explicit user acknowledgement** (it was item 1 of §23
in the Stage 2.4 evidence document); it is not covered by the three closure items
above and is not blocked by them.

---

## 9. EXACT FINAL COMMIT HASH (`VERIFIED`)

```
$ git rev-parse HEAD
ad5359bced0149807f27c3116c44f5aa213b800f

$ git log -1 --format='%H%n%an <%ae>%n%ad%n%s'
ad5359bced0149807f27c3116c44f5aa213b800f
arena-agent <arena-agent@local>
Wed Sep 9 19:28:55 2026 +0000
feat(accounting): implement balances trial balance and source traceability
```

**FINAL — Stage 2.4 = `ad5359bced0149807f27c3116c44f5aa213b800f`** (short `ad5359b`),
a single commit on `phase/2`, unchanged by this closure work.

Commit chain on `phase/2` (`VERIFIED`):

```
ad5359b  feat(accounting): implement balances trial balance and source traceability   ← Stage 2.4
720ac03  feat(accounting): implement Phase 2 Stage 2.3 posting integrity              ← Stage 2.3 (frozen)
ff03fce  feat(accounting): complete journal contract and money precision              ← Stage 2.2 (frozen)
9aef4d0  docs(evidence): record Stage 2.1 conditional approval rulings                ← Stage 2.1 (frozen)
53391be  feat(accounting): implement canonical chart of accounts
846a777  docs: mark Phase 1 foundation verified; record CI evidence for INC 22-24     ← main, untouched
```

---

## 10. Working-tree state (`VERIFIED`)

```
$ git status --short
?? docs/phase-0/            # pre-existing, untracked by design (Phase 1 baseline notes)
$ git diff --stat
                            # empty
```

* No tracked file is modified. Content diff against `ad5359b` is empty.
* The four `scripts/verify_*.sh` files showed a **file-mode-only** change
  (`100755` → `100644`) caused by the snapshot restore, with byte-identical content;
  the executable bits were restored. No content was edited.
* The two temporary probe files used in §4.1 and §5 were **deleted** after execution.
* Untracked artefacts: `docs/phase-0/` (by design) and this document.

> **Action needed from the user:** this closure document is currently **untracked**.
> It is deliberately not committed, so that `ad5359b` remains the single Stage 2.4
> commit and the hash in §9 stays final. If you want it in history, say so and it
> becomes a `docs(evidence)` commit whose hash supersedes §9 — and it must not be
> swept into the Stage 2.5 commit by accident.

---

## 11. Scope and caveats (`VERIFIED` / `NOT EXECUTED`)

* PostgreSQL is now `EXECUTED`: server 17.11, migrations, both test runners, full
  suite, Stage 2.4 behavioural probe, index catalogue, forward/reverse migration.
* Tauri: `NOT EXECUTED` — backend-only stage; not applicable.
* The PostgreSQL server and the venv live **outside** the workspace snapshot; they
  will not survive a snapshot restore and must be reinstalled to reproduce. The
  evidence above is from this session's real execution, not from a simulation.
* No product code was modified during this closure work (§10: empty diff).
* Commits `ff03fce`, `720ac03`, `ad5359b` remain **unpushed** — `git push` has no
  credentials in this environment. The user pushes, or provides an auth mechanism.

---

## 12. Closure checklist

| Gate step | State |
|---|---|
| INSPECT / IMPLEMENT / UNIT / GOLDEN | done in `ad5359b` (32 tests, 127 total) |
| FAILURE / ROLLBACK | migration reverse+forward proven on SQLite and PostgreSQL |
| RECONCILIATION | trial balance balanced before and after reversal |
| HISTORICAL INTEGRITY | posted history untouched; reversal preserves originals |
| EVIDENCE | `PHASE_2_STAGE_2.4_EVIDENCE.md` + this document |
| PostgreSQL regression | **PASS — EXECUTED** (§2–§5) |
| Document Sequence = journal number | **PASS — VERIFIED** (§7) |
| Exact final commit hash | **PASS — VERIFIED** (§9) |
| USER REVIEW → APPROVED → FROZEN | **APPROVED → FROZEN** (user verdict, 2026-09-10 18:35 UTC) |

---

## 13. Freeze record (`VERIFIED`)

| Field | Value |
|---|---|
| Verdict | **APPROVED → FROZEN**, given explicitly by the user |
| Timestamp | 2026-09-10 18:35 UTC |
| Frozen commit | `ad5359bced0149807f27c3116c44f5aa213b800f` |
| Branch | `phase/2` (single commit for this stage) |
| `main` | untouched at `846a777438e1375331a7ce2821c9483ef5f77fc7` |
| Tracked tree at freeze | clean — `git diff --stat` empty |
| Predecessors frozen | `9aef4d0` (2.1), `ff03fce` (2.2), `720ac03` (2.3) |
| Push state | local only — `git push` has no credentials in this environment |

Frozen surface (do not modify without an explicit unfreeze ruling):

```
backend/accounting/balances.py                          (new, 219 lines)
backend/accounting/balance_tests.py                     (new, 32 tests)
backend/accounting/migrations/0006_source_trace_index.py (new)
backend/accounting/models.py                            (+3 lines, Meta.indexes only)
docs/phase-reports/PHASE_2_STAGE_2.4_EVIDENCE.md        (new)
```

Still open at freeze time (does not block the freeze, carried forward):

1. This closure document is **untracked** — user to decide whether it becomes a
   `docs(evidence)` commit (its hash would then supersede §9) or stays untracked
   like `docs/phase-0/`. It must not be swept into the Stage 2.5 commit.
2. User acknowledgement of the mixed-currency refusal behaviour (§8) is still
   outstanding.
3. Commits `ff03fce`, `720ac03`, `ad5359b` remain unpushed; the user pushes, or
   provides an auth mechanism.
4. Optional: an annotated git tag (e.g. `stage-2.4-frozen`) as an immutable
   in-repo marker — offered, not created, pending the user's word.

**Next stage requires its own explicit authorization.** Per `PHASE_2_PLAN.md`, the
following stage is 2.5 — FX Realization Pattern (§1.10–1.12) + §1.13 Golden Suite.
Work on it has **not** started.
