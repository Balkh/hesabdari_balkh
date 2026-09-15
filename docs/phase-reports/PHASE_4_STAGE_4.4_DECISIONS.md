# PHASE 4.4 — ARCHITECTURE DISCOVERY RECORD (NO IMPLEMENTATION)

**1. Date/time UTC:** 2026-09-15T19:55Z
**2. Branch:** `phase/4`
**3. HEAD:** `083d925c6f68042fa3593d98f07b45081db8b51a` (4.3 closure)
**4. Working tree:** clean (this file is the only untracked path; zero
tracked diff; no commit)
**5. Frozen baseline verification:** 4.1 `60dfaf7`, 4.2 `3362748`,
4.3 code-frozen `c3af9a2` + freeze record `083d925` (docs-only child;
`c3af9a2` verified ancestor of HEAD — the prompt's "c3af9a2 baseline" is
contained, not diverged). origin/main `646e35e`. §23: NO frozen phase
needs modification — no FROZEN-PHASE CONFLICT.
**Method:** every claim cites contract section + line, or repo path.
Contract: `docs/phase-0/PHASE_0_CONTRACT_V2.1.md` (3510 lines, English-only).

---

## 6. CONTRACT EVIDENCE (C = mandatory rule, X = contextual)

| # | Finding | Source | Class |
|---|---|---|---|
| C1 | Cash account = PHYSICAL resource: "V1 may begin with one physical cash account. Architecture supports multiple cash accounts." Term appears only L1659/L1661/L2834/L3145; capitalized "Cash Account" ZERO times | §9.1 L1659–1661; L2834; L3145 | C |
| C2 | "Exchange House is a financial account relationship… distinct from a remittance network… records the company's financial event with the exchange house" | §9.3 L1675–1681 | C |
| C3 | EH currency separation: "Exchange House A / AFN", "Exchange House A / USD"; "Currencies MUST remain separate" (a Phase-11 balance rule, not master fields) | §9.4 L1687–1694 | C (Ph11) |
| C4 | Posting patterns name endpoints: "Cash", "Source/Destination Cash", "Exchange House", "Customer Receivable", "Supplier Payable" | §9.5–9.6 L1700–1755 | C (Ph11) |
| C5 | Funding/payment endpoints "Cash / Bank / Exchange House"; payment sources Cash, EH, Bank-future | §9.7/9.8, §7.1 L1400–1408 | C (Ph11) |
| C6 | Internal exchange records Source account/currency/amount → Dest account/currency/amount + rate/direction…; endpoints "AFN Cash"/"USD Cash"; V1 source/dest currency MUST differ | §9.9 L1790–1860 | C (Ph11) |
| C7 | COA: 1100 control → 1110 Cash in Hand / 1120 Bank Accounts (both posting); 1200 control → 1210/1220 EH A/B (posting). "Exchange House A/B" labels shared by COA leaves (L253–254) and §9.4 balance examples (L1690–1691) — ONE label space | §1.6 L244–254 | C |
| C8 | "Cash Ledger = Cash Control Account"; "EH Ledger = EH Control Account"; reconciliation "Cash ledger ↔ cash account" (account as recon party, distinct from ledger) | L2800–2810; L2834 | C (Ph11) |
| C9 | Phase 5 = Receivable/Payable/credits/advances ONLY — no EH → EH does NOT participate in Party Ledger (it has its OWN ledger, C8). Phase 11 owns cash/EH balances + transfers + internal exchange | L3147–3154; L3216–3226 | X |
| C10 | Bank = future/V2 ("Bank capability is future/V2"); "Architecture must remain compatible with bank accounts" — compatibility, not implementation | §9.2 L1665–1669; §7.1 | C |
| C11 | G3: cash + exchange-house balances derive from posted transactions; no side balance engine. G8/AFN-base: base equivalent supplemental, never replaces original currency | L40; L85–97 | C |
| C12 | ZERO occurrences: Counterparty, cash/EH code, cash/EH address/phone/license, cash/EH type, inactive cash/EH, default cash/EH | full-text negative | — |
| C13 | Remittance = lightweight operational V1 record, separate concept; external network V2. Forbidden: "Treat Exchange House as an uncontrolled remittance network" | §9.11 L1881–1940; §16.6#16 L3402 | C |
| C14 | Decision 13 "Exchange House: Currency-separated"; Decision 17 internal exchange V1 | L2997–3017 | C |

## 7. REPOSITORY EVIDENCE

| # | Finding | Source |
|---|---|---|
| R1 | `cash/`, `exchange/`, `remittance/`, `payments/`, `purchasing/`, `sales/` = `.gitkeep` placeholders; SINGULAR names reserved for future engines → master apps must be plural (`cash_accounts`, `exchange_houses`), mirroring categories/products/parties/warehouses | paths |
| R2 | `Currency`: code unique(3), name, symbol, decimals, `is_base` (partial-unique), `is_active`; directional `ExchangeRate`; `JE.currency` FK PROTECT nullable; `FXSettlement` in accounting | `currencies/models.py`; `accounting/models.py:55,171` |
| R3 | `Account`: code unique + name/name_fa + parent self-FK PROTECT + `is_posting` + `is_active`; COA seeds (Dari presentation names); journals generic `source_type/source_id` + index (future reference path exists) | `accounting/models.py:30-51,73`; `coa.py:30-35` |
| R4 | Party FROZEN: roles (customer/supplier) + contact trio + active; ZERO balance/ledger/finance anywhere in parties/ | `parties/models.py:18-40`; negative grep |
| R5 | Uniform master convention (7 precedents): name req NON-UNIQUE + name_fa opt + is_active T + created_at only + blank-guard check + `record_audit_event` + no-op silence + no delete path + no code where contract silent (4.1 U-2/U-3, 4.2 FR-4, 4.3 OD-1/OD-2) | categories/uom/products/parties/warehouses |

## 8. CASH ACCOUNT ANALYSIS

A physical cash resource with a stable identity (C1), referenced by name
in transfers (C4 "Source/Destination Cash") and internal exchange (C6),
reconciled as "cash account" (C8). Multiple supported (C1). No master
fields specified anywhere (C12). Currency appears on TRANSACTIONS and
BALANCES (C3-pattern, C6, C11) — never as a master attribute.

## 9. EXCHANGE HOUSE ANALYSIS

A named financial-account relationship with an external house (C2), with
currency-separated balances (C3), its OWN ledger + control account (C8),
outside Party Ledger (C9), outside remittance-network concepts (C13). No
master fields specified (C12). Same structural shape as Cash Account.

## 10. PARTY RELATIONSHIP ANALYSIS

EH-as-Party is REFUTED three ways: (a) frozen roles are customer/
supplier only — a new role = frozen change (§23 STOP); (b) Party
deliberately excludes finance (R4/FR-9) while EH is DEFINED financial
(C2); (c) EH has its own ledger, not Party Ledger (C8/C9). EH↔Party FK in
either direction is pure speculation (C12) with unanswerable lifecycle.
Cash↔Party: zero evidence; cash is an internal physical resource (C1).
→ No Party FK anywhere (settled, reviewable).

## 11. COA RELATIONSHIP ANALYSIS

"Cash IS the COA account" (use 1110 directly) is REFUTED: one 1110 leaf
cannot be "multiple cash accounts" (C1), named transfer endpoints (C4),
or a reconciliation party distinct from its ledger (C8). A Cash→COA FK is
speculative: every cash would point at the same 1110 (a constant, adding
nothing), and no per-cash leaf structure exists in the contract (C7 shows
only example leaves). Same for EH (1210/1220 are EXAMPLE leaves under
control 1200). Posting-account resolution belongs to Phase 11, which owns
posting (C4/C9). → Operational masters with NO COA FK (settled,
reviewable); journals' `source_type/source_id` already provide the future
reference path (R3).

## 12. CURRENCY ANALYSIS

Currency is centralized (R2 — no second system). Balances are keyed
(entity, currency): proven for EH (C3), for Kardex (product, warehouse),
and implied for cash by per-currency endpoints + per-transaction currency
(C6) + G3 derivation (C11). A single-currency FK on the master would
duplicate physical identity ("AFN Cash" vs "USD Cash" as separate
masters), contradict C1's "physical", and demote currency from its
transaction attribute role (C6). → Currency is a BALANCE/transaction
dimension, not a master field (OD-5: OPEN for confirmation — structural
class; recommendation A).

## 13. IDENTITY ANALYSIS

OD-1/OD-2 settled-recommend: flat name identity (`name` req + `name_fa`
opt, R5), PK = stable reference for future (account, currency) balances
and documents. "Cash"/"Cash" and "Qari Sardar"/"Qari Sardar" dupes
possible (OD-8/OD-9 govern); per-currency names ("Cash AFN") possible as
plain names but NOT required — separation holds regardless (C3/C11).

## 14. UNIQUENESS ANALYSIS

OD-8/OD-9 OPEN: recommend NON-UNIQUE (7 precedents, R5; ambiguity is a
UI/labeling concern, never a DB constraint from silence — 4.1 U-3
principle). Alternative UNIQUE is a permanent invented rule (C12).

## 15. ACTIVE/INACTIVE ANALYSIS (OD-10: settled-include, reviewable)

`is_active` default True on both (6 master precedents incl. Account and
Currency). Semantics: RECOMMENDED (convention; contract silent) —
inactive = not selectable for NEW future operations; history readable;
no enforcement in 4.4 (nothing to enforce against). NOT "balance zero /
closed / deleted" (C11: balances derive from transactions, never flags).

## 16. DELETION ANALYSIS (OD-11: settled, reviewable)

No delete workflow (7 precedents); future consumers (Phase 11) will
PROTECT historical FKs. Minimum consistent approach; nothing to decide.

## 17. APP/MODEL ARCHITECTURE (OD-12: settled, reviewable)

Separate apps `backend/cash_accounts/` (`CashAccount`) +
`backend/exchange_houses/` (`ExchangeHouse`): R1 reserves singular
`cash/` + `exchange/` for future engines; plural = master convention;
no shared abstract base (zero repo precedent — premature abstraction).
Model names follow the contract's lowercase terms capitalized (C1/C2).

## 18. FUTURE DEPENDENCY MAP

Required NOW: stable PK identities only. Required LATER (not 4.4):
Phase 5 — nothing (EH/cash absent from Party Ledger, C9); Phase 6 —
nothing; Purchases/Sales/Payments — source references at transaction
time; Phase 11 — transfers, EH balances, currency-separated ledgers,
owner deposit/withdrawal, internal exchange, COA resolution, recon
(C4–C9); Reports — statements (later). MUST NOT be implemented now: §4
list (30+ engines), esp. balances/ledgers/posting/reconciliation.

## 19. SCOPE EXCLUSIONS

§4's list verbatim, plus: bank master/module (C10 — compatibility only),
COA leaves per master, per-cash/per-EH leaf creation, currency FKs
(pending OD-5), codes (pending OD-6/7), contact fields (pending OD-13),
Party/COA FKs, type/default flags, API/UI, admin, any new engine.

## 20. ARCHITECTURE OPTIONS (genuine ambiguities)

**O-A Cash identity.** A: name-only flat master; currency = balance
dimension (C3/C6/C11 pattern; R5 shape). B: name+currency rows ("AFN
Cash" master): simpler Phase-11 picker UX, but duplicates physical
identity, contradicts C1, demotes C6 transaction currency. → A.
**O-B Cash↔COA.** A: no FK, Phase-11 resolves (C9 owns posting). B: FK
to Account: constant-pointing speculation (C7). C: cash IS 1110:
REFUTED (C1/C4/C8). → A.
**O-C EH shape.** A: independent flat master (C2/C8/C9). B: Party
subclass/role: REFUTED (§10). C: EH↔Party FK: speculation (C12). → A.
**O-D Codes.** None (4 precedents + NumberSequence document-scoped, R5)
vs manual unique (human convenience — explicitly rejected 3× before).
→ None (OD-6/OD-7 OPEN).
**O-E EH contact.** Omit (C12 + anti-CRM + 4.3 OD-3 precedent) vs inert
trio mirroring Party FR-6 (EH is external-facing, unlike a godown —
the ONE genuine counter-argument). → Omit (OD-13 OPEN).

## 21. DECISION MATRIX (/30)

| Option | Contract | Repo | Future | Scope | Simplicity | Integrity | Total | Rec |
|---|---|---|---|---|---|---|---|---|
| Cash: name-only, no currency FK | 5 (C1/C6/C11 pattern) | 5 (R5) | 5 (balances key PK+ccy) | 5 | 5 | 5 | 30 | ✅* |
| Cash: name+currency rows | 2 (contradicts C1) | 2 (no precedent) | 3 (picker UX) | 3 | 3 | 3 | 16 | ❌ |
| Cash↔COA: no FK | 4 (C9: Ph11 owns posting) | 5 | 5 | 5 | 5 | 5 | 29 | ✅ |
| Cash↔COA: FK | 2 (constant speculation) | 2 | 3 | 2 | 3 | 4 | 16 | ❌ |
| EH: independent master | 5 (C2/C8/C9) | 5 | 5 | 5 | 5 | 5 | 30 | ✅ |
| EH: Party-linked | 1 (refuted §10) | 1 (frozen break) | 2 | 1 | 2 | 2 | 9 | ❌ |
| Codes: none (both) | 4 (silent; 4 precedents) | 5 | 5 | 5 | 5 | 4 | 28 | ✅* |
| Codes: manual unique | 1 (invention) | 2 | 3 | 3 | 3 | 4 | 16 | ❌ |
| Uniqueness: non-unique | 4 (silent; 7 precedents) | 5 | 5 | 5 | 5 | 4 | 28 | ✅* |
| EH contact: omit | 4 (C12; 4.3 OD-3) | 4 | 5 | 5 | 5 | 5 | 28 | ✅* |
| EH contact: inert trio | 2 (speculative) | 3 (Party FR-6) | 4 | 4 | 4 | 5 | 22 | * |

`*` = recommended but OPEN for user ruling (permanent/structural class).

## 22. OPEN DECISIONS

Must-rule (BLOCKING): OD-5 currency placement (rec: NO FK — balance
dimension) · OD-6 cash code (rec: NONE) · OD-7 EH code (rec: NONE) ·
OD-8 cash name uniqueness (rec: NON-UNIQUE) · OD-9 EH name uniqueness
(rec: NON-UNIQUE) · OD-13 EH contact fields phone/address/note/license
(rec: OMIT; alt: inert trio mirroring FR-6).
Settled-reviewable (evidence-closed, user may still override): OD-1/OD-2
flat name identity · OD-3/§11 no COA FK · OD-4/§10 no Party FK, EH out
of Party Ledger · OD-10 `is_active` both, selection-only RECOMMENDED ·
OD-11 no delete workflow · OD-12 separate `cash_accounts` +
`exchange_houses` apps, no shared base.

## 23. RECOMMENDED RULINGS

OD-5 NO currency FK · OD-6/OD-7 NO codes · OD-8/OD-9 NON-UNIQUE ·
OD-13 OMIT contact. Proposed masters (conceptual only — NOT created):
`CashAccount(id, name req, name_fa opt, is_active T, created_at)` and
`ExchangeHouse(same shape)`; single blank-guard check each; audit +
no-op per R5; zero FKs; zero engines.

## 24. IMPLEMENTATION AUTHORIZATION STATUS

```text
IMPLEMENTATION AUTHORIZATION: NOT GRANTED
```

Discovery only. No models/migrations/services/tests/API/frontend created,
no code modified, no commit. FROZEN phases + 4.1/4.2/4.3 untouched.
Verdict: BLOCKED — 6 open user decisions (OD-5..OD-9, OD-13) — WAITING
FOR USER DECISION — NO IMPLEMENTATION.

## 25. USER APPROVAL — 2026-09-15 ("تایید است")

User approved the discovery record: all §22 recommendations are CONFIRMED
as final rulings — OD-5 NO currency FK · OD-6/OD-7 NO codes · OD-8/OD-9
NON-UNIQUE · OD-13 OMIT contact — plus all settled-reviewable positions
(§22). Implementation remains NOT AUTHORIZED: it starts only on a
separate explicit user implementation order. Verdict: RULINGS CONFIRMED —
WAITING FOR IMPLEMENTATION ORDER — NO IMPLEMENTATION.
