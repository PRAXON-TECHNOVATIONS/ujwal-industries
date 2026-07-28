# Item Cost Estimation — Detailed Plan

**App:** Ujwal Industries (ERPNext)
**Date:** 2026-07-04 (decisions locked 2026-07-09)
**Status:** Decisions locked — starting implementation with the new master doctypes

---

## 1. Goal

When a customer enquiry comes in, we want to **estimate what it truly costs us to make the enquired item** (example: `300918`) *before* we send a price — so the quoted price and our margin are decided on real cost, not a guess.

"True cost" = everything consumed to manufacture one piece:

- **Raw Material** used (minus the scrap value we get back)
- **Machine & Power** cost of the machines that run on it
- **Labour** cost of the people who work on it, split by role
- **Overheads** — indirect costs (admin, inspection, rejection, ICC, tool maintenance, etc.)

Everything about how the item is made already lives in ERPNext, connected through the item's **BOM**. The BOM knows the raw materials, the operations, the machines (Workstations), and the run time. So the BOM is the backbone of the estimate; we layer role-labour and overheads on top of it.

### 1.1 The business flow (where costing sits)

This follows the standard sales funnel — costing is done at the **Opportunity** stage, not directly on the Quotation:

```
Lead  →  Opportunity  →  [button: Create Cost Estimation]  →  Cost Estimation  →  Quotation
                              │                                     │                  │
                     dialog: pick which item(s)          RM+Machine+Labour+     quoted price built on
                     from the opportunity                Overhead breakdown     the estimated cost
```

1. A **Lead** comes in and is converted to an **Opportunity** (standard ERPNext).
2. The Opportunity lists the enquired item(s) in its **Items** table.
3. On the Opportunity, a **"Create Cost Estimation" button** opens a **dialog** to pick which item (from the opportunity's items) we want to cost.
4. That creates a **Cost Estimation** record for the chosen item — pre-filled with the item, its default BOM, and the enquired quantity — and produces the full RM + Machine + Labour + Overhead breakdown.
5. From the estimated cost, a **Quotation** is raised — the quoted price is built on top of the estimated cost (with the margin visible).

---

## 2. Guiding principle

> **Use ERPNext defaults for everything possible. Create something new only where ERPNext has no native home for the number.**

Applying this, the cost breaks into two groups:

- **Already in ERPNext (we only read it):** Raw Material cost, Scrap recovery, Machine & Power cost.
- **Genuinely new (small additions):** role-wise Labour rates, Overhead rules, and the one record that ties everything together and feeds the Quotation.

---

## 3. What the real data says today (baseline for item 300918)

Before building anything, here is what already exists for `300918`, so the plan is grounded:

- Default BOM is **`BOM-300918-001`**, made for a batch **quantity of 100**.
- **Raw Material Cost = ₹7,90,000** for 100 pcs → **₹7,900 raw material per piece**. *(This is already calculated by ERPNext — we just read it.)*
- **Operating (machine) cost = ₹0** right now — because the BOM operations don't yet have workstation hour-rates / times filled in. So machine cost is *available by default* but currently **empty** until operations are costed.
- **Scrap = ₹0** — no scrap recovery entered yet.
- The system has **42 Designations**, but they are office roles (Accountant, Analyst…). **None of the shop-floor roles** (Operator Skilled, Semi-Skilled, Helper, Die Setter, QC Inspector, Assembly, Packing) exist yet — these must be created.
- There is **one company** (Ujwal Industries) and **no "Additional Charges" doctype** — so overheads will reference the standard **Account** ledger, and rate lists can be single-company (shared).

**Implication:** the estimate for `300918` will initially be mostly Raw Material until (a) BOM operations get workstation rates/times and (b) role-labour and overheads are set up. That is expected and correct — the framework reads whatever is filled in.

---

## 4. The cost model — piece by piece

### 4.1 Raw Material — **Default (read only)**

- The BOM lists every raw material, its quantity, and its rate. ERPNext already totals this into **Raw Material Cost** on the BOM.
- Scrap recovery lives on the BOM's **Scrap Items** table; ERPNext already subtracts its value.
- **Net RM cost = BOM Raw Material Cost − BOM Scrap value.**
- We do nothing new — we read these two numbers.
- *For 300918:* Net RM = 7,90,000 − 0 = **₹7,90,000 for 100 pcs (₹7,900/pc).**

**Fields read (all Default):**

| Field read | Doctype (source) | Fieldname | Type | Kind |
|---|---|---|---|---|
| Raw material total | BOM | `raw_material_cost` | Currency | **Default** |
| Scrap recovery total | BOM | `scrap_material_cost` | Currency | **Default** |
| BOM batch qty | BOM | `quantity` | Float | **Default** |
| Each RM line item | BOM Item | `item_code` | Link | **Default** |
| RM line qty | BOM Item | `qty` / `stock_qty` | Float | **Default** |
| RM line rate | BOM Item | `rate` | Currency | **Default** |
| RM line amount | BOM Item | `amount` | Currency | **Default** |
| Scrap line item | BOM Scrap Item | `item_code` | Link | **Default** |
| Scrap line amount | BOM Scrap Item | `amount` | Currency | **Default** |

**Written to (RM child of the estimation record — New):** `item_code`, `qty`, `rate`, `amount`, plus header totals `total_rm_cost`, `scrap_recovery`, `net_rm_cost`. *(All new fields on the new Cost Estimation doctype.)*

### 4.2 Machine & Power — **Default (read only)**

- In ERPNext the machine cost comes from the **Workstation**, not Asset Category. Each Workstation carries an hourly rate already split into **electricity + consumables + rent + wages**.
- Each BOM operation says which Workstation runs and for how long (operation time in minutes).
- Machine cost of an operation = (operation minutes ÷ 60) × Workstation hourly rate. ERPNext already sums these into **Operating Cost** on the BOM.
- We read the BOM's operating cost.
- *(The costing sheet mapped this to "Asset Category", but Workstation is the correct ERPNext home. Each Workstation here is already linked to its Asset, so nothing is lost.)*
- *For 300918:* currently ₹0 until operation rates/times are entered.

**Fields read (all Default):**

| Field read | Doctype (source) | Fieldname | Type | Kind |
|---|---|---|---|---|
| Operating cost total | BOM | `operating_cost` | Currency | **Default** |
| Operation name | BOM Operation | `operation` | Link | **Default** |
| Which machine | BOM Operation | `workstation` | Link | **Default** |
| Machine hourly rate | BOM Operation | `hour_rate` | Currency | **Default** |
| Operation time (mins) | BOM Operation | `time_in_mins` | Float | **Default** |
| Per-operation cost | BOM Operation | `operating_cost` | Currency | **Default** |
| Machine link to asset | Workstation | `custom_asset_name` | Link | Custom *(already exists in this app)* |
| Rate components (elec/consumable/rent/wages) | Workstation | `hour_rate_electricity`, `hour_rate_consumable`, `hour_rate_rent`, `hour_rate_labour`, `hour_rate` | Currency | **Default** |

**Written to (Machine child of the estimation record — New):** `operation`, `workstation`, `time_in_mins`, `hour_rate`, `machine_cost`, plus header total `total_machine_cost`.

### 4.3 Labour by role — **New (small)**

This is the one thing ERPNext does not do the way the costing sheet needs. Native ERPNext folds labour into a single blended "wages" figure inside the machine rate — it cannot separate *Operator Skilled vs Helper vs Die Setter*. The sheet clearly wants labour itemised by role.

**Two small additions make this work:**

**(a) A role rate list ("Designation Cost Rate").** One line per shop-floor role saying what **one hour of that role costs us**. Each line holds:
- the **role** (Designation),
- the **hourly rate** (a standard/planning rate — deliberately *not* pulled from real salaries, so quotes don't shift every time someone gets an increment),
- an **effective-from date** (so we can revise rates over time without losing history),
- an **active** flag.

When a cost is calculated, we use the **latest active rate on/before the estimation date**.

Roles to create (from the sheet): Operator Skilled, Operator Semi-Skilled, Helper, Die Setter, Quality Inspector, Assembly Labour, Packing Labour, Welding, Tapping, Operational. (These are new Designations.)

**(b) Role-hours on each BOM operation.** On each operation we record *which roles work on it and for how many hours* per BOM batch, plus an optional head-count (how many people of that role). For each such line:
> **Labour cost = labour hours × head count × role hourly rate.**

Summed across all operations, this is the total labour block — matching the "Labour Cost" section of the sheet.

**Fields — role rate list (New master: "Designation Cost Rate"):**

| Field | Fieldname | Type | Kind | Notes |
|---|---|---|---|---|
| Role | `designation` | Link → Designation | Default target, **New usage** | Points at the Designation master (existing doctype) |
| Hourly rate | `hourly_rate` | Currency | **New** | The standard cost per hour |
| Effective from | `effective_from` | Date | **New** | Latest ≤ estimation date wins |
| Active | `is_active` | Check | **New** | Only active rows used |
| Company | `company` | Link → Company | **New** | Single company today |

**Fields — role-hours on the operation (New custom child on BOM Operation: `custom_labour_details`):**

| Field | Fieldname | Type | Kind | Read/Written |
|---|---|---|---|---|
| Role | `designation` | Link → Designation | **New** | Entered by user on BOM |
| Labour hours | `labour_hours` | Float | **New** | Entered by user |
| Head count | `head_count` | Int | **New** | Entered (default 1) |
| Hourly rate | `hourly_rate` | Currency | **New** | Fetched from Designation Cost Rate |
| Labour cost | `labour_cost` | Currency | **New** | Computed `hours × head × rate` |

Also read from the operation itself: **`operation`** (BOM Operation `operation`, Default) to label each labour line.

**Written to (Labour child of the estimation record — New):** `operation`, `designation`, `labour_hours`, `head_count`, `hourly_rate`, `labour_cost`, plus header total `total_labour_cost`.

*Worked example (illustrative) for one operation on 300918's batch of 100:*
- Die Setter: 2 hrs × 1 person × ₹250/hr = ₹500
- Operator Skilled: 8 hrs × 1 × ₹180/hr = ₹1,440
- Helper: 8 hrs × 2 × ₹120/hr = ₹1,920
- Operation labour = **₹3,860 for the batch** → **₹38.60/pc**

### 4.4 Overheads (indirect costs) — **New (small)**

Costs like Indirect Material, Inspection Machinery, Indirect Equipment, Admin & Other, ICC, Rejection Charges, and Tool Maintenance have no native per-item home. We add a small **overhead rule list**. Each overhead line says:
- a **name** (e.g. "Rejection Charges"),
- the **ledger Account** it maps to (standard ERPNext Account, since there is no Additional Charges doctype),
- **how it is applied** — one of:
  - **% of Raw Material cost** (e.g. rejection scales with material value),
  - **% of Total Cost so far** (RM + Machine + Labour — e.g. admin overhead),
  - **flat amount per piece** (e.g. a fixed inspection charge),
- the **rate/percentage**, an **active** flag, and an **effective-from date**.

We maintain this list once and reuse it for every item.

> **Base-ordering rule (important):** "% of Total Cost" is always computed on **RM + Machine + Labour only** — *before* any overhead is added. This prevents overhead-being-charged-on-overhead. All overhead lines are calculated off the same pre-overhead subtotal, then added together.

**Fields — overhead rule list (New master: "Overhead Charge Rate"):**

| Field | Fieldname | Type | Kind | Notes |
|---|---|---|---|---|
| Charge name | `charge_name` | Data | **New** | e.g. "Rejection Charges", "ICC" |
| Ledger account | `account_head` | Link → Account | Default target, **New usage** | Standard ERPNext Account (no Additional Charges doctype exists) |
| Basis | `basis` | Select | **New** | `% of RM Cost` / `% of Total Cost` / `Flat per Unit` |
| Rate / % | `rate` | Float | **New** | Percentage or ₹-per-piece per basis |
| Active | `is_active` | Check | **New** | Only active rows applied |
| Effective from | `effective_from` | Date | **New** | |
| Company | `company` | Link → Company | **New** | |

**Written to (Overhead child of the estimation record — New):** `charge_name`, `basis`, `rate`, `applied_amount`, plus header total `total_overhead_cost`.

*Worked example (illustrative) on a batch subtotal of, say, ₹8,20,000:*
- Rejection Charges = 2% of RM (₹7,90,000) = ₹15,800
- Admin & Other = 3% of subtotal (₹8,20,000) = ₹24,600
- Inspection (flat) = ₹5/pc × 100 = ₹500
- Total overhead = **₹40,900**

### 4.5 Outsourcing / Job Work / Plating / Transportation

The sheet lists these under Labour, but they are really **bought-in services**, not our own labour hours. **Recommendation: treat them as overhead lines** (flat per piece, or % of cost). This is cleaner than pretending they are in-house labour hours. *(Confirm in §8.)*

---

## 5. Trigger — the button on Opportunity

The Cost Estimation is **started from the Opportunity**, not created blank.

**The button:** a **"Create Cost Estimation"** button is added to the Opportunity form.

**The dialog:** clicking it opens a dialog that lists the item(s) already on the Opportunity (from its **Items** table) and asks **which item to estimate** (and the qty defaults to the enquired qty). One estimation is made per selected item.

**What the dialog reads (all Default fields on Opportunity):**

| Field read | Doctype (source) | Fieldname | Type | Kind |
|---|---|---|---|---|
| The opportunity | Opportunity | `name` | — | **Default** |
| Party / customer | Opportunity | `party_name`, `customer_name` | Dynamic Link / Data | **Default** |
| Company | Opportunity | `company` | Link | **Default** |
| Currency | Opportunity | `currency` | Link | **Default** |
| Enquired items (choices in dialog) | Opportunity Item | `item_code` | Link | **Default** |
| Enquired qty (default qty) | Opportunity Item | `qty` | Float | **Default** |
| Enquired item name | Opportunity Item | `item_name` | Data | **Default** |

**What it writes:** a new **Cost Estimation** record with `opportunity`, `item`, `qty`, `company`, `currency` pre-filled (see header fields in §6), then the four cost blocks are computed. A link back is kept so the Opportunity can show its estimations.

*(New custom field on Opportunity is optional — e.g. a read-only count/link of estimations created. The button and dialog are the main additions; no change to standard Opportunity data.)*

---

## 6. How one estimate is assembled (step by step)

For the item chosen in the dialog:

1. **Item + BOM come from the Opportunity dialog.** The item picked in the dialog carries its enquired quantity; its default BOM is picked automatically (for 300918 → `BOM-300918-001`). We also set the **estimation date** (which drives all rate lookups).
2. **Raw Material (net):** read BOM raw material cost, subtract BOM scrap value. → *Default*
3. **Machine & Power:** read BOM operating cost (workstation rate × time). → *Default*
4. **Labour:** for every operation, sum (role hours × head count × role rate) using rates effective on the estimation date. → *New*
5. **Subtotal = RM(net) + Machine + Labour.** This is the base for percentage overheads.
6. **Overheads:** apply each active overhead rule to its base (RM, subtotal, or per-piece flat) and add them up. → *New*
7. **Total estimated cost = Subtotal + Overheads.**
8. **Cost per piece = Total ÷ quantity.**

All of this is saved as **one Cost Estimation record** for the item, showing each block (RM, Machine, Labour, Overhead) and the grand total. Because it is a saved snapshot, **old quotes keep their original cost even if rates change later** — we get an audit trail of what we assumed when we quoted.

**Refresh:** a button re-pulls all four blocks live from the BOM and the current rate lists, so we can re-cost an item on demand as rates or the BOM change.

**Header fields of the Cost Estimation record (New doctype):**

| Field | Fieldname | Type | Kind | Filled by |
|---|---|---|---|---|
| Source opportunity | `opportunity` | Link → Opportunity | **New** | Auto — set by the button that created it |
| Item | `item` | Link → Item | **New** | Auto — chosen in the dialog (from opportunity items) |
| BOM | `bom` | Link → BOM | **New** | Auto — default BOM of the item |
| Quantity | `qty` | Float | **New** | Auto — enquired qty from Opportunity Item (editable) |
| Estimation date | `estimation_date` | Date | **New** | Drives all rate lookups |
| Valid till | `valid_till` | Date | **New** | User |
| Company | `company` | Link → Company | **New** | Auto — from Opportunity `company` |
| Currency | `currency` | Link → Currency | **New** | From BOM `currency` |
| Net RM cost | `net_rm_cost` | Currency | **New** | Computed |
| Total machine cost | `total_machine_cost` | Currency | **New** | Computed |
| Total labour cost | `total_labour_cost` | Currency | **New** | Computed |
| Total overhead cost | `total_overhead_cost` | Currency | **New** | Computed |
| Total estimated cost | `total_estimated_cost` | Currency | **New** | Computed |
| Cost per piece | `cost_per_unit` | Currency | **New** | Computed = total ÷ qty |

Fields read to auto-fill the header (all **Default** on their source): from **Opportunity** → `company`, `currency`, and the picked **Opportunity Item** `item_code` + `qty`; from **Item** → its default BOM (BOM where `is_default=1`); from **BOM** → `quantity` / `currency`.

---

## 7. From Cost Estimation to the Quotation

Once the estimation is done, the **Quotation is raised on top of it**. Two ways it can flow, both supported:

- **From the estimation:** a **"Create Quotation"** button on the Cost Estimation carries the item, qty, party (from the linked Opportunity) and the **estimated cost** straight into a new Quotation — so the quoted price starts from a known cost.
- **On the Quotation itself:** each item row can also pull the **latest submitted Cost Estimation** for that item, so the estimated cost and margin show even for quotations made independently.

Either way, the Quotation shows, next to the price we are quoting: the **estimated cost per piece** and the resulting **margin %** = (quoted price − estimated cost) ÷ quoted price. This is **informational** — it does not block or overwrite the price we type; it just shows whether the price covers cost.

**Fields on Quotation Item:**

| Field | Fieldname | Type | Kind | Read / Written |
|---|---|---|---|---|
| Which item | `item_code` | Link → Item | **Default** | Read — triggers the lookup |
| Quoted qty | `qty` | Float | **Default** | Read |
| Quoted rate | `rate` | Currency | **Default** | Read — for margin |
| Linked estimation | `custom_item_cost_estimation` | Link → Item Cost Estimation | **New (custom)** | Auto: latest submitted estimation for the item |
| Estimated cost/pc | `custom_estimated_cost` | Currency | **New (custom)** | Fetched from estimation `cost_per_unit` |
| Estimated margin % | `custom_estimated_margin_pct` | Percent | **New (custom)** | Computed `(rate − est cost) ÷ rate × 100` |

Lookup: on setting `item_code` (or when created from the estimation button), find the latest **submitted** Item Cost Estimation for that item + company and pull its `cost_per_unit` into `custom_estimated_cost`; recompute the margin whenever `rate` or `custom_estimated_cost` changes.

*(Standard ERPNext already lets a Quotation be created from an Opportunity — the estimation link rides along, so the "Opportunity → Quotation" path also carries the cost.)*

---

## 8. Summary — Default vs New

| Piece | Where it comes from | Build |
|---|---|---|
| Lead → Opportunity | Standard ERPNext CRM flow | **Default** |
| "Create Cost Estimation" button + item-pick dialog on Opportunity | Reads Opportunity Items; creates estimation | **New (small)** |
| Raw Material (gross) | BOM raw material cost | **Default** |
| Less: Scrap Recovery | BOM scrap items | **Default** |
| Machine & Power (Blanking, Deburring, Tapping…) | Workstation hourly rate × BOM operation time | **Default** |
| Labour by role (Operator, Helper, Die Setter, QC…) | New role rate list + role-hours on BOM operations | **New (small)** |
| Overheads (Admin, ICC, Rejection, Inspection, Tool Maintenance…) | New overhead rule list (% or flat) | **New (small)** |
| Outsourcing / Job Work / Plating / Transport | Overhead rule list (bought-in service) | **New (small)** |
| The Cost Estimation record | New record that ties all blocks together | **New** |
| Estimation → Quotation (with cost & margin) | Button on estimation + fetch on Quotation Item | **New (small)** |

**Bottom line:** Raw Material and Machine cost are 100% ERPNext default — we only read them. The genuinely new pieces are (1) the **button/dialog on Opportunity** that starts an estimation for a chosen enquired item, (2) a role-wise labour rate list + role-hours on operations, (3) an overhead rule list, and (4) the one Cost Estimation record that assembles everything and hands off to the Quotation.

---

## 9. What has to be set up before the first real estimate

1. **Create shop-floor Designations** (Operator Skilled, Semi-Skilled, Helper, Die Setter, Quality Inspector, Assembly, Packing, Welding, Tapping…) — they don't exist yet.
2. **Fill the role rate list** with an hourly rate per role.
3. **Fill the overhead rule list** with the 6–11 overhead lines and their %/flat basis and accounts.
4. **Cost the BOM operations** — give each BOM operation a Workstation with an hourly rate and an operation time, so Machine cost stops being ₹0.
5. **Add role-hours** to each BOM operation (which roles, how many hours, head count).

Once these are in place, generating a Cost Estimation for `300918` (or any item) produces a full RM + Machine + Labour + Overhead breakdown automatically.

---

## 10. Open questions before we build

1. **Where is a Cost Estimation created?** ✅ **Decided:** from a **"Create Cost Estimation" button on the Opportunity**, with a dialog to pick the enquired item. *(Manual creation can still be allowed as a fallback.)*
2. **Multiple items on one Opportunity?** ✅ **Decided:** one Cost Estimation **per item** — clean per-item costing, each with its own BOM/RM/Machine/Labour/Overhead breakdown.
3. **Rate lists per company or shared?** ✅ **Decided: per company.** Ujwal Industries is one of **3 companies under the Ivision Group**, not a standalone company — so the `company` field stays on both **Designation Cost Rate** and **Overhead Charge Rate**, and rate lookups always filter by the Cost Estimation's `company`.
4. **Outsourcing / Job Work / Plating / Transport?** ✅ **Decided:** treated as **overhead service charges** (Overhead Charge Rate lines), not forced into labour.
5. **Standard labour hours** — do you already have standard hours-per-role-per-operation for `300918` so we can validate the numbers against a known costing? *(Still open — needed to sanity-check real numbers once labour setup exists.)*
6. **Machine cost?** ✅ **Decided: no fallback.** Machine cost stays ₹0 until Workstation hourly rates and BOM operation times are actually filled in; this keeps the number honest and matches ERPNext's native behavior.
