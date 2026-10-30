============================================================
ERP MASTER BLUEPRINT & BUILD SPECIFICATION
VERSION 3.0
============================================================

PROJECT:
Professional, Simple, Fast, Bilingual ERP System

PRIMARY TECHNOLOGY:
Backend  : Python + Django + Django REST Framework
Frontend : React + TypeScript
Desktop  : Tauri
Database : SQLite initially / PostgreSQL-ready architecture

LANGUAGES:
- Persian/Dari
- English

DATE SYSTEM:
- Jalali-first user experience
- Centralized date/calendar service

ACCOUNTING:
- Full Double-Entry Accounting System

PRODUCT VISION:
- Real-world ERP
- Professional
- Simple
- Fast
- Reliable
- Maintainable
- Auditable
- Commercial-ready
- Not unnecessarily crowded


============================================================
0. MASTER DEVELOPMENT PRINCIPLE
============================================================

The ERP must be powerful internally but simple externally.

The user should not need to understand the internal
complexity of accounting, inventory, posting, ledgers,
or document synchronization.

The user performs the business operation once.

The system automatically performs all required
downstream operations.

CORE PRINCIPLE:

ONE BUSINESS ACTION
        ->
ONE SOURCE OF TRUTH
        ->
AUTOMATIC INTEGRATION
        ->
ACCOUNTING
        ->
INVENTORY
        ->
PARTY LEDGER
        ->
REPORTING
        ->
DOCUMENTS


NON-NEGOTIABLE RULE:

NO VERIFIED TEST
=
NO NEXT PHASE


============================================================
1. PRODUCT PHILOSOPHY
============================================================

The ERP must NOT become unnecessarily complicated,
crowded, or difficult to learn.

The system must feel simple to the end user while
maintaining professional enterprise-level internal logic.

Priorities:

1. Data integrity
2. Accounting correctness
3. Inventory correctness
4. Transaction safety
5. User experience
6. Performance
7. Maintainability
8. Reporting accuracy
9. Security
10. Commercial readiness


============================================================
2. TECHNOLOGY STACK
============================================================

BACKEND:

- Python
- Django
- Django REST Framework

FRONTEND:

- React
- TypeScript

DESKTOP:

- Tauri

DATABASE:

- SQLite initially where appropriate
- Architecture must remain PostgreSQL-ready

TESTING:

- Pytest
- Django tests
- API tests
- Frontend tests
- Integration tests
- End-to-End tests
- Accounting reconciliation tests
- Inventory reconciliation tests
- Backup/restore tests
- Print/document tests
- Regression tests

ARCHITECTURAL RULE:

Business logic belongs to the backend/domain layer.

React must NOT become the source of truth for:

- Accounting
- Inventory
- Financial posting
- Party balances
- Permissions
- Critical validation

React is responsible primarily for:

- Presentation
- User interaction
- UI state
- Navigation
- User experience


============================================================
3. ARCHITECTURAL STYLE
============================================================

Prefer a modular monolith.

Do NOT introduce unnecessary:

- Microservices
- Multiple competing engines
- Duplicate business logic
- Duplicate accounting engines
- Duplicate inventory engines
- Duplicate date systems
- Duplicate print engines
- Heavy infrastructure without clear justification

The architecture must prioritize:

- Simplicity
- Reliability
- Clear boundaries
- Testability
- Maintainability
- Performance
- Easy deployment


============================================================
4. CORE MODULES
============================================================

The ERP must include:

1. Dashboard
2. Parties
3. Customers
4. Suppliers
5. Products
6. Warehouses
7. Purchases
8. Sales
9. Inventory
10. Cash
11. Exchange Accounts
12. Full Accounting
13. Reports
14. Documents & Printing
15. Financial Periods
16. Backup & Recovery
17. Users & Permissions
18. Settings
19. Licensing

The navigation must remain visually simple.

Internal functionality must not automatically become
permanent top-level navigation.


============================================================
5. PARTY ARCHITECTURE
============================================================

Customer and Supplier must share a central Party concept.

PARTY TYPES:

- Customer
- Supplier
- Customer + Supplier
- Other Party

A single business entity must not be duplicated
unnecessarily.

Each Party must have:

- Identity information
- Contact information
- Currency information where applicable
- Transaction history
- Financial statement
- Balance
- Related documents


============================================================
6. CUSTOMER / SUPPLIER BALANCE
============================================================

Party balance must come from the ledger.

It must NOT be a manually maintained arbitrary field.

Every transaction must affect the Party ledger
according to the accounting rules.

The system must clearly distinguish:

- Debtor
- Creditor
- Settled

Every relevant invoice/document should show:

Previous Balance
+
Current Transaction
-
Payment / Allocation
=
New Balance


EXAMPLE:

Previous Balance:
10,000 USD Debtor

Current Sale:
2,500 USD

Payment:
3,000 USD

New Balance:
9,500 USD Debtor


The same principle applies to suppliers where appropriate.


============================================================
7. PRODUCT MASTER
============================================================

Product must support:

- Product Code
- Product Name
- Category
- Brand
- Unit
- Secondary Unit where required
- Barcode where required
- Purchase Price
- Sales Price
- Minimum Stock
- Active/Inactive
- Notes

Historical transaction prices must remain unchanged.

Changing current product pricing must NEVER modify
historical invoices or historical transactions.


============================================================
8. WAREHOUSE ARCHITECTURE
============================================================

The system must support multiple warehouses.

Examples:

- Main Warehouse
- Store Warehouse
- Secondary Warehouse

Each warehouse maintains independent stock.

Example:

Product X:

Warehouse A = 500
Warehouse B = 300

Total Company Stock = 800


============================================================
9. INVENTORY SOURCE OF TRUTH
============================================================

Inventory must be movement-based.

FORMULA:

Opening Stock
+ Purchase Receipts
+ Sales Returns
+ Transfer In
+ Positive Adjustments
- Sales
- Purchase Returns
- Transfer Out
- Negative Adjustments
=
Current Stock


Every stock movement must have:

- Product
- Warehouse
- Date
- Movement Type
- Quantity
- Source Document
- Reference
- Description


No important stock change may occur without
a traceable movement.


============================================================
10. WAREHOUSE TRANSFER
============================================================

Warehouse transfers are internal movements.

Example:

Warehouse A
        ->
Transfer
        ->
Warehouse B


System creates:

Warehouse A -> OUT
Warehouse B -> IN


Total company inventory must remain unchanged.

A normal internal transfer must NOT create:

- Revenue
- Expense
- Customer debt
- Supplier debt


============================================================
11. PURCHASE WORKFLOW
============================================================

The user should perform:

Supplier
    ->
Purchase Invoice
    ->
Items
    ->
Warehouse
    ->
Payment / Credit
    ->
Post


The system automatically performs:

Purchase Invoice
    ->
Inventory Receipt
    ->
Supplier Ledger
    ->
Accounting Journal
    ->
Reports


The user must not manually repeat the same transaction
in separate modules.


============================================================
12. PURCHASE INVOICE
============================================================

Purchase Invoice must support:

- Supplier
- Date
- Currency
- Exchange Rate
- Invoice Number
- Reference
- Warehouse
- Description
- Product
- Quantity
- Unit
- Unit Price
- Discount
- Tax where required
- Total
- Paid Amount
- Balance
- Previous Supplier Balance
- New Supplier Balance

Posted purchase documents must have historical integrity.


============================================================
13. SALES WORKFLOW
============================================================

The user should perform:

Customer
    ->
Previous Balance
    ->
Sales Invoice
    ->
Warehouse
    ->
Payment / Credit
    ->
Post


The system automatically performs:

Sales Invoice
    ->
Inventory Issue
    ->
Customer Ledger
    ->
Revenue
    ->
COGS
    ->
Accounting Journal
    ->
Reports


============================================================
14. SALES INVOICE
============================================================

Sales Invoice must support:

- Customer
- Date
- Currency
- Exchange Rate
- Invoice Number
- Reference
- Warehouse
- Description
- Product
- Quantity
- Unit
- Unit Price
- Discount
- Tax where required
- Total
- Paid Amount
- Balance
- Previous Customer Balance
- New Customer Balance

Posted sales documents must have historical integrity.


============================================================
15. FULL DOUBLE-ENTRY ACCOUNTING SYSTEM
============================================================

ACCOUNTING IS A CORE SYSTEM.

The ERP MUST contain a complete professional
Double-Entry Accounting System.

Accounting is NOT merely a transaction ledger.

Every financial transaction MUST follow
Double-Entry Accounting principles.

NON-NEGOTIABLE RULE:

TOTAL DEBIT = TOTAL CREDIT

No unbalanced Journal Entry may be posted.


============================================================
16. ACCOUNTING EQUATION
============================================================

The accounting system must maintain:

ASSETS
=
LIABILITIES
+
EQUITY


And for every Journal Entry:

TOTAL DEBIT
=
TOTAL CREDIT


============================================================
17. ACCOUNTING CORE
============================================================

The accounting system must include:

1. Chart of Accounts
2. Account Groups
3. Accounts
4. Journal Entries
5. Journal Lines
6. General Ledger
7. Subsidiary Ledgers
8. Customer Ledger
9. Supplier Ledger
10. Cash Ledger
11. Bank Ledger where applicable
12. Exchange House Ledger
13. Inventory Accounting
14. Accounts Receivable
15. Accounts Payable
16. Revenue
17. Cost of Goods Sold
18. Expenses
19. Assets
20. Liabilities
21. Equity
22. Owner Capital
23. Owner Drawings
24. Trial Balance
25. Profit & Loss
26. Balance Sheet
27. Cash Flow
28. Accounting Periods
29. Period Closing
30. Period Locking
31. Adjusting Entries
32. Reversal Entries
33. Opening Balances
34. Closing Entries
35. Audit Trail
36. Financial Reconciliation


============================================================
18. CHART OF ACCOUNTS
============================================================

The system must use a structured Chart of Accounts.

Recommended high-level groups:

1 - Assets
2 - Liabilities
3 - Equity
4 - Revenue
5 - Cost of Goods Sold
6 - Expenses


The exact account numbering and hierarchy must be
defined during PHASE 0 based on actual business requirements.

Each account should support:

- Account Code
- Account Name
- Account Type
- Parent Account
- Currency where applicable
- Active/Inactive
- Posting Allowed
- Description

Non-posting parent accounts must not receive direct
journal postings unless explicitly permitted by design.


============================================================
19. AUTOMATIC DOUBLE-ENTRY POSTING
============================================================

Every standard business transaction must generate
a balanced accounting entry automatically.

EXAMPLE:

CREDIT PURCHASE:

DR Inventory
CR Accounts Payable / Supplier


CASH PURCHASE:

DR Inventory
CR Cash


CREDIT SALE:

DR Accounts Receivable / Customer
CR Sales Revenue


SALE COST:

DR Cost of Goods Sold
CR Inventory


CUSTOMER RECEIPT:

DR Cash
CR Accounts Receivable


SUPPLIER PAYMENT:

DR Accounts Payable
CR Cash


EXPENSE PAYMENT:

DR Expense
CR Cash / Bank


OWNER CAPITAL:

DR Cash / Asset
CR Owner Capital


OWNER WITHDRAWAL:

DR Owner Drawings
CR Cash


The exact posting rules must be defined,
implemented and tested for every transaction type.


============================================================
20. ACCOUNTING TRANSACTION FLOW
============================================================

Business Transaction
        ->
Validation
        ->
Transaction Engine
        ->
Posting Rule
        ->
Journal Entry
        ->
Journal Lines
        ->
General Ledger
        ->
Subsidiary Ledgers
        ->
Financial Reports


============================================================
21. JOURNAL ENGINE
============================================================

Every financial transaction must produce
a traceable Journal Entry.

Journal Entry must support:

- Journal Number
- Jalali Date
- Transaction Date
- Description
- Reference
- Source Type
- Source ID
- Currency
- Exchange Rate
- Total Debit
- Total Credit
- Status

Journal Lines must support:

- Account
- Debit
- Credit
- Currency
- Original Amount
- Base Currency Amount
- Party where applicable
- Warehouse where applicable
- Description

MANDATORY:

TOTAL DEBIT = TOTAL CREDIT


============================================================
22. JOURNAL TRACEABILITY
============================================================

Every automatic Journal Entry must retain
a connection to its source document.

Examples:

Sales Invoice
    ->
Journal Entry

Purchase Invoice
    ->
Journal Entry

Customer Receipt
    ->
Journal Entry

Supplier Payment
    ->
Journal Entry


Users must be able to navigate:

Source Document
    ->
Journal

and:

Journal
    ->
Source Document


============================================================
23. GENERAL LEDGER
============================================================

The system must provide a complete General Ledger.

Each account should show:

- Opening Balance
- Debit
- Credit
- Running Balance
- Closing Balance

Support:

- Date filtering
- Account filtering
- Currency filtering
- Reference
- Source document
- Drill-down


============================================================
24. SUBSIDIARY LEDGERS
============================================================

The accounting system must support subsidiary ledgers.

Examples:

Accounts Receivable
    ->
Customer A
Customer B
Customer C


Accounts Payable
    ->
Supplier A
Supplier B
Supplier C


Cash
    ->
Cash AFN
Cash USD


Exchange Houses
    ->
Exchange House A
Exchange House B


============================================================
25. CUSTOMER ACCOUNTING
============================================================

Customer sale:

DR Accounts Receivable
CR Sales Revenue


Customer payment:

DR Cash
CR Accounts Receivable


Customer Balance must equal the appropriate
subsidiary/accounting ledger balance.


============================================================
26. SUPPLIER ACCOUNTING
============================================================

Credit purchase:

DR Inventory
CR Accounts Payable


Supplier payment:

DR Accounts Payable
CR Cash


Supplier Balance must reconcile with Accounts Payable.


============================================================
27. INVENTORY ACCOUNTING
============================================================

Inventory must integrate directly with accounting.

Purchase:

DR Inventory
CR Accounts Payable / Cash


Sale:

DR Accounts Receivable / Cash
CR Sales Revenue


Cost of Sale:

DR Cost of Goods Sold
CR Inventory


Inventory adjustments must use controlled
and auditable accounting rules.


============================================================
28. TRIAL BALANCE
============================================================

The system must provide a complete Trial Balance.

Fields:

- Account
- Opening Debit
- Opening Credit
- Period Debit
- Period Credit
- Closing Debit
- Closing Credit

Validation:

TOTAL DEBITS = TOTAL CREDITS


============================================================
29. PROFIT & LOSS
============================================================

Profit & Loss must be generated from accounting data.

Revenue
-
Cost of Goods Sold
-
Expenses
=
Net Profit / Loss


============================================================
30. BALANCE SHEET
============================================================

Balance Sheet must be generated from accounting data.

Assets
=
Liabilities
+
Equity


============================================================
31. CASH FLOW
============================================================

The ERP must support a proper Cash Flow report.

Cash movement must reconcile with the corresponding
cash ledger and accounting data.


============================================================
32. OPENING BALANCES
============================================================

The system must support controlled opening balances.

Opening balances must be entered through proper
double-entry accounting.

Opening balance entries must be balanced and auditable.


============================================================
33. ADJUSTING ENTRIES
============================================================

The system must support controlled adjusting entries.

Possible examples:

- Accruals
- Corrections
- Depreciation
- Inventory adjustments
- Other legitimate accounting adjustments

All adjustments must be auditable.


============================================================
34. REVERSAL
============================================================

Posted accounting transactions must not normally
be deleted as a correction mechanism.

Correction process:

Original Entry
    ->
Reversal Entry
    ->
Correct Entry


Historical audit trail must remain available.


============================================================
35. FINANCIAL PERIODS
============================================================

Financial periods must be configurable.

The business may use:

- 3 months
- 6 months
- 12 months
- Custom valid period


Example:

1405/01/01
to
1405/03/31


The system must NOT assume that every business
uses only a 12-month accounting period.


============================================================
36. PERIOD STATES
============================================================

Supported states:

OPEN
CLOSED
LOCKED


When locked:

- New posting is blocked
- Editing is blocked
- Deletion is blocked

Authorized users may reopen according to permissions.


============================================================
37. PERIOD CLOSING
============================================================

Period closing must not destroy historical data.

Closing procedures must preserve:

- Journal history
- Ledger history
- Invoices
- Inventory history
- Party history
- Audit trail

Detailed closing rules must be finalized
during PHASE 0.


============================================================
38. MULTI-CURRENCY ACCOUNTING
============================================================

Initial currencies:

- AFN
- USD

Architecture must support future currencies.

Every foreign-currency transaction must retain:

- Original Currency
- Original Amount
- Exchange Rate
- Base Currency Amount

Historical exchange rates must never silently change.


============================================================
39. CASH MANAGEMENT
============================================================

Cash must support multiple currencies.

Example:

Cash AFN
Cash USD


Operations:

- Receipt
- Payment
- Expense
- Owner Deposit
- Owner Withdrawal
- Currency Exchange where applicable


============================================================
40. EXCHANGE HOUSE / SARAFI
============================================================

The ERP must NOT recreate the internal remittance
system of exchange houses.

Exchange houses already have their own systems.

Our ERP only manages our company's financial
relationship with the exchange house.

Exchange House record may include:

- Name
- Contact
- Our Account/Reference
- Currency
- Amount
- Date
- Reference
- Description
- Related Party
- Status where required


EXAMPLE:

Exchange House:
Mizan

Transaction:

Money collected through Mizan
for purchase of 1000 barrels of 10-liter oil.

The ERP records the financial event and its reference.

It does NOT manage the exchange house's
internal remittance network.


============================================================
41. EXCHANGE HOUSE ACCOUNTING
============================================================

Exchange House transactions must integrate
with accounting.

Example:

DR Exchange House Account
CR Relevant Cash / Bank / Payable Account


The exact posting rule depends on the business event
and must be defined during PHASE 0.


============================================================
42. JALALI DATE ARCHITECTURE
============================================================

Jalali date handling is CORE INFRASTRUCTURE.

A centralized Date/Calendar Service must be used by:

- Sales
- Purchases
- Inventory
- Accounting
- Reports
- Documents
- Financial Periods
- Audit Logs

User-facing business dates must be correctly displayed
and entered using Jalali dates.

Example:

1405/06/05


The system must correctly support:

- Conversion
- Sorting
- Filtering
- Date ranges
- Month boundaries
- Year boundaries
- Leap-year behavior
- Financial periods
- Reports
- Printing


============================================================
43. DOCUMENT ENGINE
============================================================

A CENTRAL DOCUMENT ENGINE must exist.

Individual modules must NOT implement
independent printing engines.

Architecture:

DOCUMENT ENGINE
    ->
PRINT ENGINE
    ->
PDF ENGINE
    ->
TEMPLATES


Supported documents:

- Sales Invoice
- Purchase Invoice
- Warehouse Receipt
- Warehouse Issue
- Delivery Note
- Cash Receipt
- Cash Payment
- Exchange Document
- Selected Item Document
- Reports


============================================================
44. HALF-A4 PRINT STANDARD
============================================================

Operational documents must support optimized Half-A4 printing.

Preferred Half-A4 documents:

- Sales Invoice
- Purchase Invoice
- Warehouse documents
- Delivery documents
- Cash receipts
- Cash payments
- Check/Saraye/Godam documents
- Selected item documents
- Daily operational documents


Full A4 must remain available for:

- Large reports
- Financial statements
- Detailed reports
- Documents requiring larger layouts


Where appropriate, two Half-A4 documents
must fit correctly on one A4 sheet.


============================================================
45. PRINT PREVIEW
============================================================

Every printable document should support:

- Preview
- Print
- Save as PDF
- Template selection


The preview must represent the actual final document layout.


============================================================
46. PRINT CUSTOMIZATION
============================================================

Document templates must be customizable.

Possible fields:

- Company Logo
- Company Name
- Customer
- Supplier
- Previous Balance
- Current Transaction
- New Balance
- Warehouse
- Product Code
- Product Name
- Quantity
- Unit
- Price
- Discount
- Tax
- Total
- Signature
- Notes
- Barcode
- Reference


The user should be able to configure
visible fields and layout where supported.


============================================================
47. SELECTIVE ITEM PRINTING
============================================================

A single invoice may contain many products.

The user must be able to select individual items.

Example:

[✓] Oil A
[ ] Oil B
[✓] Oil C
[ ] Oil D


Then:

PRINT SELECTED ITEMS


Also support:

PRINT ONE ITEM


This is especially important for warehouse,
check/saraye and operational workflows.

This capability must be implemented in the
central Document Engine.


============================================================
48. REPORT CENTER
============================================================

A centralized Report Center must exist.


SALES REPORTS:

- Sales Summary
- Sales Detail
- Sales by Customer
- Sales by Product
- Sales by Warehouse


PURCHASE REPORTS:

- Purchase Summary
- Purchase Detail
- Purchase by Supplier
- Purchase by Product


INVENTORY REPORTS:

- Stock Summary
- Stock by Warehouse
- Product Kardex
- Stock Movement
- Stock Valuation
- Low Stock
- Warehouse Movement


PARTY REPORTS:

- Customer Statement
- Supplier Statement
- Receivables
- Payables
- Party Transactions
- Outstanding Balances


CASH REPORTS:

- Cash Ledger
- Cash Summary
- AFN Cash
- USD Cash


EXCHANGE REPORTS:

- Exchange House Statement
- Exchange Account Movement


ACCOUNTING REPORTS:

- Journal
- General Ledger
- Trial Balance
- Accounts Receivable
- Accounts Payable
- Profit & Loss
- Balance Sheet
- Cash Flow


FINANCIAL REPORTS:

- Financial Period Reports
- Reconciliation Reports


============================================================
49. REPORT FILTERS
============================================================

Reports should support relevant contextual filters:

- Date From
- Date To
- Party
- Product
- Warehouse
- Currency
- Status
- Document Number
- Account

Do NOT force irrelevant filters onto every report.


============================================================
50. REPORT DRILL-DOWN
============================================================

Reports must support drill-down where appropriate.

Example:

Customer Statement
    ->
Transaction
    ->
Invoice
    ->
Invoice Items
    ->
Stock Movement
    ->
Journal Entry


Important numbers must have traceable sources.


============================================================
51. REPORT RECONCILIATION
============================================================

Reports must reconcile with their source ledgers.

Examples:

Sales Report
=
Revenue Ledger


Customer Statement
=
Customer Ledger


Supplier Statement
=
Supplier Ledger


Inventory Report
=
Stock Movement Ledger


Cash Report
=
Cash Ledger


Trial Balance
=
General Ledger


Profit & Loss
=
Revenue + COGS + Expense Accounts


Balance Sheet
=
Accounting Equation


============================================================
52. BACKUP & RECOVERY
============================================================

Backup must be a complete and tested subsystem.

BACKUP:

Create Backup
    ->
Validate Backup
    ->
Store Backup


RESTORE:

Current State
    ->
Safety Backup
    ->
Restore
    ->
Integrity Check
    ->
Application Verification


Backup must preserve all critical business data.


============================================================
53. BACKUP RESTORE TEST
============================================================

Test process:

1. Create test data
2. Create backup
3. Modify/delete selected test data
4. Restore backup
5. Verify original data
6. Verify accounting integrity
7. Verify inventory integrity
8. Verify party balances
9. Verify reports
10. Verify application functionality


A backup is NOT considered valid merely because
a backup file was successfully created.


============================================================
54. BILINGUAL SYSTEM
============================================================

The ERP must support:

- Persian/Dari
- English

Localization must exist from the beginning.

Do NOT build English first and add Persian later.

Must support:

- i18n
- RTL
- LTR
- Localized labels
- Localized forms
- Localized reports
- Localized documents


============================================================
55. DESIGN SYSTEM
============================================================

The frontend must use a centralized Design System.

Architecture:

DESIGN TOKENS
    ->
COMPONENTS
    ->
LAYOUTS
    ->
SCREENS


Centralized control for:

- Colors
- Typography
- Spacing
- Buttons
- Inputs
- Tables
- Dialogs
- Cards
- Navigation
- Form controls


Individual screens must not invent
their own independent visual systems.


============================================================
56. USER EXPERIENCE
============================================================

The ERP must be:

- Simple
- Clean
- Fast
- Professional
- Familiar
- Easy to learn
- Not visually crowded


Important information should be visible immediately.

Detailed information should be accessible through:

- Details
- Tabs
- Drill-down
- Reports


Do NOT remove important functionality merely
to make the UI visually simple.


============================================================
57. PERFORMANCE
============================================================

Performance is a first-class requirement.

Avoid:

- Loading all customers at once
- Loading all products at once
- Loading all invoices at once
- Blocking network requests on the UI thread
- Unnecessary polling
- Excessive re-rendering
- Full-table recalculation on every keystroke


Use where appropriate:

- Search
- Pagination
- Lazy Loading
- Caching
- Debouncing
- Async operations
- Virtualized tables for large datasets


============================================================
58. SECURITY
============================================================

Security must include:

- Authentication
- Authorization
- Roles
- Permissions
- Audit Logs
- Secure document access
- Period locking
- Backup security
- License security
- Input validation
- Sensitive operation protection


Every sensitive operation must be traceable.


============================================================
59. AUDIT TRAIL
============================================================

Important business and financial actions must be auditable.

Audit records should contain where appropriate:

- User
- Date/time
- Action
- Entity
- Entity ID
- Previous State
- New State
- Reference
- Reason where required


Posted financial documents must maintain strong historical integrity.


============================================================
60. DOCUMENT STATES
============================================================

Documents should use controlled states.

Typical lifecycle:

DRAFT
    ->
POSTED
    ->
REVERSED / CANCELLED


Exact states may differ by document type.

Posted financial documents must not be casually edited.


============================================================
61. SOURCE OF TRUTH
============================================================

Inventory Source of Truth:

STOCK MOVEMENT LEDGER


Financial Source of Truth:

ACCOUNTING LEDGER


Party Balance Source of Truth:

PARTY / ACCOUNTING SUBLEDGER


Historical Invoice Source:

POSTED DOCUMENT


Historical Exchange Rate:

TRANSACTION RATE


UI Design Source:

CENTRAL DESIGN SYSTEM


Translations:

CENTRAL i18n SYSTEM


Dates:

CENTRAL JALALI DATE SERVICE


============================================================
62. DATA INTEGRITY
============================================================

Critical operations must be transactional.

A transaction must not partially succeed.

Example:

If a Sale is posted:

Either all required components succeed:

- Invoice
- Stock Issue
- Customer Ledger
- Revenue
- COGS
- Journal

OR:

The operation must fail safely
without leaving inconsistent partial state.


============================================================
63. HISTORICAL INTEGRITY
============================================================

Historical records must remain reproducible.

Changing:

- Current product price
- Current exchange rate
- Customer information
- Supplier information
- Configuration

must NOT silently change historical transactions.

Historical transactions retain their original values.


============================================================
64. ERROR HANDLING
============================================================

Errors must be:

- Clear
- User-friendly
- Actionable
- Logged
- Traceable


Do NOT expose raw technical exceptions
to normal users.

No silent critical failures.


============================================================
65. NAVIGATION
============================================================

Recommended high-level navigation:

Dashboard
Sales
Purchases
Inventory
Parties
Cash
Accounting
Reports
Documents
Settings


Secondary functionality should appear contextually
where possible.


============================================================
66. DASHBOARD
============================================================

Dashboard should show useful information:

- Sales today
- Purchases today
- Cash balances
- Receivables
- Payables
- Stock warnings
- Recent transactions
- Important alerts


Do NOT turn the dashboard into a wall of charts.


============================================================
67. SEARCH
============================================================

Search should make it easy to find:

- Customers
- Suppliers
- Products
- Invoices
- Receipts
- Payments
- Journals
- Documents
- References


Search must remain fast and scalable.


============================================================
68. DOCUMENT NUMBERING
============================================================

Each document type must use controlled numbering.

Examples:

SI-000001
PI-000001
RC-000001
PY-000001
JE-000001
TR-000001


Document numbering must be:

- Deterministic
- Unique
- Auditable


Posted document numbers must not silently change.


============================================================
69. COMMERCIAL LICENSING
============================================================

The architecture must be Commercial-Ready.

However, initial ERP development must NOT become
unnecessarily complicated because of licensing.


Architecture:

ERP Application
    ->
License Manager
    ->
Signed License
    ->
Validation


Potential future editions:

- Trial
- Standard
- Professional
- Enterprise
- Lifetime where commercially appropriate


Potential licensing controls:

- License ID
- Organization
- Edition
- Activation Status
- Issue Date
- Expiry Date
- Device Limit
- User Limit
- Enabled Modules
- License Type
- Activation Key
- Cryptographic Signature


============================================================
70. LICENSE SECURITY
============================================================

Do NOT use a simple hardcoded license check.

Commercial licenses should use cryptographic signatures.

Potential capabilities:

- Signed License
- Online Activation
- Offline Validation
- Expiration
- Grace Period
- Device Binding where appropriate
- License Revocation
- Tamper Detection
- Renewal


NON-NEGOTIABLE:

LICENSE FAILURE MUST NEVER CAUSE DATA LOSS.


License expiration must NOT:

- Delete database
- Delete invoices
- Delete accounting
- Delete inventory
- Destroy backups


A restricted/read-only mode may be used
according to the commercial policy.


============================================================
71. GOLDEN ACCOUNTING TEST
============================================================

Scenario:

Party:
Murad Mandawi

Transaction:
Receive 3,000 USD


Expected:

Cash:
+3,000 USD

Murad Receivable:
-3,000 USD


Journal:

DR Cash
    3,000 USD

CR Accounts Receivable - Murad
    3,000 USD


Expected:

Debit = Credit

Customer Statement:
Updated

Cash Ledger:
Updated

Journal:
Updated

Reports:
Updated


============================================================
72. GOLDEN PURCHASE TEST
============================================================

Supplier:
ABC

Warehouse:
Main

Product:
Oil A

Opening Stock:
0

Supplier Balance:
0


Purchase:

100 units

Unit Cost:
500 AFN

Total:
50,000 AFN

Credit Purchase


Expected:

Warehouse Stock:
100 units

Inventory Value:
50,000 AFN

Supplier Balance:
50,000 AFN Creditor


Accounting:

DR Inventory
    50,000 AFN

CR Supplier
    50,000 AFN


Debit = Credit


============================================================
73. GOLDEN SALES TEST
============================================================

Opening Stock:

100 units

Unit Cost:

500 AFN


Sale:

20 units

Sales Price:

700 AFN


Expected:

Stock:
80 units

Customer Balance:
14,000 AFN Debtor

Revenue:
14,000 AFN

COGS:
10,000 AFN

Gross Profit:
4,000 AFN


Accounting:
Balanced

Inventory:
Reconciled

Customer Ledger:
Updated


============================================================
74. GOLDEN WAREHOUSE TRANSFER TEST
============================================================

Initial:

Warehouse A:
100 units

Warehouse B:
0 units


Transfer:

100 units


Expected:

Warehouse A:
0

Warehouse B:
100

Total Company Stock:
100


No:

- Revenue
- Expense
- Customer debt
- Supplier debt


============================================================
75. GOLDEN PRINT TEST
============================================================

Create:

- Sales Invoice
- Purchase Invoice
- Warehouse Document
- Receipt


Verify:

- Half-A4 size
- Correct margins
- Correct Jalali date
- Correct Persian text
- Correct English text
- Correct RTL/LTR
- Correct totals
- Correct previous balance
- Correct current balance
- Correct new balance
- Correct item selection
- Correct PDF
- Correct Print Preview
- Correct physical print layout


Where appropriate:

Two Half-A4 documents must correctly fit on one A4 sheet.


============================================================
76. GOLDEN JALALI TEST
============================================================

Test:

- Normal dates
- Month boundaries
- Year boundaries
- Leap-year cases
- Date sorting
- Date filtering
- Financial periods
- Reports
- Invoice printing


Every module must use the same centralized date logic.


============================================================
77. GOLDEN BACKUP TEST
============================================================

Create:

- Customer
- Supplier
- Product
- Purchase
- Sale
- Receipt
- Payment
- Inventory movement
- Journal entries


Create backup.

Modify/delete test records.

Restore.

Verify:

- Customers
- Suppliers
- Products
- Inventory
- Party balances
- Cash
- Accounting
- Journal
- Reports
- Documents


============================================================
78. ACCOUNTING RECONCILIATION TESTS
============================================================

Must verify:

Sales
=
Revenue


Sales Cost
=
COGS


Customer Statement
=
Accounts Receivable


Supplier Statement
=
Accounts Payable


Inventory
=
Stock Movement + Inventory Accounting


Cash
=
Cash Ledger


Trial Balance
=
General Ledger


Balance Sheet
satisfies:

Assets
=
Liabilities
+
Equity


============================================================
79. TESTING GOVERNANCE
============================================================

Every feature must follow:

IMPLEMENT
    ->
UNIT TEST
    ->
INTEGRATION TEST
    ->
E2E TEST
    ->
ACCOUNTING RECONCILIATION
    ->
INVENTORY RECONCILIATION
    ->
UI VERIFICATION
    ->
PRINT VERIFICATION
    ->
REGRESSION TEST
    ->
APPROVED


If a critical test fails:

STOP
    ->
FIX
    ->
RETEST
    ->
VERIFY
    ->
APPROVE


============================================================
80. NO SYNTHETIC PASS
============================================================

Do NOT report PASS based on:

- Assumptions
- Code inspection alone
- Expected behavior
- Mocked success without meaningful verification
- Synthetic results


PASS must be supported by actual execution evidence
appropriate to the feature.


============================================================
81. DEVELOPMENT PHASES
============================================================

PHASE 0
DOMAIN & ACCOUNTING CONTRACT

Define and approve:

- Entities
- Relationships
- Business rules
- Accounting rules
- Chart of Accounts
- Posting rules
- Inventory rules
- Party balance rules
- Currency rules
- Jalali date rules
- Financial periods
- Document numbering
- Document states
- Permissions
- Reversal rules
- Audit rules
- Test scenarios


NO PRODUCTION DATABASE IMPLEMENTATION
UNTIL THE CORE DOMAIN CONTRACT IS APPROVED.


------------------------------------------------------------

PHASE 1
DATABASE + BACKEND FOUNDATION

Build:

- Django foundation
- Core models
- Authentication foundation
- Domain services
- Transaction boundaries
- Accounting foundation
- Inventory foundation
- Party foundation
- API foundation


TEST
    ->
VERIFY
    ->
APPROVE


------------------------------------------------------------

PHASE 2
REACT + TAURI + DESIGN SYSTEM

Build:

- React shell
- TypeScript structure
- Tauri desktop shell
- Design System
- RTL/LTR
- i18n
- Navigation
- Global error handling
- API client


TEST
    ->
VERIFY
    ->
APPROVE


------------------------------------------------------------

PHASE 3
MASTER DATA

Build:

- Parties
- Customers
- Suppliers
- Products
- Warehouses
- Currencies
- Accounts
- Exchange Houses


TEST
    ->
VERIFY
    ->
APPROVE


------------------------------------------------------------

PHASE 4
INVENTORY

Build:

- Stock movements
- Warehouse stock
- Receipts
- Issues
- Transfers
- Adjustments
- Kardex
- Stock reports


TEST
    ->
INVENTORY RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 5
PURCHASING

Build:

- Purchase Invoice
- Purchase Items
- Supplier Ledger
- Inventory Receipt
- Automatic Accounting
- Purchase Reports
- Purchase Printing


TEST
    ->
ACCOUNTING RECONCILIATION
    ->
INVENTORY RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 6
SALES

Build:

- Sales Invoice
- Sales Items
- Customer Ledger
- Inventory Issue
- Revenue
- COGS
- Automatic Accounting
- Sales Reports
- Sales Printing


TEST
    ->
ACCOUNTING RECONCILIATION
    ->
INVENTORY RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 7
CUSTOMER / SUPPLIER LEDGER

Build:

- Statements
- Receivables
- Payables
- Previous Balance
- Current Transaction
- New Balance
- Payment Allocation where required


TEST
    ->
RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 8
CASH

Build:

- Receipt
- Payment
- Cash Ledger
- AFN
- USD
- Cash Reports
- Automatic Accounting


TEST
    ->
ACCOUNTING RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 9
EXCHANGE ACCOUNTS

Build:

- Exchange House records
- Company balances
- Currency-specific ledgers
- References
- Automatic accounting
- Exchange reports


DO NOT BUILD A COMPLETE REMITTANCE SYSTEM.


TEST
    ->
RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 10
FULL ACCOUNTING

Complete:

- Chart of Accounts
- Journal
- General Ledger
- Subsidiary Ledgers
- Trial Balance
- Automatic Posting
- Manual Journal
- Reversal
- Period Locks
- Opening Balances
- Adjustments
- Financial Statements
- Reconciliation


TEST:
FULL DOUBLE-ENTRY ACCOUNTING TEST SUITE


APPROVE ONLY AFTER:

Debit = Credit

AND

Financial reports reconcile.


------------------------------------------------------------

PHASE 11
REPORTING

Complete:

- Operational reports
- Inventory reports
- Party reports
- Cash reports
- Exchange reports
- Accounting reports
- Financial statements
- Drill-down
- Export/printing where appropriate


TEST
    ->
RECONCILIATION
    ->
APPROVE


------------------------------------------------------------

PHASE 12
DOCUMENT & PRINT ENGINE

Complete:

- Central Document Engine
- Template Engine
- Half-A4
- Full A4
- Print Preview
- PDF
- Printing
- Custom Fields
- Selective Item Printing
- Warehouse Documents
- Invoices
- Receipts


TEST:

- Visual verification
- PDF verification
- Print verification
- Half-A4 verification
- RTL/LTR verification
- Jalali verification


APPROVE


------------------------------------------------------------

PHASE 13
FINANCIAL PERIODS

Complete:

- Custom periods
- Open
- Close
- Lock
- Reopen permissions
- Reversal/adjustment handling


TEST
    ->
ACCOUNTING VERIFICATION
    ->
APPROVE


------------------------------------------------------------

PHASE 14
BACKUP & RECOVERY

Complete:

- Backup
- Validation
- Restore
- Safety backup
- Integrity check
- Recovery verification


TEST:

REAL BACKUP
+
REAL RESTORE
+
DATA INTEGRITY


APPROVE


------------------------------------------------------------

PHASE 15
SECURITY & AUDIT

Complete:

- Authentication
- Roles
- Permissions
- Audit Logs
- Sensitive operation protection
- Security hardening


TEST
    ->
SECURITY VERIFICATION
    ->
APPROVE


------------------------------------------------------------

PHASE 16
FULL SYSTEM VALIDATION

Perform:

- Full E2E
- Accounting reconciliation
- Inventory reconciliation
- Party reconciliation
- Cash reconciliation
- Exchange reconciliation
- Backup/restore
- Printing
- Jalali
- Bilingual
- Performance
- Security
- Regression


NO PRODUCTION RELEASE
UNTIL THIS PHASE PASSES.


------------------------------------------------------------

PHASE 17
COMMERCIAL READINESS

Complete:

- License Manager
- Signed License
- Activation architecture
- Offline validation
- Expiration handling
- Commercial packaging
- Production installer
- Upgrade strategy


TEST:

Valid License
Invalid License
Expired License
Tampered License
Offline Validation
Renewal
Restriction Mode
Backup While Restricted
Data Integrity


============================================================
82. PHASE APPROVAL RULE
============================================================

A phase is APPROVED only when:

- Required tests PASS
- No unresolved P0 defects
- No unresolved critical P1 defects
- Accounting reconciliation PASS where applicable
- Inventory reconciliation PASS where applicable
- Required UI workflows PASS
- Printing PASS where applicable
- Regression PASS


Only after approval may the next phase begin.


============================================================
83. FINAL BUSINESS FLOW
============================================================

PURCHASE:

Supplier
    ->
Purchase Invoice
    ->
Warehouse Receipt
    ->
Supplier Ledger
    ->
Accounting
    ->
Reports
    ->
Printable Document


SALE:

Customer
    ->
Previous Balance
    ->
Sales Invoice
    ->
Warehouse Issue
    ->
Customer Ledger
    ->
Revenue
    ->
COGS
    ->
Accounting
    ->
Reports
    ->
Printable Document


RECEIPT:

Party
    ->
Receipt
    ->
Cash
    ->
Party Ledger
    ->
Accounting Journal
    ->
Reports


WAREHOUSE TRANSFER:

Warehouse A
    ->
Transfer
    ->
Warehouse B
    ->
Stock Movement
    ->
Updated Warehouse Balances


============================================================
84. FINAL SOURCE-OF-TRUTH MODEL
============================================================

BUSINESS DOCUMENT
        |
        +---- Inventory Movement
        |
        +---- Party Ledger
        |
        +---- Accounting Journal
        |
        +---- Cash / Exchange
        |
        +---- Reports
        |
        +---- Print Document


Every downstream result must be traceable
to a valid source transaction.


============================================================
85. FINAL PRODUCT STANDARD
============================================================

The final ERP must be:

SIMPLE FOR THE USER

POWERFUL FOR THE ACCOUNTANT

ACCURATE FOR INVENTORY

CLEAR FOR MANAGEMENT

TRACEABLE FOR AUDIT

FAST FOR DAILY OPERATIONS

SAFE FOR BUSINESS DATA

BILINGUAL

JALALI-FIRST

PRINT-READY

BACKUP-READY

COMMERCIAL-READY


============================================================
86. FINAL NON-NEGOTIABLE RULES
============================================================

RULE 1:
Accounting MUST be full Double-Entry Accounting.

RULE 2:
TOTAL DEBIT MUST ALWAYS EQUAL TOTAL CREDIT.

RULE 3:
No critical transaction may partially post.

RULE 4:
No posted financial transaction may be silently deleted.

RULE 5:
Historical transactions must remain reproducible.

RULE 6:
Inventory must be movement-based and traceable.

RULE 7:
Customer and Supplier balances must come from ledgers.

RULE 8:
Automatic accounting must be generated from business events.

RULE 9:
All important documents must be printable.

RULE 10:
Operational documents must support Half-A4.

RULE 11:
Users must be able to print selected invoice items.

RULE 12:
Jalali date logic must be centralized.

RULE 13:
Financial periods must be configurable.

RULE 14:
Backup must include real restore verification.

RULE 15:
The ERP must support Persian/Dari and English.

RULE 16:
The frontend must use a centralized Design System.

RULE 17:
No unnecessary architectural complexity.

RULE 18:
License architecture must be Commercial-Ready.

RULE 19:
License failure must NEVER cause data loss.

RULE 20:
NO VERIFIED TEST = NO NEXT PHASE.


============================================================
87. FINAL DEVELOPMENT COMMAND
============================================================

When implementing this blueprint:

DO NOT:

- Guess business rules
- Invent accounting rules without approval
- Duplicate business logic
- Bypass the accounting engine
- Bypass inventory controls
- Create independent printing engines
- Create independent date systems
- Introduce unnecessary architecture
- Mark untested functionality as PASS
- Move to the next phase while critical tests are failing


ALWAYS:

- Inspect existing architecture where applicable
- Define the domain rule first
- Implement the smallest correct solution
- Test immediately
- Reconcile accounting
- Reconcile inventory
- Verify UI
- Verify documents
- Verify performance
- Verify security
- Document the result
- Obtain phase approval


============================================================
88. FINAL PROJECT PRINCIPLE
============================================================

BUILD SMALL.

BUILD CORRECTLY.

TEST IMMEDIATELY.

VERIFY WITH REAL EVIDENCE.

KEEP ONE SOURCE OF TRUTH.

AUTOMATE REPETITIVE WORK.

PROTECT ACCOUNTING DATA.

PROTECT INVENTORY DATA.

PROTECT HISTORICAL DATA.

KEEP THE USER INTERFACE SIMPLE.

DO NOT ADD COMPLEXITY WITHOUT BUSINESS VALUE.


============================================================
END OF ERP MASTER BLUEPRINT & BUILD SPECIFICATION
VERSION 3.0
============================================================
