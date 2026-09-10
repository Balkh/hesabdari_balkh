# PHASE 0 — DOMAIN & ACCOUNTING CONTRACT

## COMPLETE MASTER DOCUMENT — ALL 16 SECTIONS

**VERSION:** 2.1 — FINAL CONSISTENCY-LOCKED
**DATE:** 2026-09-05
**MARKET:** Afghanistan
**BASE CURRENCY:** AFN
**PRIMARY FOREIGN CURRENCY:** USD
**STATUS:** APPROVED — CONSISTENCY LOCKED — IMPLEMENTATION READY

---

# GLOBAL CONTRACT RULES

These rules apply to all 16 sections.

## G1 — No Unapproved Business Assumptions

Implementation MUST NOT invent business behavior that is not defined by this contract.

When a new business requirement appears, it must be explicitly reviewed and added through a controlled change.

---

## G2 — Double-Entry Accounting Is Authoritative

Every posted accounting event MUST satisfy:

```text
TOTAL DEBIT = TOTAL CREDIT
```

No exception.

---

## G3 — One Financial Truth

Customer, supplier, inventory, cash, exchange-house and accounting balances MUST derive from authoritative posted transactions.

No independent unofficial balance engine may exist.

---

## G4 — Posted Transactions Are Immutable

A POSTED transaction MUST NOT be edited or deleted.

Corrections MUST use controlled mechanisms such as:

* Reversal
* Corrective transaction
* Return
* Adjustment
* Approved correction document

---

## G5 — Atomicity

A business transaction affecting multiple modules MUST either complete all required effects or complete none.

No partial state is permitted.

---

## G6 — Historical Integrity

Historical:

* Currency rates
* Transaction prices
* Quantities
* Costs
* Accounting effects
* Document references

MUST remain reconstructable.

---

## G7 — Currency Separation

Different currencies MUST NEVER be numerically merged as though they were the same currency.

---

## G8 — Base Currency Equivalent Is Supplemental

AFN equivalent is for:

* valuation
* reporting
* comparison

It MUST NOT replace the original transaction currency.

---

## G9 — Transaction Price Supremacy

Actual transaction price is authoritative.

Reference prices are suggestions only.

---

## G10 — Evidence-First Implementation

Every implementation stage MUST follow:

```text
Implement
→ Test
→ Execute Golden Tests
→ Verify Reconciliation
→ Verify Failure/Rollback
→ Show Evidence
→ User Review
→ APPROVED
→ FROZEN
→ Next Stage
```

---

## G11 — No PASS Without Executed Evidence

A component MUST NOT be declared PASS merely because code exists or tests were written.

PASS requires actual execution and evidence.

---

## G12 — Single Source of Truth

Every important domain fact MUST have one authoritative source.

---

# SECTION 1 — ACCOUNTING FOUNDATION

## 1.1 Purpose

Define the accounting foundation of the ERP before implementation.

The accounting engine is the financial source of truth.

---

## 1.2 Accounting Model

```text
Business Event
      ↓
Accounting Event
      ↓
Journal Entry
      ↓
Journal Lines
      ↓
General Ledger
      ↓
Account Balance
```

---

## 1.3 Foundational Account Types

```text
ASSET
LIABILITY
EQUITY
REVENUE
EXPENSE
```

Operational concepts:

```text
RECEIVABLE
PAYABLE
INVENTORY
CASH
BANK
EXCHANGE HOUSE
COGS
SALES RETURN
PURCHASE RETURN
FOREX GAIN
FOREX LOSS
```

---

## 1.4 Normal Balances

| Account Type | Normal Balance |
| ------------ | -------------- |
| Asset        | Debit          |
| Expense      | Debit          |
| COGS         | Debit          |
| Liability    | Credit         |
| Equity       | Credit         |
| Revenue      | Credit         |

---

## 1.5 Debit/Credit Rules

### Assets

Increase → Debit
Decrease → Credit

### Liabilities

Increase → Credit
Decrease → Debit

### Equity

Increase → Credit
Decrease → Debit

### Revenue

Increase → Credit
Decrease → Debit

### Expenses

Increase → Debit
Decrease → Credit

---

# 1.6 CHART OF ACCOUNTS

The ERP uses stable four-digit canonical account codes.

The code represents the account identity and hierarchy.

```text
1000 Assets
1100 Cash & Bank
1110 Cash in Hand
1120 Bank Accounts

1200 Exchange House Accounts
1210 Exchange House A
1220 Exchange House B

1300 Accounts Receivable
1310 Trade Receivables

1400 Inventory
1410 Main Warehouse
1420 Secondary Warehouse

1500 Supplier Advances
1900 Other Assets


2000 Liabilities
2100 Accounts Payable
2110 Trade Payables
2200 Customer Advances / Credits
2400 Tax Payable — V2 Reserved
2900 Other Liabilities


3000 Equity
3100 Owner Capital
3900 Opening Balance Equity
3950 Retained Earnings


4000 Revenue
4100 Sales Revenue
4110 Wholesale Sales
4120 Retail Sales
4200 Sales Returns


5000 Cost of Goods Sold
5100 COGS
5200 Purchase Returns


6000 Expenses
6100 Operating Expenses
6200 Freight & Transport
6300 Salaries


8100 Foreign Exchange Gain
8200 Foreign Exchange Loss
```

### COA Rules

1. Account code is stable.
2. Account identity remains stable after posting.
3. Historical transactions remain linked to their original account.
4. Posting is allowed only to valid posting accounts.
5. Non-posting/group accounts cannot accidentally receive operational postings.
6. 8100 and 8200 are valid top-level accounts.
7. Future expansion must preserve existing identities.

---

# 1.7 CORE ACCOUNTING RELATIONSHIPS

### Purchase

```text
Inventory → Supplier Payable / Cash
```

### Sale

```text
Customer Receivable / Cash
        ↓
Sales Revenue

COGS
        ↓
Inventory
```

### Customer Receipt

```text
Cash / Exchange House
        ↓
Customer Receivable
```

### Supplier Payment

```text
Supplier Payable
        ↓
Cash / Exchange House
```

---

# 1.8 JOURNAL ENTRY CONTRACT

Every Journal Entry contains:

* ID
* Posting Date
* Source Type
* Source Document ID
* Description
* Currency context
* Total Debit
* Total Credit
* Status
* Created By
* Created At

Journal Lines contain:

* Account
* Debit
* Credit
* Description
* Reference

Mandatory:

```text
Debit Total = Credit Total
```

An unbalanced journal cannot be POSTED.

---

# 1.9 POSTING INTEGRITY

Posting MUST be:

* Atomic
* Idempotent
* Traceable
* Auditable
* Immutable

The system MUST prevent duplicate accounting effects from repeated commands.

---

# 1.10 FOREIGN EXCHANGE GAIN/LOSS

### Accounts

```text
8100 Foreign Exchange Gain
8200 Foreign Exchange Loss
```

### Realized FX

Realized when settlement uses an effective rate different from the historical obligation rate.

### Unrealized FX

Period-end revaluation is V2.

V1 does not silently rewrite historical values.

---

# 1.11 RATE DIRECTION

Canonical V1 convention:

```text
1 USD = X AFN
```

Example:

```text
1 USD = 70.0000 AFN
```

Therefore:

```text
USD × Rate = AFN Equivalent
```

and:

```text
AFN ÷ Rate = USD Equivalent
```

The UI MUST display the rate direction.

---

# 1.12 HISTORICAL RATE

Example:

```text
Invoice:
1,000 USD
Rate:
70 AFN

Historical Equivalent:
70,000 AFN
```

A later rate of 72 does not modify the original invoice.

---

# 1.13 ACCOUNTING GOLDEN TESTS

Minimum:

* Balanced journal
* Unbalanced journal rejection
* Customer receivable
* Supplier payable
* Customer receipt
* Supplier payment
* Purchase
* Sale
* COGS
* Exchange-house movement
* FX gain
* FX loss
* Historical rate preservation
* Duplicate posting prevention
* Atomic rollback
* Source-document traceability

---

# SECTION 2 — CUSTOMER & SUPPLIER BALANCE

## 2.1 AUTHORITATIVE CHAIN

```text
Business Transaction
→ Posted Accounting Transaction
→ Party/Subsidiary Ledger
→ Gross Financial Positions
→ Net Position
→ Display / Reporting
```

---

## 2.2 GROSS AND NET

The system preserves separately:

1. Gross Receivable/Payable
2. Credit/Advance
3. Net Position

---

## 2.3 CUSTOMER NET POSITION

```text
Customer Net
=
Receivable
-
Customer Credit
```

Status:

* DEBTOR
* CREDITOR
* ZERO

---

## 2.4 SUPPLIER NET POSITION

```text
Supplier Net
=
Payable
-
Supplier Advance
```

---

## 2.5 CURRENCY SEPARATION

Balance identity:

```text
Party + Currency + Balance Type
```

Example:

```text
Customer A / USD / Receivable
Customer A / USD / Credit
Customer A / AFN / Receivable
```

Currencies are never numerically merged.

---

## 2.6 AFN EQUIVALENT

The system may show:

```text
USD Balance
AFN Equivalent
```

but AFN equivalent cannot replace USD balance.

---

## 2.7 PREVIOUS BALANCE

Previous balance is derived from authoritative historical posted transactions.

It is not a manually typed accounting value on an invoice.

---

## 2.8 CHRONOLOGY

Historical calculation order:

```text
Posting Date
→ Document Sequence
→ Journal Entry ID
```

---

## 2.9 OVERPAYMENT

If payment exceeds outstanding:

1. Warn user
2. Show exact excess
3. Require explicit confirmation
4. User chooses:

   * Reduce payment
   * Convert excess to credit/advance
   * Controlled refund workflow

No confirmed choice = no posting.

---

## 2.10 ADVANCE ALLOCATION

V1:

**Manual allocation only.**

No automatic oldest-first allocation.

---

## 2.11 REFUND

Refund of customer credit or supplier advance requires a controlled workflow.

---

## 2.12 OPENING BALANCE

Opening balance uses controlled opening transactions.

Counter-account:

```text
3900 Opening Balance Equity
```

---

## 2.13 GOLDEN TESTS

* Customer debtor
* Customer full payment
* Customer partial payment
* Customer credit
* Customer overpayment
* Supplier payable
* Supplier advance
* Multi-currency
* Historical balance
* Opening balance
* Negative allocation rejection
* Party ↔ GL reconciliation

---

# SECTION 3 — CURRENCY, EXCHANGE RATE & MULTI-CURRENCY

## 3.1 V1 CURRENCIES

Required:

```text
AFN
USD
```

Other currencies are future expansion.

---

## 3.2 BASE CURRENCY

```text
AFN
```

AFN is the system-wide accounting and reporting base currency.

---

## 3.3 MONETARY VALUE

Every monetary amount MUST contain:

* Amount
* Currency

No ambiguous monetary value is allowed.

---

## 3.4 EXCHANGE RATE

Every rate requires:

* From Currency
* To Currency
* Rate
* Rate Date
* Direction

Canonical:

```text
USD → AFN
1 USD = X AFN
```

---

## 3.5 DEFAULT RATE

Default rate may be prefilled.

It MUST be:

* Visible
* Editable
* Saved exactly as used

---

## 3.6 RATE DATE

Document Date and Rate Date are separate.

Both are preserved.

Historical rate is immutable.

---

## 3.7 CROSS-CURRENCY PAYMENT

Cross-currency allocation is permitted in V1.

Example:

```text
Invoice:
1,000 USD @ 70

Payment:
70,500 AFN
```

The system calculates settlement conversion and FX difference.

---

## 3.8 PAYMENT VS ALLOCATION

### Payment

```text
Payment Amount
Payment Currency
Payment Rate
Payment AFN Equivalent
```

### Allocation

```text
Invoice Amount
Invoice Currency
Allocated Amount
Allocation Currency
Allocation AFN Equivalent
```

### Unallocated/Credit

```text
Unallocated Amount
Unallocated Currency
```

---

## 3.9 FUNDAMENTAL PAYMENT EQUATION

```text
Payment Amount
=
Allocated Portion
+
Unallocated/Credit Portion
```

Normal payment:

```text
Unallocated = 0
```

Confirmed overpayment:

```text
Unallocated > 0
```

---

## 3.10 CROSS-CURRENCY RULES

For each allocation:

* Invoice currency remains unchanged.
* Payment currency remains unchanged.
* Historical invoice rate remains unchanged.
* Settlement rate is recorded.
* FX difference is calculated.
* User sees conversion before posting.

---

## 3.11 PRECISION

| Value         | Precision |
| ------------- | --------: |
| AFN           |         2 |
| USD           |         2 |
| Exchange Rate |         4 |
| Unit Price    |         4 |
| Line Total    |         2 |
| AVCO          |         4 |
| COGS          |         2 |

---

## 3.12 ROUNDING

Method:

```text
Half-Up
```

Examples:

```text
Line Total = Round(Qty × Unit Price, 2)

COGS = Round(Qty × AVCO, 2)

FX Equivalent = Round(Amount × Rate, 2)
```

Allocation totals must reconcile exactly.

Final rounding difference is handled deterministically on the final applicable allocation line.

---

## 3.13 UOM EXAMPLES

```text
Cooking Oil:
1 Carton = 10 L
1 Barrel = 200 L

Sugar:
1 Bori = 50 Kg

Tomato Paste:
1 Joure = 2 Packages

Rice:
1 Bag = 50 Kg

Flour:
1 Bag = 50 Kg
```

Historical documents retain the conversion used at posting time.

---

## 3.14 GOLDEN TESTS

Minimum coverage includes:

* AFN
* USD
* Rate direction
* Default rate
* Editable rate
* Historical rate
* Rate date
* Currency separation
* AFN equivalent
* Cross-currency payment
* FX gain
* FX loss
* Precision
* Rounding
* UOM conversion
* Historical integrity

---

# SECTION 4 — INVENTORY & WAREHOUSE

## 4.1 PRODUCT MASTER

Each product:

* Unique code
* Persian/Dari name
* English name
* Category
* Brand optional
* Primary UOM
* Secondary UOM optional
* Conversion factor
* Barcode optional
* Reference purchase price
* Reference sales price
* Minimum stock
* Maximum stock optional
* Reorder point optional
* Active/inactive
* Description

---

## 4.2 TRANSACTION PRICE SUPREMACY

Actual transaction price is authoritative.

Reference prices are suggestions.

---

## 4.3 SMART PRICING

Sales suggestion:

1. Last sold price to customer
2. Reference sales price

User may freely change price.

---

## 4.4 WAREHOUSE

Each warehouse has independent stock.

---

## 4.5 STOCK SOURCE OF TRUTH

```text
Opening Stock
+ Purchase Receipts
+ Sales Returns
+ Transfer In
+ Positive Adjustments
- Sales Issues
- Purchase Returns
- Transfer Out
- Negative Adjustments
= Current Stock
```

---

## 4.6 INVENTORY VALUATION CURRENCY

Original transaction data preserves:

* Original currency
* Original amount
* AFN equivalent

But V1 inventory valuation and AVCO are authoritative in AFN.

---

## 4.7 AVCO

```text
AVCO
=
Total AFN Inventory Cost
÷
Total Quantity
```

Purchase receipt:

```text
New AVCO
=
(Previous AFN Cost + New AFN Cost)
÷
(Previous Qty + New Qty)
```

Sale:

```text
COGS
=
Quantity × AVCO at posting time
```

---

## 4.8 HISTORICAL COGS

Normal historical COGS is not rewritten.

Negative-stock correction is a separate controlled accounting event.

---

## 4.9 NEGATIVE STOCK

Negative stock is permitted only with:

* Warning
* User acknowledgment
* Reason code

---

## 4.10 TEMPORARY COST

When stock is negative:

1. Use last known purchase cost where available.
2. Otherwise standard cost may be used.
3. Mark cost as estimated.
4. Record negative-stock event.

---

## 4.11 LATER RECEIPT

When actual stock arrives, the system evaluates the negative-stock history.

If temporary COGS differs from actual attributable cost:

```text
COGS Adjustment
```

is posted separately.

Original sale remains unchanged.

---

## 4.12 MULTIPLE NEGATIVE TRANSACTIONS

Each negative transaction retains its own cost basis/reference.

Later receipts must be matched chronologically.

No single global overwrite is allowed.

---

## 4.13 RETURN COST BASIS

Sales returns use the original recorded cost basis of the returned sale.

Today's AVCO cannot arbitrarily determine the historical return cost.

If the original sale had a temporary negative-stock cost later corrected, the return references the controlled historical cost-basis record.

---

## 4.14 STOCK MOVEMENT TYPES

| Type             | Effect |
| ---------------- | ------ |
| Purchase Receipt | IN     |
| Sales Issue      | OUT    |
| Sales Return     | IN     |
| Purchase Return  | OUT    |
| Transfer In      | IN     |
| Transfer Out     | OUT    |
| Adjustment In    | IN     |
| Adjustment Out   | OUT    |

Transfers do not create revenue or expense.

---

## 4.15 KARDEX

Per Product + Warehouse:

* Date
* Document
* Type
* Description
* Qty In
* Qty Out
* Running Balance
* Unit Cost
* Total Value
* Currency
* Reference

---

## 4.16 GOLDEN TESTS

Include:

* Product
* Warehouse
* Purchase
* Sale
* Transfer
* Return
* Adjustment
* AVCO
* COGS
* Kardex
* Negative stock
* Multiple negative transactions
* Cost correction
* Return cost basis
* UOM
* Multi-currency
* Historical inventory
* Reconciliation

---

# SECTION 5 — PURCHASE MANAGEMENT

## 5.1 WORKFLOW

```text
Supplier
→ Date
→ Currency
→ Exchange Rate if required
→ Warehouse
→ Items
→ Discount
→ Freight
→ Review
→ POST
```

---

## 5.2 AUTOMATIC EFFECTS

```text
Purchase Invoice
→ Inventory Receipt
→ Stock Increase
→ AVCO Update
→ Supplier Ledger
→ Payable
→ Accounting
→ Reports
→ Printable Document
```

---

## 5.3 PURCHASE FIELDS

* PI-YYYY-XXXXX
* Supplier
* Jalali Date
* Currency
* Exchange Rate
* Rate Date
* Warehouse
* Description
* Items
* Subtotal
* Discount
* Freight
* Total
* Paid Amount
* Outstanding Amount
* Previous Supplier Position
* New Supplier Position
* Status

---

## 5.4 FREIGHT POLICY

V1 default:

**Freight & Transport is an expense.**

```text
Dr Inventory
Dr Freight & Transport Expense
Cr Supplier Payable
```

Future capitalization is a separate controlled future accounting policy.

---

## 5.5 DISCOUNT POLICY

Purchase discount reduces purchase cost.

```text
Gross Purchase
- Purchase Discount
= Net Inventory Cost
```

No undefined discount-revenue account is required in V1.

---

## 5.6 PURCHASE PAYMENT

Credit purchase:

```text
Dr Inventory / Applicable Expense
Cr Supplier Payable
```

Immediate cash purchase:

```text
Dr Inventory / Applicable Expense
Cr Cash / Exchange House
```

---

## 5.7 GOLDEN TESTS

* Cash purchase
* Credit purchase
* Partial payment
* Discount
* Freight
* AFN
* USD
* Warehouse receipt
* AVCO
* Supplier balance
* Closed period
* Duplicate number
* Inactive supplier
* Inactive product
* Printing
* Reporting
* Atomic rollback

---

# SECTION 6 — SALES MANAGEMENT

## 6.1 WORKFLOW

```text
Customer
→ Previous Balance
→ Date
→ Currency
→ Exchange Rate
→ Warehouse
→ Items
→ Discount
→ Payment
→ Review
→ POST
```

---

## 6.2 AUTOMATIC EFFECTS

```text
Sales Invoice
→ Inventory Issue
→ Stock Decrease
→ COGS
→ Gross Profit
→ Customer Ledger
→ Receivable/Cash
→ Accounting
→ Reports
→ Print
```

---

## 6.3 DYNAMIC PRICING

Suggested:

1. Last sold price to customer
2. Reference sales price

Actual user-entered price is authoritative.

---

## 6.4 SALES ACCOUNTING

Credit sale:

```text
Dr Customer Receivable
Cr Sales Revenue
```

Cash sale:

```text
Dr Cash
Cr Sales Revenue
```

COGS:

```text
Dr COGS
Cr Inventory
```

---

## 6.5 GROSS PROFIT

```text
Gross Profit
=
Actual Net Sales Revenue
-
Actual COGS
```

---

## 6.6 NEGATIVE STOCK

Controlled negative stock follows Section 4.

---

## 6.7 SELECTIVE PRINTING

User can print:

* Full invoice
* Selected items
* One item

---

## 6.8 GOLDEN TESTS

Include:

* Cash sale
* Credit sale
* Partial payment
* Discount
* Previous balance
* COGS
* Gross profit
* Negative stock
* Multi-currency
* Wholesale
* Retail
* Full printing
* Selective printing
* Closed period
* Duplicate number
* Inactive entities
* Drill-down
* Atomic rollback

---

# SECTION 7 — PAYMENT & ALLOCATION

## 7.1 PAYMENT TYPES

* Customer Payment
* Supplier Payment

Sources:

* Cash
* Exchange House
* Bank — future

---

## 7.2 WORKFLOW

```text
Party
→ Outstanding Invoices
→ Select Invoices
→ Payment Amount
→ Payment Currency
→ Exchange Rate
→ Source
→ Allocation
→ Review
→ POST
```

---

## 7.3 PAYMENT HEADER

* PMT-YYYY-XXXXX
* Party
* Party Type
* Date
* Payment Currency
* Payment Amount
* Exchange Rate
* Rate Date
* Payment AFN Equivalent
* Source
* Source Reference
* Description
* Status

---

## 7.4 ALLOCATION

* Invoice
* Invoice Date
* Invoice Currency
* Invoice Outstanding
* Allocated Amount
* Allocation Currency
* Allocation AFN Equivalent
* FX Difference where applicable

---

## 7.5 ALLOCATION RULES

Each allocation:

```text
> 0
```

and:

```text
Allocation ≤ Invoice Outstanding
```

No allocation to a fully paid invoice.

---

## 7.6 PAYMENT RECONCILIATION

```text
Payment Amount
=
Allocated Portion
+
Unallocated/Credit Portion
```

---

## 7.7 CUSTOMER OVERPAYMENT

```text
Dr Cash / Exchange House
Cr Customer Receivable
Cr Customer Credit
```

---

## 7.8 SUPPLIER OVERPAYMENT

```text
Dr Supplier Payable
Dr Supplier Advance
Cr Cash / Exchange House
```

---

## 7.9 CROSS-CURRENCY

Cross-currency settlement:

* preserves invoice currency
* preserves payment currency
* preserves historical rate
* records settlement rate
* calculates FX
* displays conversion before posting

---

## 7.10 GOLDEN TESTS

* Full payment
* Partial payment
* Multiple invoices
* Multiple payments
* Customer overpayment
* Supplier overpayment
* Confirmed overpayment
* Unconfirmed overpayment
* AFN
* USD
* Cross-currency
* FX gain
* FX loss
* Fully paid invoice
* Closed period
* Duplicate number
* Inactive party
* Reconciliation
* Atomic rollback

---

# SECTION 8 — RETURNS

## 8.1 TYPES

* Sales Return
* Purchase Return

---

## 8.2 WORKFLOW

```text
Party
→ Original Invoice
→ Details
→ Items
→ Quantity
→ Reason
→ Warehouse
→ Review
→ POST
```

---

## 8.3 ELIGIBLE QUANTITY

Returned quantity MUST NOT exceed the remaining eligible quantity from the original transaction after previous returns.

---

## 8.4 SALES RETURN

### Outstanding invoice

Receivable decreases.

### Fully paid invoice

Customer credit is created.

### Partially paid invoice

The return is applied against the original financial position using controlled proportional settlement rules.

No duplicate credit is permitted.

---

## 8.5 PURCHASE RETURN

### Outstanding

Supplier payable decreases.

### Fully paid

Supplier advance is created.

---

## 8.6 SALES RETURN ACCOUNTING

```text
Dr Sales Returns
Cr Customer Receivable / Customer Credit
```

Inventory:

```text
Dr Inventory
Cr COGS
```

Cost uses original controlled cost basis.

---

## 8.7 PURCHASE RETURN ACCOUNTING

```text
Dr Supplier Payable / Supplier Advance
Cr Inventory
```

---

## 8.8 GOLDEN TESTS

* Outstanding return
* Paid return
* Partial-payment return
* Purchase return
* Paid purchase return
* Excess return rejection
* Multiple returns
* Cost-basis preservation
* Multi-currency
* Closed period
* Duplicate number
* Printing
* Reporting
* Atomic rollback

---

# SECTION 9 — CASH / BANK / EXCHANGE HOUSE / INTERNAL CURRENCY EXCHANGE

## 9.1 CASH

V1 may begin with one physical cash account.

Architecture supports multiple cash accounts.

---

## 9.2 BANK

Bank capability is future/V2.

Architecture must remain compatible with bank accounts.

---

# 9.3 EXCHANGE HOUSE

Exchange House is a financial account relationship.

It is distinct from a remittance network.

The ERP records the company's financial event with the exchange house.

It does not attempt to become an external remittance network.

---

## 9.4 EXCHANGE HOUSE CURRENCY SEPARATION

Each exchange house has independent balances:

```text
Exchange House A / AFN
Exchange House A / USD
```

Currencies MUST remain separate.

---

# 9.5 CASH TRANSACTIONS

### Customer Receipt

```text
Dr Cash
Cr Customer Receivable
```

### Other Receipt

```text
Dr Cash
Cr Revenue / Other Income
```

### Supplier Payment

```text
Dr Supplier Payable
Cr Cash
```

### Expense

```text
Dr Expense
Cr Cash
```

### Cash Transfer

```text
Dr Destination Cash
Cr Source Cash
```

No revenue or expense is created by a transfer.

---

# 9.6 EXCHANGE HOUSE TRANSACTIONS

Cash → Exchange House:

```text
Dr Exchange House
Cr Cash
```

Exchange House → Supplier:

```text
Dr Supplier Payable
Cr Exchange House
```

---

# 9.7 OWNER DEPOSIT

When owner funds the business:

```text
Dr Cash / Bank / Exchange House
Cr Owner Capital
```

The transaction is classified as owner capital, not revenue.

---

# 9.8 OWNER WITHDRAWAL

When owner withdraws business funds:

```text
Dr Owner Withdrawal / Equity
Cr Cash / Bank / Exchange House
```

The transaction is classified as equity movement, not operating expense.

The exact owner-equity account structure must remain consistent with the Chart of Accounts.

---

# 9.9 INTERNAL CURRENCY EXCHANGE

Internal currency exchange means converting one company-held currency into another.

Example:

```text
70,000 AFN
→
1,000 USD
```

The transaction is NOT a sale, purchase, customer payment or supplier payment.

It is an internal movement of company value between currencies/accounts.

---

## 9.9.1 Internal Exchange Requirements

Each exchange records:

* Source account
* Source currency
* Source amount
* Destination account
* Destination currency
* Destination amount
* Exchange rate
* Rate direction
* Date
* Reference
* Description
* User
* Status

---

## 9.9.2 Internal Exchange Accounting

Example:

```text
Source:
70,000 AFN Cash

Destination:
1,000 USD Cash
```

At a defined rate:

```text
Dr USD Cash
Cr AFN Cash
```

Both sides are represented using the appropriate AFN base equivalent so that the accounting entry remains balanced.

---

## 9.9.3 Internal FX Difference

If the accounting carrying value of the source amount differs from the value assigned to the destination amount under the actual exchange transaction, the difference MUST be explicitly classified as:

```text
FX Gain
or
FX Loss
```

The system MUST NOT create unexplained balancing differences.

Internal currency exchange FX is distinct from settlement FX on customer/supplier payments.

---

## 9.9.4 Same-Account Exchange

A conversion cannot be posted as an exchange from an account to itself unless the domain explicitly supports that operation as a controlled currency conversion.

For V1, source and destination currency must differ.

---

## 9.10 CASH CONTROLS

Transfers:

* Cannot exceed available balance.
* Must preserve currency rules.
* Must be atomic.
* Must be auditable.

---

# 9.11 REMITTANCE — V1 SCOPE

The ERP recognizes that remittance is a separate business concept from Exchange House accounting.

However, V1 does NOT attempt to implement a full external remittance network.

---

## 9.11.1 V1 Remittance Record

If the business requires recording a remittance transaction, V1 may maintain a lightweight operational record containing:

* Reference Number
* Sender
* Receiver
* Country
* City
* Amount
* Currency
* Exchange Rate if applicable
* Exchange House
* Status
* Date
* Description

---

## 9.11.2 Remittance Status

Supported statuses:

```text
REGISTERED
SENT
PAID
CANCELLED
```

---

## 9.11.3 Remittance Accounting Boundary

A remittance record does NOT automatically create accounting merely because it exists.

Accounting occurs only when a corresponding financial event actually affects:

* Cash
* Exchange House
* Payable
* Receivable
* Expense
* Other defined financial account

This prevents operational remittance records from creating false accounting.

---

## 9.11.4 External Remittance Network

Integration with external remittance networks is V2/future.

V1 only records the company's financial and operational information necessary for internal control.

---

# 9.12 GOLDEN TESTS

* Customer receipt
* Supplier payment
* Expense
* Cash transfer
* Insufficient balance
* Exchange House
* Exchange-house AFN/USD separation
* Owner deposit
* Owner withdrawal
* Internal AFN→USD exchange
* Internal USD→AFN exchange
* Internal FX gain/loss
* Remittance registration
* Remittance status
* Remittance cancellation
* Closed period
* Duplicate number
* Atomic rollback
* Reconciliation

---

# SECTION 10 — DOCUMENT & INVOICE

## 10.1 DOCUMENT TYPES

* Sales Invoice
* Purchase Invoice
* Payment Receipt
* Payment Voucher
* Cash Receipt
* Cash Payment
* Cash Transfer
* Sales Return
* Purchase Return
* Warehouse Receipt
* Warehouse Issue
* Delivery Note
* Stock Transfer
* Inventory Adjustment
* Physical Count
* Journal Entry
* Remittance Record
* Reports

---

# 10.2 DOCUMENT NUMBERING

Canonical:

```text
TYPE-YYYY-XXXXX
```

Examples:

```text
SI-1405-00001
PI-1405-00001
PMT-1405-00001
RTN-1405-00001
PRN-1405-00001
CSH-1405-00001
```

Numbers are:

* Unique
* Controlled
* Sequential according to series policy
* Immutable after posting

Number generation must be safe under repeated/parallel requests.

---

# 10.3 JALALI DISPLAY AND INTERNAL DATE STORAGE

The ERP uses Jalali dates for user-facing business operations, documents and reports.

**Internal date/time storage MUST use an unambiguous Gregorian-based representation, with timestamps stored in UTC where time is involved.**

The system converts to Jalali only for presentation and user interaction.

This rule applies consistently to:

* Posting dates
* Created timestamps
* Audit timestamps
* Document dates
* Period dates
* Report filters
* Backup metadata

The system MUST NOT use Jalali text as the authoritative internal chronological storage format.

---

# 10.4 DATE CONVERSION INTEGRITY

Conversion between internal Gregorian dates and Jalali display dates MUST be deterministic and tested, including:

* Month boundaries
* Year boundaries
* Leap years
* Fiscal periods
* Historical reports

---

# 10.5 TEMPLATES

Templates support:

* Company logo
* Company name
* Address
* Phone
* Document title
* Header
* Footer
* Number
* Date
* Party
* Items
* Quantity
* Unit
* Unit price
* Discount
* Currency
* Total
* Notes
* Signatures
* Barcode

RTL and LTR supported.

Half-A4 and Full-A4 supported.

---

# 10.6 PRINT ENGINE

Supports:

* Preview
* Direct print
* PDF
* Paper configuration
* Margins
* Header/footer
* Multiple templates

---

# 10.7 SELECTIVE ITEM PRINTING

User can:

```text
Print All
Print Selected Items
Print One Item
```

A selective print MUST clearly indicate that it is a selected-item view/print when required.

---

# 10.8 SELECTIVE PRINT TOTAL POLICY

A selective print is a presentation of an existing posted invoice.

It MUST NOT create a new accounting transaction.

The original invoice totals remain authoritative.

For a selected-item print:

### Original Invoice Totals

The document MUST preserve access to the original:

* Subtotal
* Discount
* Freight
* Total
* Paid
* Balance

### Selected Items Summary

The print MAY additionally show:

```text
Selected Items Subtotal
Selected Items Discount
Selected Items Net
```

These values are calculated only from the selected lines.

They MUST be clearly labeled as:

```text
SELECTED ITEMS
```

They MUST NOT be presented as the original invoice total.

This prevents the printed selected subset from being mistaken for a separate financial invoice.

---

# 10.9 DOCUMENT STATUS

### DRAFT

Editable.

Watermark:

```text
DRAFT
```

### POSTED

Immutable.

No draft watermark.

### REVERSED

Immutable.

Clearly marked:

```text
REVERSED
```

---

# 10.10 GOLDEN TESTS

* Invoice print
* Selective printing
* Single item
* Selected subtotal
* Original total preservation
* Half-A4
* Full-A4
* PDF
* Numbering
* Templates
* RTL
* LTR
* Posted immutability
* Reversed notation
* Date conversion

---

# SECTION 11 — REPORTING

## 11.1 SALES REPORTS

* Summary
* Detail
* Customer
* Product
* Warehouse
* Currency
* Sales Type
* Gross Profit
* Reconciliation
* Aging

---

## 11.2 PURCHASE REPORTS

* Summary
* Detail
* Supplier
* Product
* Warehouse
* Currency
* Reconciliation
* Aging

---

## 11.3 INVENTORY REPORTS

* Current stock
* Warehouse stock
* Stock movement
* Kardex
* Valuation
* Low stock
* Non-moving
* Purchase
* Sales
* Transfers
* Adjustments
* Physical count
* Reconciliation
* Negative stock

---

## 11.4 PARTY REPORTS

* Customer statement
* Supplier statement
* Receivables
* Payables
* Outstanding
* Aging
* Gross position
* Credit/advance
* Net position

---

## 11.5 CASH / EXCHANGE REPORTS

* Cash ledger
* Cash summary
* Cash by account
* Cash by currency
* Receipts
* Payments
* Transfers
* Exchange House statement
* Exchange movement
* Internal currency exchanges

---

## 11.6 ACCOUNTING REPORTS

* Journal
* General Ledger
* Subsidiary Ledger
* Trial Balance
* AR
* AP
* P&L
* Balance Sheet
* Cash Flow
* Period reports
* Reconciliation
* FX Gain/Loss

---

## 11.7 FILTERS

* Date From/To
* Party
* Customer
* Supplier
* Product
* Warehouse
* Exchange House
* Currency
* Status
* Document
* Transaction Type
* Account
* Sales Type

---

## 11.8 DRILL-DOWN

```text
Sales Report
→ Customer
→ Invoice
→ Items
→ Stock Movement
→ Journal Entry
```

---

## 11.9 RECONCILIATION

Mandatory:

```text
Sales Report = Revenue Ledger
Customer Statement = Customer Ledger
Supplier Statement = Supplier Ledger
Inventory Report = Stock Ledger
Cash Report = Cash Ledger
Exchange Report = Exchange Ledger
Trial Balance = General Ledger
P&L = Revenue + COGS + Expenses
Assets = Liabilities + Equity
```

---

## 11.10 EXPORT

Where applicable:

* Screen
* Print
* PDF
* Excel

Exports represent the same authoritative data shown in the report.

---

# SECTION 12 — FISCAL PERIOD & POSTING DATE

## 12.1 PERIOD

Each period contains:

* ID
* Name
* Start Date
* End Date
* Status
* Created Date
* Closed Date

Supported:

* 3 months
* 6 months
* 9 months
* 12 months
* Custom valid period

---

# 12.2 PERIOD STATUS

### OPEN

Posting allowed.

Draft editing allowed.

Posted transaction editing/deletion is prohibited.

### CLOSED

Posting blocked.

Historical data remains immutable.

### LOCKED

Read-only financial state.

No financial changes.

---

# 12.3 STATUS TRANSITIONS

```text
Open → Closed
Closed → Open
Open → Locked
Locked → Open
```

---

# 12.4 REOPEN / UNLOCK

Closed→Open and Locked→Open require:

* Authorization
* Reason
* User identity
* Timestamp
* Audit record

Reopening does NOT make posted transactions editable.

---

# 12.5 PERIOD CLOSING

Closing:

* Preserves data
* Preserves journals
* Preserves invoices
* Preserves inventory history
* Preserves party history
* Preserves audit trail
* Verifies balanced journals
* Verifies reconciliation

Closing MUST fail if critical financial inconsistencies exist.

---

# 12.6 POSTING DATE

```text
Posting Date ∈ Open Period
```

Otherwise posting is rejected.

Future period may generate a warning according to policy.

---

# 12.7 BACKDATED TRANSACTIONS

Allowed only into an Open period.

They MUST correctly update:

* Customer balances
* Supplier balances
* Inventory
* COGS
* Reports
* Historical balances

---

# 12.8 HISTORICAL QUERIES

The system supports:

```text
Customer balance on Date X
Supplier balance on Date X
Warehouse stock on Date X
Cash balance on Date X
```

---

# 12.9 GOLDEN TESTS

* Period creation
* Open posting
* Closed rejection
* Locked rejection
* Closing
* Reopening
* Unlock authorization
* Backdated transaction
* Historical balance
* Posted immutability

---

# SECTION 13 — SECURITY / AUTHORIZATION / APPROVAL

## 13.1 AUTHENTICATION

Offline authentication required.

V1:

* One user initially

Architecture:

* Multi-user ready

Passwords must be securely stored.

---

## 13.2 ROLES

* Administrator
* Accountant
* Sales
* Purchase
* Inventory
* Cashier
* Reports
* Auditor

---

## 13.3 PERMISSIONS

* Create
* Read
* Update
* Delete
* Post
* Reverse
* Approve

Permissions must be enforced at the domain/backend level, not merely hidden in UI.

---

## 13.4 AUDIT TRAIL

Records:

* User
* Date/time
* Action
* Entity
* Entity ID
* Previous state where applicable
* New state where applicable
* Reference
* Reason

Important actions:

* Create
* Update
* Delete
* Post
* Reverse
* Approve
* Reject
* Login
* Logout
* Period close
* Period reopen
* Period unlock
* Inventory adjustment
* Permission change

Audit trail is immutable.

---

## 13.5 APPROVAL

Sensitive operations:

* Reversal
* Period close
* Period reopen
* Period unlock
* Inventory adjustment
* Bulk changes
* Permission changes

V1 may simplify approval for a single-user deployment while retaining multi-user architecture.

---

## 13.6 GOLDEN TESTS

* Authentication
* Authorization
* Audit
* Approval
* Reversal authorization
* Period unlock authorization
* Posted-data immutability

---

# SECTION 14 — BACKUP & RECOVERY

## 14.1 BACKUP TYPES

* Manual
* Automatic
* Full
* Incremental — future

Storage:

* Local
* External
* USB
* Network

---

## 14.2 BACKUP SCOPE

Include:

* Database
* Company settings
* Application configuration
* Invoice templates
* User settings
* Audit trail

Exclude unnecessary:

* Temp
* Cache
* Disposable logs
* Unnecessary runtime files

---

## 14.3 VALIDATION

After backup:

1. File integrity
2. Database integrity
3. Critical data verification

Invalid backup cannot be reported as valid.

---

## 14.4 RESTORE

Before restore:

1. Warn
2. Explain consequences
3. Require confirmation
4. Create safety backup where possible
5. Validate backup
6. Restore
7. Verify database
8. Verify application startup
9. Verify critical business data

Failure must stop safely.

---

## 14.5 LICENSE SAFETY

License failure MUST NEVER:

* Delete data
* Corrupt data
* Remove transactions
* Destroy backups

---

## 14.6 GOLDEN TESTS

* Manual backup
* Automatic backup
* Validation
* Restore
* Safety backup
* Scope
* Corrupted backup rejection
* Post-restore verification
* License failure data safety

---

# SECTION 15 — CROSS-MODULE INTEGRATION

## 15.1 PURCHASE

```text
Purchase
→ Inventory Receipt
→ Supplier Ledger
→ Accounting
→ Reports
```

---

## 15.2 SALES

```text
Sales
→ Inventory Issue
→ Customer Ledger
→ Accounting
→ Reports
```

---

## 15.3 PAYMENT

```text
Payment
→ Party Ledger
→ Cash / Exchange House
→ Accounting
→ Reports
```

---

## 15.4 RETURN

```text
Return
→ Inventory
→ Party Ledger
→ Accounting
→ Reports
```

---

## 15.5 CASH

```text
Cash Transaction
→ Cash Ledger
→ Party Ledger if applicable
→ Accounting
→ Reports
```

---

## 15.6 DOCUMENT

```text
Business Document
→ Posted Document
→ Document Storage
→ Print/PDF
→ Archive
```

---

# 15.7 CROSS-MODULE CONSISTENCY

At all times:

```text
Party Ledger
=
Party Control Account

Inventory Ledger
=
Inventory Control Account

Cash Ledger
=
Cash Control Account

Exchange House Ledger
=
Exchange House Control Account

Sales Report
=
Revenue Ledger

COGS Report
=
COGS Ledger

Trial Balance:
Debit = Credit

Balance Sheet:
Assets = Liabilities + Equity
```

---

# 15.8 RECONCILIATION ENGINE

The system detects discrepancies between:

* Party ledger ↔ control account
* Inventory ledger ↔ inventory account
* Cash ledger ↔ cash account
* Exchange ledger ↔ exchange account
* Sales ↔ revenue
* Purchase ↔ payable
* COGS ↔ inventory movement

Reconciliation suggestions MUST NOT silently alter financial truth.

Any correction requires a controlled corrective transaction.

---

# 15.9 FAILURE PROPAGATION

If a required component fails:

```text
ROLLBACK ALL RELATED EFFECTS
```

Example Sales failure:

* No inventory deduction
* No customer balance change
* No COGS
* No revenue
* No successful posted document

Example Purchase failure:

* No inventory receipt
* No supplier balance change
* No payable
* No partial accounting

---

# 15.10 IDEMPOTENCY

Repeated submission of the same business operation MUST NOT create duplicate:

* Invoice
* Inventory movement
* Journal entry
* Payment
* Party balance effect

---

# 15.11 CROSS-CURRENCY INTEGRATION

Cross-currency operations MUST preserve:

* Original currency
* Settlement currency
* Historical rate
* Settlement rate
* AFN equivalent
* FX difference

---

# 15.12 GOLDEN INTEGRATION TESTS

* Purchase complete flow
* Sales complete flow
* Payment complete flow
* Return complete flow
* Cash flow
* Exchange-house flow
* Internal currency exchange
* Remittance operational flow
* Reconciliation
* Failure rollback
* Duplicate submission
* Historical integrity
* Cross-currency settlement

---

# SECTION 16 — FINAL PHASE 0 MASTER CONTRACT

## 16.1 PHASE 0 COMPLETION

Phase 0 is complete only when Sections 1–15 have:

* Defined business rules
* Resolved decisions
* Defined edge cases
* Defined Golden Tests
* Defined error handling
* Passed cross-section consistency review
* Received explicit approval
* Been frozen

---

# 16.2 FINAL CONSISTENCY LOCK

The following decisions are permanently locked for V1 unless a formal change is approved.

### 1. Chart of Accounts

Stable four-digit account identity.

### 2. Exchange Rate Direction

```text
1 USD = X AFN
```

### 3. Payment vs Allocation

```text
Payment
=
Allocated
+
Unallocated/Credit
```

### 4. Overpayment

Requires explicit confirmation.

### 5. Cross-Currency

Permitted with explicit settlement rate and FX.

### 6. Freight

V1:

```text
Freight → Freight & Transport Expense
```

### 7. Purchase Discount

Reduces inventory purchase cost.

### 8. Inventory Valuation

AVCO is calculated in AFN.

### 9. Negative Stock

Controlled temporary cost + later separate correction.

### 10. Return Cost

Uses original recorded cost basis.

### 11. Posted Transactions

Immutable.

### 12. Fiscal Reopen

Authorized + reason + audit.

Does not unlock posted transactions.

### 13. Exchange House

Currency-separated.

### 14. Reconciliation

Detects discrepancies; does not silently modify truth.

### 15. Idempotency

Repeated commands cannot create duplicate financial effects.

### 16. Remittance

Lightweight operational record in V1; external remittance-network integration is V2.

### 17. Internal Currency Exchange

Explicitly supported in V1 as an internal conversion between company-held currencies/accounts.

### 18. Internal Date Storage

Gregorian-based internal representation; UTC for timestamps; Jalali for user-facing presentation.

### 19. Owner Deposit / Withdrawal

Explicit equity transactions, not revenue/expense.

### 20. Selective Printing

Selected-line summaries are presentation-only and cannot replace original invoice totals.

---

# 16.3 V1 / V2 BOUNDARY

## V1

Required:

* AFN
* USD
* Double-entry accounting
* Chart of Accounts
* Customers
* Suppliers
* Receivables
* Payables
* Customer credits
* Supplier advances
* Inventory
* Warehouses
* AVCO
* Controlled negative stock
* Purchase
* Sales
* Payments
* Returns
* Cash
* Exchange House
* Internal currency exchange
* Lightweight remittance record
* Jalali presentation
* Gregorian/UTC internal dates
* Documents
* Printing
* Selective item printing
* Reporting
* Fiscal periods
* Security
* Audit
* Backup
* Reconciliation
* Owner deposit/withdrawal
* Idempotency

---

## V2 / FUTURE

Reserved:

* Additional currencies beyond V1
* Bank operational module
* Unrealized FX revaluation
* FIFO
* LIFO
* Specific Identification
* Automatic advance allocation
* Incremental backup
* Advanced approval workflows
* Tax system
* External remittance-network integration
* Advanced remittance automation
* Advanced commercial capabilities

---

# 16.4 IMPLEMENTATION ORDER

Implementation follows dependency order.

## Phase 1 — Core Technical Foundation

* Project structure
* Database foundation
* Configuration
* Base models
* Transaction infrastructure
* Jalali date foundation
* Internal Gregorian/UTC date handling
* Currency foundation
* Audit foundation
* Error handling
* Idempotency foundation

---

## Phase 2 — Accounting Core

* Chart of Accounts
* Journal Entry
* Journal Lines
* Posting engine
* Double-entry validation
* Account balances
* Source-document traceability

---

## Phase 3 — Fiscal Period

* Period model
* Open/Closed/Locked
* Posting-date validation
* Reopen/unlock
* Historical queries

---

## Phase 4 — Master Data

* Products
* Categories
* UOM
* Customers
* Suppliers
* Warehouses
* Cash accounts
* Exchange houses

---

## Phase 5 — Party Ledgers

* Receivable
* Payable
* Customer credit
* Supplier advance
* Gross/net position
* Opening balances
* Reconciliation

---

## Phase 6 — Inventory Engine

* Stock movement
* Warehouse balances
* AVCO
* Kardex
* Negative stock
* Cost-basis history

---

## Phase 7 — Purchase

* Purchase invoice
* Inventory receipt
* Supplier payable
* Freight
* Discount
* Accounting integration

---

## Phase 8 — Sales

* Sales invoice
* Inventory issue
* COGS
* Revenue
* Customer receivable
* Gross profit

---

## Phase 9 — Payments

* Customer payments
* Supplier payments
* Allocation
* Overpayment
* Cross-currency
* FX gain/loss

---

## Phase 10 — Returns

* Sales return
* Purchase return
* Inventory reversal
* Cost basis
* Party balance effects

---

## Phase 11 — Cash & Exchange House

* Cash
* Transfers
* Exchange-house balances
* Currency-separated ledgers
* Owner deposit
* Owner withdrawal
* Internal currency exchange

---

## Phase 12 — Remittance

* Lightweight remittance record
* Reference
* Sender
* Receiver
* Country
* City
* Status
* Financial-event linkage where applicable

No external remittance-network integration in V1.

---

## Phase 13 — Documents & Printing

* Numbering
* Templates
* RTL/LTR
* Half-A4
* Full-A4
* PDF
* Selective item printing
* Selected-item summaries

---

## Phase 14 — Reporting & Reconciliation

* Operational reports
* Accounting reports
* Drill-down
* Reconciliation
* Export

---

## Phase 15 — Security & Audit

* Authentication
* Authorization
* Roles
* Audit
* Approval controls

---

## Phase 16 — Backup & Recovery

* Manual backup
* Automatic backup
* Validation
* Restore
* Safety backup

---

## Phase 17 — Full Integration Validation

```text
Purchase
→ Inventory
→ Supplier
→ Accounting

Sales
→ Inventory
→ Customer
→ COGS
→ Revenue
→ Accounting

Payment
→ Party
→ Cash/Exchange
→ Accounting

Return
→ Inventory
→ Party
→ Accounting

Internal Exchange
→ Source Currency
→ Destination Currency
→ Accounting
→ FX

Remittance
→ Operational Record
→ Financial Event where applicable
```

Then:

```text
Reconciliation
→ Regression
→ Golden Tests
→ Failure Tests
→ Historical Integrity
→ Performance Verification
```

---

## Phase 18 — Commercial Readiness

Only after all previous phases PASS:

* Licensing
* Commercial packaging
* Deployment
* Recovery validation
* Production readiness

---

# 16.5 IMPLEMENTATION GATE

No phase is complete because code was written.

Required:

```text
Implementation
↓
Unit Tests
↓
Integration Tests
↓
Golden Tests
↓
Failure / Rollback Tests
↓
Reconciliation
↓
Historical Integrity Verification
↓
Performance Verification where applicable
↓
Evidence Report
↓
USER REVIEW
↓
APPROVED
↓
FROZEN
↓
NEXT PHASE
```

---

# 16.6 ABSOLUTE FORBIDDEN BEHAVIORS

The ERP MUST NEVER:

1. Post unbalanced accounting.
2. Silently edit posted history.
3. Delete historical accounting.
4. Create duplicate accounting.
5. Merge different currencies numerically.
6. Rewrite historical exchange rates.
7. Rewrite historical transaction prices.
8. Create partial cross-module transactions.
9. Treat reference prices as authoritative.
10. Automatically allocate advances in V1.
11. Post unconfirmed overpayments.
12. Allow negative allocations.
13. Allow returns above eligible original quantities.
14. Silently rewrite historical COGS.
15. Hide negative stock.
16. Treat Exchange House as an uncontrolled remittance network.
17. Unlock a period without authorization and audit.
18. Make posted transactions editable merely because a period is reopened.
19. Report an invalid backup as valid.
20. Allow license failure to destroy business data.
21. Report success when downstream effects are incomplete.
22. Allow reconciliation to silently rewrite financial truth.
23. Store Jalali display text as the authoritative chronological date.
24. Treat owner investment as revenue.
25. Treat owner withdrawal as ordinary operating expense.
26. Treat an operational remittance record as automatic accounting.
27. Treat a selective print as a new financial document.
28. Create unexplained FX balancing differences.

---

# 16.7 FINAL ARCHITECTURAL PRINCIPLE

The ERP follows:

```text
BUSINESS TRUTH
      ↓
BUSINESS DOCUMENT
      ↓
CONTROLLED POSTING
      ↓
ACCOUNTING + OPERATIONAL EFFECTS
      ↓
SUBLEDGERS
      ↓
GENERAL LEDGER
      ↓
REPORTING
      ↓
RECONCILIATION
```

No module may become an independent financial truth.

---

# 16.8 FINAL STATUS

**PHASE 0 — DOMAIN & ACCOUNTING CONTRACT**

### STATUS

**✅ COMPLETE**

**✅ CROSS-SECTION CONSISTENCY LOCKED**

**✅ V1 DECISIONS LOCKED**

**✅ EDGE CASES DEFINED**

**✅ ACCOUNTING INTEGRITY LOCKED**

**✅ MULTI-CURRENCY RULES LOCKED**

**✅ INVENTORY COSTING LOCKED**

**✅ NEGATIVE STOCK RULES LOCKED**

**✅ PAYMENT / ALLOCATION MODEL LOCKED**

**✅ OVERPAYMENT RULES LOCKED**

**✅ RETURN COST BASIS LOCKED**

**✅ FISCAL PERIOD RULES LOCKED**

**✅ JALALI / INTERNAL DATE RULES LOCKED**

**✅ OWNER EQUITY TRANSACTIONS LOCKED**

**✅ INTERNAL CURRENCY EXCHANGE LOCKED**

**✅ REMITTANCE V1 BOUNDARY LOCKED**

**✅ SELECTIVE PRINTING RULES LOCKED**

**✅ SECURITY / AUDIT RULES LOCKED**

**✅ BACKUP / RECOVERY RULES LOCKED**

**✅ CROSS-MODULE INTEGRATION LOCKED**

**✅ IDEMPOTENCY RULES LOCKED**

**✅ IMPLEMENTATION ORDER LOCKED**

**✅ EVIDENCE-FIRST COMPLETION GATE LOCKED**

---

# FINAL DECLARATION

This document is the authoritative Phase 0 Domain & Accounting Contract.

Implementation MUST follow this contract.

Any requirement not explicitly defined here MUST NOT be invented during implementation.

Any future change to a frozen rule requires an explicit reviewed change request and regression impact assessment.

**PHASE 0 — VERSION 2.1 — FINAL CONSISTENCY-LOCKED**

**END OF MASTER CONTRACT**
