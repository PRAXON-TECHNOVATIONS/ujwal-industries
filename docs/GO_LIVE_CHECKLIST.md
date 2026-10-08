# Ujwal Industries — Go-Live Checklist

Everything that needs to be configured, verified, or filled in before the manufacturing floor starts running live transactions on this system. Grouped around the actual customizations built into the `ujwal_industries` app (hooks, custom doctypes, custom fields) — not generic ERPNext advice.

Use this as a literal checklist: `[ ]` → `[x]` as each item is confirmed **with real data**, not just reviewed on screen.

---

## ⚑ Critical Go-Live Blockers — check these first

These are not ordinary config gaps. Each one either silently corrupts data/behavior app-wide or hard-blocks a core transaction the moment go-live traffic starts. Confirm all of these before anything else in this document.

- [ ] **Supplier Approval workflow is active and at least one supplier has actually reached `workflow_state = Approved`.** The Supplier link-field query (`approved_supplier_only.py`) restricts every Supplier dropdown app-wide (PO, MR, Supplier Quotation, everywhere) to `workflow_state == "Approved"`. If the workflow isn't installed/active, no supplier can ever reach that state, and **every Supplier dropdown in the system will appear empty** — POs and MRs become impossible to create.
- [ ] **Item `custom_tolerance_` is set correctly on every manufactured item.** Both `job_card_override.py` and `stock_entry_override.py` disable ERPNext's native process-loss tracking and Work Order overproduction cap app-wide — `custom_tolerance_` on Item is now the **only** remaining control on how much a Work Order can over-produce. If it's left blank/0 on an item, there is effectively no upper bound on manufactured qty for that item.
- [ ] **Item Default rows (WIP Warehouse / Target Warehouse) exist per Company for every item used in manufacturing.** `work_order.py` pulls these at `before_insert`; if missing, a Work Order can be created with **no WIP warehouse**, silently breaking stock transfer/consumption later.
- [ ] **Document Series Settings has a row for every Purchase Order and Sales Invoice "type" combination in use** (subcontracted/service/import-RM/local for PO; labour/service/sub-invoice/export-local for SI). If no row matches, naming silently falls through to the generic numeric series; if a row matches but its number range is exhausted, document creation **hard-blocks** with a "series limit exceeded" error mid-transaction.
- [ ] **Every operational role referenced by notifications/approvals is actually assigned to a real, active user**: Planning Supervisor, Production Manager, Outsource Store Manager, Store Incharge, Sales and Purchase Head, **Sales Manager**, **Purchase Manager**. If nobody holds Sales Manager/Purchase Manager, the "Update Items" approval flow on Sales/Purchase Order gets stuck at "Pending Approval" with nobody but Administrator able to clear it. If nobody holds the other roles, notification-based handoffs (see Section 4) fail completely with no visible error.
- [ ] **Customer/Supplier `gst_category` set before onboarding** — this field is mandatory (`reqd=1`) via property setter on both doctypes; a new customer/supplier **cannot be saved at all** without it, which will block fast onboarding at go-live if GST category isn't known upfront.
- [ ] **`custom_po_no` (Pos. No.) is mandatory on every Sales Order/Delivery Note/Sales Invoice item row.** Rows synced automatically from a linked SO row get this auto-assigned; a row added manually and **not** linked back to an SO row (`so_detail`/`dn_detail`) will hard-block save until someone fills it in by hand — train order-entry staff on this before go-live, not after the first support ticket.
- [ ] **"Non Vaulted Closing Stock" and "Stock Report" reports are non-functional** — both only read Item master fields; their opening/closing/receipt/issue columns are never actually populated in code. Do not hand these to stock/accounts teams expecting real numbers; either fix them or clearly mark them as work-in-progress before go-live.
- [ ] **Reorder amendment logic hard-deletes the original document.** `mr_reorder.py` and the PO/SI/SO/DN/Quotation `before_insert` overrides all reuse an amended-from document's name by **deleting the original amended doc**. If anyone expects the original cancelled document to remain visible/auditable after amendment, it will not — confirm this is acceptable to accounts/audit before go-live.

---

## 1. Company & Core Masters

### 1.1 Company & Global Settings
- [ ] Company, fiscal year, default currency set
- [ ] Default Buying/Selling terms, default payment terms set

### 1.1a Stock Settings
- [ ] `Applicable Naming Series` for Item reviewed and confirmed **on** if Item numbering should follow Material Type (see 1.5 — Item autoname `throw`s during creation if a material type has no matching row in Item Naming Series and this is turned on, so this must be decided before the first Item is created, not after)
- [ ] If `Applicable Naming Series` is off, confirm the fallback numeric autoname (section 2) produces acceptable Item codes instead
- [ ] Default UOM, default Item Group, and stock valuation method confirmed with accounts (affects RM cost figures that flow into BOM costing and Cost Estimation)
- [ ] Naming series for Stock Entry, Material Request, etc. checked against Document Series Settings (section 2) for conflicts — Stock Settings and this app's own naming-series doctypes both govern numbering and should not disagree

### 1.1b Manufacturing Settings
- [ ] `Allow Backdated Planned Start Date` — **defaults to checked (on)**; decide the intended value deliberately, since leaving the default means planners *can* set a Production Plan's start date in the past with no warning
- [ ] `Enable Shift-wise Scheduling` — **defaults to checked (on)**; when on, production dates are calculated shift-wise rather than by plain working days, so confirm this actually matches how the planning team schedules today
- [ ] `Shift Types for Planning` (Table MultiSelect, references Bulk PP Planning Shift) populated with every shift type in use — if shift-wise scheduling is on and this is left empty, planning has no shifts to combine working minutes from
- [ ] Bulk PP Planning Shift master itself populated first (shift name + working minutes) before selecting shifts here
- [ ] Standard `Disable Capacity Planning` setting (native ERPNext, sits right above these custom fields) reviewed alongside the above — the two interact: capacity planning + shift-wise scheduling together should be tested on one real Production Plan before go-live

### 1.1c Ujwal Industries Settings (single doctype)
- [ ] `Remove Machine Conflict Validation` — **defaults to unchecked**; only enable if Bulk Pre-Production Plan should stop checking for machine double-booking
- [ ] `Bypass Create Work Order and Material Request on Submit` — **defaults to unchecked**; ⚑ if turned on (by accident or otherwise), submitting a Production Plan silently skips WO/MR creation — confirm this is a deliberate choice, not an oversight
- [ ] `Consider SPM for Split` — **defaults to unchecked**; affects whether In House / In House-Vendor rows with no tool load qty and no fixed lot capacity fall back to SPM-based batch splitting or run as one unsplit batch (subcontract rows are unaffected either way) — confirm with planning which behavior is wanted before the first real Bulk Pre-Production Plan run

### 1.2 Warehouses
- [ ] All physical warehouses created (Stores, RM, Finished Goods, per-floor/per-shed if applicable)
- [ ] Work-in-Progress warehouse set on Company / Manufacturing Settings
- [ ] Scrap warehouse set and linked correctly (Stock Entry scrap tolerance validation depends on scrap actually landing in the right warehouse)
- [ ] Subcontracting warehouses set up for every subcontracting supplier used (goods sent to subcontractor tracked correctly)
- [ ] Rejection/QA-hold warehouse set up if Quality Inspection flow requires one

### 1.3 Workstations & Machines
- [ ] All Workstations created, one per physical machine/line
- [ ] Workstation base costing fields filled in (drives `Workstation.validate` day-cost calculation):
  - [ ] Holiday list assigned
  - [ ] Operating cost / hour rate set
  - [ ] `Machine EMI per Day`
  - [ ] `Wages per Shift`
  - [ ] `Electricity Charges per Shift`
  - [ ] `Factory Expenses per Day`
  - [ ] `Finance Cost per Day`
  - [ ] `Admin Cost per Day`
  - [ ] Confirm these were correctly migrated if renamed from old "per Day" wages/electricity fields — verify no data was lost in the rename
- [ ] Workstation Users mapping done for every workstation (controls which operator sees which machine on the floor and in Job Card list views)
- [ ] Workstation downtime reasons (Job Card Pause Reason master) populated with the actual reasons the floor uses

### 1.4 Assets & Asset↔Machine/Tool Mapping
- [ ] Asset Category tree structure set up correctly: group categories (`is_group`) at the top, real (non-group) categories underneath — non-group categories require Accounts to be set, and a non-group category's parent must be a group node, both enforced on save
- [ ] A dedicated **Tool** group Asset Category exists at the root — every asset meant to be used as a BOM operation tool must sit under this category (or a child of it), since tool-eligibility checks (`is_tool_asset_category`) walk up to confirm the parent category is literally named "Tool"
- [ ] `Tool Type` field (New / Old) set correctly on every Asset under the Tool category — this feeds directly into the Asset ID, not just informational
- [ ] Confirm the Asset ID naming scheme is understood by whoever creates tool assets: `<ItemCodePrefix>-<CategoryPrefix>-<ToolTypeLetter>-<NN>` (e.g. item code + category + N/O for New/Old + running number) — Item Code and Tool Type are **mandatory** for this to generate; non-tool assets keep standard ERPNext naming
- [ ] Every physical machine that is also tracked as a fixed Asset (for depreciation/maintenance) is linked to its corresponding Workstation record — confirm the team has a clear convention for which machines get both an Asset **and** a Workstation record vs. Workstation only
- [ ] Every tool that a BOM Operation can require is registered as an Asset under the Tool category **and** also added to the relevant BOM's `custom_tool_details` child table (see 1.6) with the correct default flag — an asset existing without being linked on the BOM won't be picked up in tool-conflict/scheduling checks
- [ ] Asset Maintenance records set up for machines with a maintenance schedule — confirm `Asset Maintenance` "end date from asset" auto-fill behaves correctly on a real record
- [ ] Asset Category accounts (for non-group categories) mapped to the correct GL accounts before any asset purchase/depreciation entry is posted

### 1.5 Item Master
- [ ] Material Type master populated with every material type the plant actually uses
- [ ] Item Naming Series (per Material Type) configured in Stock Settings with correct `from_start` / `to_end` ranges — required before the first Item is created, since Item autoname throws if a material type has no series defined
- [ ] Item Subcontracting Suppliers set on every subcontracted item:
  - [ ] Exactly one default supplier per (item, company)
  - [ ] No duplicate (company, supplier) rows
  - [ ] Lead time (days) filled in and non-negative
  - [ ] `Rate per Pc` per (item, supplier, operation) filled in — this feeds Cost Estimation and PO rate fetch
- [ ] Confirm BOM subcontract operation cost re-syncs correctly after an Item's subcontract data changes (automatic on Item save — spot check one item)
- [ ] Item Group / UOM / Reorder level & reorder qty set where used by the hourly reorder job (`optimized_reorder_item`)

### 1.6 BOM & Related Masters (Operations, Tools, Scrap, Batch Size)
- [ ] Operation master created for every distinct manufacturing operation the plant runs
- [ ] On each BOM Operation row:
  - [ ] `custom_batchsize` set correctly (BOM cost is monkey-patched to divide operating cost by this, **not** ERPNext's standard `batch_size` — confirm every operation has a real value, since it silently defaults to 1 if missing/zero)
  - [ ] `Cascade Complete Previous` flag reviewed — controls whether a Job Card operation can be submitted before the prior one completes
  - [ ] `custom_workstations_csv` populated with the actual eligible machines for that operation (drives `custom_machine_count` used for conflict/capacity checks)
  - [ ] `custom_fixed_lot_capacity` set only where there's **no** tool linked to that operation (BOM validation throws if both a default tool and a fixed lot capacity are set on the same operation)
- [ ] Tool master (Asset Category → Tool + sub-categories) set up, and BOM `custom_tool_details` child table reviewed:
  - [ ] Exactly one tool marked `is_default` per operation on each BOM
  - [ ] Tool load quantity set per tool/operation row where relevant
- [ ] Scrap Items reviewed on each BOM — scrap item, rate, and expected qty match real-world yield loss
- [ ] `Total Scrap Cost` / RM cost / operation cost reviewed on a few representative BOMs after a manual `update_cost` run, to confirm the custom batch-size costing logic produces sane numbers
- [ ] BOM Approval workflow states and approvers confirmed (see Section 3)
- [ ] Default BOM correctly flagged per item, and route/name auto-generation (`BOM-<item>`, `BOM-<item>-<component>` fallback) understood by whoever creates BOMs manually

### 1.7 Customer Master
- [ ] Customer Naming Series configured
- [ ] Customer autoname behavior confirmed
- [ ] Compliance docs custom fields present and populated for customers where applicable:
  - [ ] `MSME/GST Doc`
  - [ ] `MSME` doc
  - [ ] `GST` doc
- [ ] Position number sync fields reviewed if customer POs carry item-level position/line numbers (Sales Order → Delivery Note → Sales Invoice sync)

### 1.8 Supplier Master
- [ ] Supplier Naming Series configured
- [ ] Supplier autoname confirmed
- [ ] GSTIN duplicate check tested (`before_save` throws on duplicate GSTIN across suppliers) — confirm real supplier GSTINs are entered correctly the first time to avoid this blocking onboarding mid-migration
- [ ] Approved Supplier query (`standard_queries.Supplier`) confirmed to return the expected supplier list in link fields — if it filters by "approved" status, make sure real suppliers are actually marked approved before go-live
- [ ] Supplier Quotation → Purchase Order flow tested with at least one subcontracted item to confirm rate lock behavior (`custom_subcontract_rate_locked` on PO Item) works as expected

### 1.9 Company Contact Details, Address & GSTIN
- [ ] Company GSTIN(s) entered correctly per registered business location (multi-GSTIN if the company has more than one registered premises/state)
- [ ] Company primary Address created and linked (used as "Company Address" on Sales Invoice, Purchase Order, Delivery Note, and Print Formats)
- [ ] Company billing/shipping addresses distinguished if dispatch happens from a different location than billing
- [ ] Company primary Contact (phone, email) set — appears on outward-facing print formats
- [ ] Bank account / bank details linked to Company for print formats that show payment instructions
- [ ] Customer GSTIN + Address + Contact populated for every active customer (required for GST-compliant Sales Invoice/e-Way Bill generation) — cross-check against `MSME/GST Doc`, `MSME`, and `GST` custom fields in section 1.7
- [ ] Supplier GSTIN + Address + Contact populated for every active supplier (required for Purchase Order/GRN and appears in PO Register / ZPUR Reg reports which pull `supplier_gstin` directly)
- [ ] GST Settings (HSN/SAC codes, GST accounts, state code mapping) configured if e-Invoicing/e-Way Bill is in scope
- [ ] Terms & Conditions templates created and linked to the relevant transaction types (PO, SO, Quotation)

### 1.10 Pricing — Price Lists & Item Prices
- [ ] Standard Buying and Standard Selling Price Lists created (or renamed to match how the team refers to them, e.g. domestic/export, or region-wise if applicable)
- [ ] Currency set correctly per Price List (relevant if any customers/suppliers are billed in a foreign currency)
- [ ] Item Prices loaded for every active item on the relevant Price List(s) — bulk-imported from the old costing sheet/Excel rather than left blank
- [ ] Price List linked correctly on default Customer/Supplier records so the right rate populates automatically on new transactions
- [ ] Relationship between Item Price and Cost Estimation module clarified with the team — confirm whether Cost Estimation output is expected to update Item Price automatically, or whether the two are maintained independently (currently independent — Cost Estimation has no BOM/Price List dependency by design)
- [ ] Purchase Order item rate fetch from Cost Estimation (section 5) reconciled against Item Price / Supplier Quotation rates so there's no confusion about which number is authoritative at PO time
- [ ] Pricing Rules (discounts, margins) configured if used, and tested against at least one real customer/item combination
- [ ] Tax templates (Sales Taxes and Charges Template, Purchase Taxes and Charges Template) set up per GST slab used, and set as default where applicable

---

## 2. Naming Series & Document Numbering

- [ ] Document Series Settings configured for every relevant doctype
- [ ] Customer, Supplier, and Item naming series confirmed with the team (see 1.5/1.7/1.8 for detail)
- [ ] Fallback numeric autoname (`numeric_series`, wired to the `"*"` hook) reviewed — confirm it doesn't clash with any ERPNext doctype where you want to keep default naming
- [ ] Starting numbers agreed with accounts/store (continuing from old registers vs. fresh start)
- [ ] Purchase Order, Sales Invoice, Asset autoname overrides tested with one real document each

---

## 3. Roles, Permissions & Approval Workflows

- [ ] Custom roles created & assigned: **Store Manager**, **Store Incharge**, **Outsource Store Manager**, **Planning Supervisor** — plus standard roles: Manufacturing/Production Manager & User, Sales Manager & User, Purchase Manager & User, Accounts Manager & User, Stock Manager & User, Delivery Manager & User, Job Card Operator
- [ ] Workstation / Job Card / Work Order visibility restrictions tested per role (permission query hooks) — log in as a floor operator and confirm they only see their assigned machine's jobs
- [ ] Approval workflows live and approvers confirmed at each state:
  - [ ] Supplier Approval
  - [ ] Material Request Approval
  - [ ] Purchase Order Approval
  - [ ] BOM Approval
- [ ] Order Item Approval custom fields tested on at least one Sales/Purchase Order item update (`Update Approval Status`, `Update Request Reason`, `Update Request Data`)
- ⚑ **Verify "Super Approver" role actually exists and is assigned** — found referenced oddly in the role fixture list next to "Sales Executive" (looked like a possible missing comma/typo); confirm on the live site rather than trusting the fixture as-is

---

## 4. Notifications

- [ ] Store Incharge notified on Material Request creation & Work Order submit
- [ ] Sales/Purchase Head notified on Material Request submit
- [ ] Planning Supervisor notified on Sales Order submit
- [ ] Production Supervisor notified on Work Order creation
- [ ] Outsource Store Manager notified on Subcontracting Order creation
- [ ] Store Incharge notified on Purchase Order submit
- [ ] All named users have real email addresses, and SMTP is tested end-to-end with a real transaction — not just confirmed to exist in code

---

## 5. Cost Estimation Module

- [ ] Cost Estimation fields reviewed end-to-end by whoever used the old Excel sheet (Item / Operation / Workstation driven, deliberately no BOM dependency)
- [ ] PO item rate fetch from Cost Estimation tested on a real Purchase Order (most recently added feature)
- [ ] Annexure rate fetch checked against a known-correct historical quote
- [ ] `Annexure Rate Locked` field on Stock Entry Detail behaves as expected once a rate is locked
- [ ] Other Costs and Profit % calculations verified against finance's expected margin
- [ ] Summary column cross-checked on 2–3 real historical jobs against the old Excel sheet's output
- [ ] Workstation Cost Estimation tab fields (EMI, wages, electricity, factory expenses, finance cost, admin cost per day) confirmed filled in for every workstation used in estimation — these feed directly into estimate accuracy

---

## 6. Transaction Doctype Customizations

Business rules and automations baked into Material Request, Purchase Order, Purchase Receipt, Sales Order, Sales Invoice, Quotation, Delivery Note, Work Order, Job Card, and Stock Entry. Each depends on specific master data or settings being right — most will not throw a visible error if that dependency is wrong, they'll just produce quietly incorrect results.

### 6.1 Material Request
- [ ] Item Reorder rows (warehouse, reorder level, reorder qty, material request type) reviewed for every item under auto-reorder — the hourly `optimized_reorder_item` job groups these into cumulative MRs per (company, warehouse, type); stale reorder levels silently over- or under-generate MRs
- [ ] Item `purchase_uom` and its UOM Conversion Detail factor confirmed correct for every reorder-managed item — a missing conversion factor produces MRs with the wrong quantity/UOM without any error
- [ ] Stock Settings `auto_indent` and `reorder_email_notify` reviewed — confirm intended on/off state
- [ ] `Material Request.set_warehouse` and `custom_custom_material_request_type` confirmed mandatory in practice — both are `reqd=1` via property setter; MRs cannot be saved without a target warehouse and a request type
- [ ] Reorder-created MRs are correctly tagged `custom_custom_material_request_type = "Reorder"` — spot check one auto-generated MR
- ⚑ Amendment behavior understood: amending an MR **deletes the original document** and reuses its name — confirm this is acceptable for audit trail purposes (also true for PO/SI/SO/DN/Quotation, see blockers above)

### 6.2 Purchase Order
- [ ] Custom PO numbering by type (`is_subcontracted` / `custom_service_po` / `custom_purchase_type`: Import RM vs Local) tested against real Document Series Settings rows — see the Critical Blockers section above
- [ ] "Update Items" dialog approval flow (`custom_update_approval_status`) tested end-to-end with a real Purchase Manager user — item deletion is blocked entirely by design, and `custom_po_no` (Pos. No.) is mandatory on every row
- [ ] `custom_subcontract_rate_locked` field behavior confirmed: once a Cost-Estimation-sourced rate is locked on a PO Item, changing the underlying Cost Estimation afterward does **not** flag the PO as stale — there's no visible warning if the two drift apart
- [ ] Purchase Order Item `rate` precision setting confirmed correct for low-unit-cost items (precision was explicitly customized)

### 6.3 Purchase Receipt
- [ ] `custom_gate_pass` link populated on every PR created via the Gate Pass flow — `custom_actual_processing_days` (computed from Gate Pass time to PR creation time) silently stays blank with no warning if this link is missing
- [ ] Quality Inspection → PR processing-time write-back tested: QI's `item_code` must match a PR item exactly (variant/batch mismatches make the write silently no-op)

### 6.4 Sales Order
- [ ] `customer_name_` custom field behavior confirmed with the sales team — if populated, it force-overwrites the standard `customer_name` on the SO; garbage/wrong data here silently overwrites the real customer display name
- [ ] Sales Order quantity lock tested: once a submitted Production Plan has consumed a line's qty (`production_plan_qty > 0`), that line's qty cannot be changed or removed without first cancelling the plan — confirm this field stays correctly in sync, since a stale value either fails to protect against real qty drift or blocks edits that should be legal
- [ ] "Forecast" Sales Order Type option confirmed available and used consistently if forecast orders are part of the workflow (added via property setter to the standard `order_type` field)
- [ ] `custom_po_no` (Pos. No.) sync from SO → Delivery Note → Sales Invoice tested on one real order with multiple line items, including a manually-added extra line (to confirm the "must fill in by hand" fallback behaves as expected)

### 6.5 Sales Invoice
- [ ] Custom SI numbering by type (`custom_is_labour` / `custom_service_sale_invoice` / `custom_sub_invoice` / `custom_invoice_type`: Export vs Local) tested against real Document Series Settings rows
- [ ] Custom SI e-Invoice print format tested only **after** generating the e-Invoice (IRN/QR code render blank silently if printed before e-Invoice Log/e-Waybill Log exist for that invoice)
- [ ] GST breakup (CGST/SGST vs IGST branching) verified against a real inter-state and a real intra-state invoice

### 6.6 Quotation
- [ ] Amendment name-reuse behavior confirmed acceptable (only customization on this doctype)

### 6.7 Delivery Note
- [ ] `custom_po_no` position-number sync from Sales Order tested (see 6.4)
- [ ] Amendment name-reuse behavior confirmed acceptable

### 6.8 Work Order
- [ ] WIP/Target warehouse auto-fill from Item Default tested for at least one item per company — see Critical Blockers above if Item Default rows are missing
- [ ] Production Plan's planned end date confirmed to survive Work Order submission unchanged (core ERPNext would otherwise recompute it)
- [ ] Store Incharge role's Work Order visibility restriction tested (should only see In Process / Not Started, not Completed/Closed)
- [ ] "Material Return" stock entry builder tested for returning leftover transferred RM
- [ ] Batch-size-aware operation splitting tested on a multi-workstation operation: `custom_batchsize` and `custom_workstations_csv` (CSV of eligible machines) on BOM Operation drive job-card time/qty splitting — a malformed CSV or a zero/blank batch size silently changes the split math (defaults to full WO qty per operation instead of per-batch)
- ⚑ Confirm awareness that the standard Work Order overproduction cap has been **removed entirely** — see Critical Blockers above regarding `custom_tolerance_`

### 6.9 Job Card
- [ ] `custom_tolerance_` (%) on Item confirmed set correctly for every manufactured item — this gates how much completed qty variance is allowed at submit before the app blocks it; missing/0 means **zero tolerance**, which will hard-block legitimate small variances
- [ ] Aware that FG-availability sequencing validation (blocking a Job Card from logging more completed qty than the previous operation/transferred material allows) is **currently commented out** in the codebase — it is not enforced today even though the logic exists; confirm with the dev team whether this is intentional for go-live
- [ ] Job Card editing blocked correctly while its Workstation has active downtime or its linked Asset has open Asset Maintenance
- [ ] "Material Return" and "Order Completed" pseudo-statuses (tracked via time-log pause reasons) tested on one real multi-operation Job Card
- [ ] `sequence_id` field confirmed intentionally editable (made read-only=0 via property setter, to support tolerance-based sequence bypass) — make sure operators understand they can technically reorder sequence and use this responsibly
- ⚑ Confirm awareness that `process_loss_qty` is **force-set to 0 everywhere** (on save, on Work Order update, on submit) — any real scrap/loss must go through the app's custom scrap Stock Entry flow; if operators don't follow that flow, loss is invisibly zeroed out with no trace

### 6.10 Stock Entry
- [ ] Manually-entered basic rates confirmed to survive save correctly (`set_basic_rate_manually` stash/restore logic) alongside india_compliance's GST recalculation
- [ ] Scrap-item tolerance tested in both modes:
  - [ ] Pure Scrap Entry (`custom_is_scrap_entry`) — checked against previously booked scrap for the Work Order, upper-limit only
  - [ ] Combined Manufacture + Scrap — min/max tolerance sourced from BOM Scrap Item's `custom_tolerance_`
- [ ] `custom_annexure_rate_locked` behavior confirmed — same staleness risk as PO's `custom_subcontract_rate_locked` (6.2): no visible flag if the underlying Cost Estimation changes after lock
- [ ] Confirms a Job Card exists for every operation before allowing a Manufacture entry (`check_if_operations_completed`, using Manufacturing Settings' `overproduction_percentage_for_work_order`) — test on a WO with a skipped operation to confirm it actually blocks
- [ ] Stock Entry Detail rate precision (`basic_rate`, `valuation_rate`) confirmed correct for both high-value and low-unit-cost items

### 6.11 Downtime Entry
- [ ] `to_time` discipline confirmed for pure Workstation downtime (mandatory) vs Job-Card-linked downtime (optional/open-ended) — a downtime entry with `to_time` far in the future by data-entry error leaves that Workstation stuck in "Problem" status, silently blocking all Job Card edits against it until manually corrected

### 6.12 Data Import (Production Plan)
- [ ] Backdated-date blocking on Production Plan Excel import tested with the actual column headers used in the real import template — the check fuzzy-matches header wording, so a renamed/reworded column silently escapes the backdating check

---

## 7. Shop Floor: Production Plan & Bulk Planning

- [ ] Bulk Pre-Production Plan / Bulk PP tool run once on real sales order data (covers Bulk PP Item, Sub Assembly Item, Material Request Item, BOM Selection, Planning Shift child tables)
- [ ] Production Plan Importer / Data Import path tested with a real Excel file and the actual column headers used (see 6.12 for the fuzzy-match caveat)
- [ ] Gate Pass flow walked through for at least one inbound and one outbound movement
- [ ] Quality Inspection → GRN processing time, and Purchase Receipt actual processing time, verified end to end (see 6.3)
- [ ] Serial No custom "Source Document" fields (reference doctype/name, posting date) populated correctly for traceability reporting
- [ ] Downtime Entry → Workstation status sync confirmed live (runs every minute via cron) — confirm the scheduler is actually enabled on the production bench (`bench doctor`), not just that the code exists

---

## 8. Dashboards, Workspaces, Reports & Print Formats

Every custom page and report reads live transaction data through specific assumptions. Test each against real data, not empty filters — several depend on conventions (like an item code prefix) that aren't obvious from the UI, and two reports are currently non-functional.

### 8.1 Floor Display Pages
- [ ] **BOM Tool Display** — only picks up finished goods whose item code starts with **"300"**; if the plant's FG coding convention doesn't match this, tools silently never appear. Requires `Tool Child Table` populated on submitted default BOMs and `Job Card.custom_tool_name` set.
- [ ] **Delivery Risk Dashboard** — risk levels (Overdue/Delivery Risk/On Hold/On Track) are computed from Work Order pace vs. delivery date; wrong/missing WO `planned_end_date` or `actual_start_date` skews every prediction. A Sales Order with no Work Order yet just shows a generic "overdue"/"no WO" with no further diagnosis.
- [ ] **Dispatch Display** — reads upcoming/overdue dispatch buckets from Bulk Pre-Production Plan's `custom_batch_schedule` JSON; if a Sales Order has no Bulk PP or no ticked batch, its whole FG collapses into a single bucket dated to the SO delivery date (looks like a bug if unexplained). 3-day lookahead window only.
- [ ] **Machine Production Display** — groups active Job Cards by Workstation for a 7-day window; requires `Job Card.workstation` and `Workstation.custom_asset` populated, else machines group under "Unknown".
- [ ] **Purchase Order Display** — PR→PO lead time only populates if `Purchase Order Item.material_request` is actually linked; confirm buyers link the MR when converting to PO.
- [ ] **Purchase Requisition Display** — supplier column stays blank by design until a PO exists against that MR line — flag this to users up front so it isn't reported as a bug.
- [ ] **Sales Order Tracking** — its "stages done" logic counts any completed Job Card, which is a different rule than Delivery Risk Dashboard uses (FG completion) — the two dashboards can legitimately show different stage counts for the same order; brief the team so this doesn't read as a data inconsistency.
- [ ] **Stock Requirements** — MD04-style running balance depends on every source document (PO/MR/WO/SO/Stock Entry) carrying the correct warehouse; a wrong-warehouse transaction simply won't appear anywhere in the projection.
- [ ] **Store Display** — `balance_to_confirm` depends on Job Card `total_completed_qty` staying in sync with Work Order `produced_qty`; spot check after a real WO run.
- [ ] **Subcontract Issued Display** — RM columns stay blank by design until a Subcontracting Order exists against the PO.
- [ ] **Subcontract Received Display** — actual receipt is sourced from Subcontracting Receipt Items, **not** PO Item `received_qty` — a Purchase-Receipt-only workflow will under-report here; confirm the team actually uses Subcontracting Receipts.
- [ ] **Tool Readiness Display** — matches tools at the BOM level that carries them; tools needed for a Sales Order with no Production Plan yet are silently excluded even if urgently needed.

### 8.2 Number Cards
- [ ] Job Cards (Completed/WIP) and Work Order (Not Started/In Process/Completed) counts confirmed accurate — these are plain status counts and depend on status transitions actually firing correctly
- [ ] PR - Draft, SC Orders - Open, SE - Material Issue counts spot-checked against their underlying filters
- ⚑ **Workstation (Production) / Workstations (Downtime) cards depend entirely on someone manually maintaining `Workstation.status`** — ERPNext does not auto-update this field on its own, so these cards will drift stale unless the floor team (or the per-minute downtime sync) is actually keeping status current

### 8.3 Workspaces
- [ ] **Job Card Operator** workspace — restricted to the "Job Card Operator" role specifically (not "Manufacturing User"); confirm operators actually hold this exact role or they'll land on a workspace with no tiles
- [ ] **Planning** workspace — references number cards ("Bulk Pre Prod" / "Plans from Bulk PP" / "Plans Submitted" / "Plans Completed") that do **not** currently exist under this app's number_card directory — ⚑ verify these resolve on the live site or the Planning workspace will show broken/blank tiles
- [ ] **Production Manager** workspace — uses the confirmed WO/Job Card number cards, should render correctly
- [ ] **Store** workspace — links a "Subcontracting Order Summary" report reference that doesn't match any report in this app — ⚑ verify it resolves to a standard ERPNext report, or the tile will be broken

### 8.4 Reports
- [ ] **BOM Stock Tree Report** — needs correct BOM `is_active`/`docstatus` flags and warehouse-company scoping to explode correctly
- [ ] **BOM Tool Report** — same "300" item-code prefix and `custom_tool_name` dependency as BOM Tool Display (8.1)
- [ ] **Display Report** — needs `Workstation.custom_asset` and expected/planned dates set; 3-day default window
- [ ] **Gate Entry GRN Report** — needs `Purchase Receipt.custom_gate_pass` actually linked, or GRN qty shows blank
- [ ] **GRN Processing Time** — needs `Item.custom_expected_grn_processing_days` populated; the "actual" side is not auto-calculated here, it must come from elsewhere (see 6.3)
- [ ] **GRN Vs Sales Report** — ⚑ merges Purchase Receipt/PO rows with Stock Entry and Sales Invoice rows by list position / exact date match rather than a real join — treat its "Qty Sale" column as approximate, not authoritative
- [ ] **Labour Variance Report** — needs accurate Job Card `time_required` estimates and consistent time-log entry to apportion variance correctly per employee
- [ ] **PO Register** — needs tax templates correctly populating `cgst`/`sgst`/`igst_amount` fields, and `supplier_gstin` set on every relevant PO
- [ ] **Rejection Report** — depends on rejection quantities being filled in correctly at GRN/QI time
- [ ] **RM GRN Report** — ⚑ classifies GL accounts (Insurance/Freight/GST) by string-matching the account name (`LIKE '%...%'`) — a renamed or non-English Chart of Accounts account name will silently break this classification
- [ ] **Serial No and Batch Traceability** — requires an item/batch/serial filter to run at all; needs consistent `has_serial_no`/`has_batch_no` flags and clean Stock Entry data
- [ ] **Sub Vendor Reconciliation** — requires the `bs4` Python package installed in the bench environment, or the report errors out
- [ ] **Tool Utilisation** — needs `tool_load_quantity` populated on tool rows; note the report builds part of its SQL via raw string `.format()` on `bom_no`, which is fragile — worth hardening before wide rollout
- [ ] **Work Order Stock Entries** — depends on Work Order Item `consumed_qty` and correctly-typed Stock Entries to build the tree correctly
- [ ] **ZPur Reg** — wide PO→GRN→Invoice register that can fan out into duplicate rows on multiple matches; shares the GL-name-matching fragility of RM GRN Report
- ⚑ **Non Vaulted Closing Stock and Stock Report are non-functional** — see Critical Blockers above; do not present these to end users as working reports until fixed

### 8.5 Print Formats
- [ ] **Custom SI e-Invoice** (Sales Invoice) — 4-copy layout with QR/IRN from india_compliance's e-Invoice Log, HSN/GST breakup, PO date from linked Sales Order, delivery challan date from Delivery Note — confirm e-Invoice is generated **before** printing, or the IRN/QR section renders blank with no error
- [ ] **Sub Vendor Challan Return** (Subcontracting Receipt) — reviewed and approved by the store/subcontracting team
- [ ] Company logo, GSTIN, address, bank details, and terms text on every print format double-checked — these are customer/vendor-facing, so a factual error here is externally visible
- [ ] HR-related formats (Offer Letter, Appointment Letter) confirmed out of scope for manufacturing go-live, or reviewed if HR is also going live simultaneously

---

## 9. Environment & Infrastructure

- [ ] Latest app code migrated on the production site (`bench --site [sitename] migrate`); confirm `after_migrate` custom-field patches ran without error
- [ ] Scheduler enabled on the production bench (required for the per-minute workstation status sync and hourly reorder job)
- [ ] Outgoing email (SMTP) configured and tested (Section 4 depends entirely on this)
- [ ] Backups scheduled, and a restore has actually been tested once
- [ ] All users created with correct roles, real email addresses, and default passwords reset
- [ ] Opening stock, opening balances, and any migrated historical data reconciled and signed off before the old system is switched off

---

## Sign-off

Once every section above is checked and tested with real data, the following should sign off before the old system is switched off:

| Area | Signed off by | Date |
|---|---|---|
| Production / Planning | | |
| Store & Purchase | | |
| Sales & Accounts | | |
| IT / Implementation | | |
