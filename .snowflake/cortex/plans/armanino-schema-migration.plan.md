# Plan: Armanino Source Schema Migration

## Problem
Armanino changed their source file format from a **wide format** (TY/LY/2024 columns for each metric) to a **tall/normalized format** (one row per transaction with single metric columns). The new file (`Armanino_SourceFile_06.04.2026.csv`) has these columns:

```
CUSTOMER ID, CUSTOMERNAME, ITEM, ITEM DESCRIPTION, PACK SIZE, 
CASE SALES, TOTAL LBS, $$ SALES, SHIP DATE YEAR, SHIP DATE MONTH, BROKER
```

The old format had 19 columns:
```
Distributor, ITEM, ITEM DESCRIPTION, Product Pack Size, SHIP DATE YEAR, Month,
Cases 2026, Cases 2025, Cases 2024, Pounds 2026, Pounds 2025, Pounds 2024,
Gross Sales 2026, Gross Sales 2025, Gross Sales 2024, Net Sales 2026, Net Sales 2025, Net Sales 2024, BROKER
```

## Constraints
- **231,905 rows** of old-format data exist in `TB_ARMANINO_SOURCE` (dates 2026-03-06 to 2026-05-13)
- **65,607 rows** exist in `TB_TRF_ARMANINO` (years 2024-2026)
- Old data must NOT be deleted or corrupted
- The scorecard view (`VW_ARMANINO_SCORECARD`) must continue working for both old and new data

## Approach

### Step 1: ALTER Source Table (add new columns, keep old ones)

```sql
ALTER TABLE DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_ARMANINO_SOURCE 
ADD COLUMN CUSTOMER_ID VARCHAR(16777216),
           CUSTOMERNAME VARCHAR(16777216),
           CASE_SALES VARCHAR(16777216),
           TOTAL_LBS VARCHAR(16777216),
           DOLLAR_SALES VARCHAR(16777216),
           SHIP_DATE_MONTH VARCHAR(16777216);
```

Old rows: new columns will be NULL.  
New rows: old wide-format columns (`CASES_TY`, `CASES_LY`, etc.) will be NULL since the ingestion proc reads CSV headers dynamically.

**Note**: The ingestion procedure (`P_DATA_INGESTION`) uses `pd.read_csv` which creates columns based on the CSV header. Since it does `save_as_table` with mode "append", Snowflake will match by column name. New columns present in the CSV but not in the table will fail — so we must add them first. Old columns not present in the new CSV will simply get NULLs.

**Important**: The CSV header uses spaces and special chars (`CUSTOMER ID`, `$$ SALES`). The ingestion proc reads them as-is from the CSV header. We need to match exactly what pandas will produce from the header names:
- `CUSTOMER ID` → column `CUSTOMER_ID` (pandas replaces spaces with underscores? Actually no — Snowpark `create_dataframe` preserves pandas column names as-is, and Snowflake uppercases them)

Let me check: the ingestion proc does `df = pd.read_csv(...)` then `df1 = session.create_dataframe(df)` then `df1.write.mode("append").save_as_table(...)`. Snowpark will use the pandas column names as Snowflake column names (uppercased). So:
- `CUSTOMER ID` → `CUSTOMER ID` (with space)
- `CUSTOMERNAME` → `CUSTOMERNAME`
- `ITEM` → `ITEM` (same as old `ITEM` which maps to `ITEM_CODE`... wait)

Actually looking at the old source table, the column is `ITEM_CODE` not `ITEM`. The old CSV header says `ITEM` but the table has `ITEM_CODE`. This means the ingestion either renames columns OR the table was manually created to match the CSV exactly.

Looking at the old CSV: `Distributor,ITEM,ITEM DESCRIPTION,Product Pack Size,SHIP DATE YEAR,Month,...`
And the table columns: `DISTRIBUTOR, ITEM_CODE, ITEM_DESCRIPTION, PRODUCT_PACK_SIZE_SIZE_UOM, YEAR, MONTH,...`

These DON'T match directly — the table was pre-created with custom column names. So the ingestion must be mapping by position, not by name, when doing `save_as_table` with append. Looking at the P_DATA_INGESTION code: it does NOT rename columns explicitly for Armanino (only for INTEGRATED_FOOD_SERVICES and REDGOLD). So Snowpark `save_as_table` in append mode maps by **column position/order** when names don't match.

This means: For the new file, which has 11 columns, we need either:
1. A new target table for the new format, OR
2. Handle it so that the 11 columns map correctly

Given the ingestion framework appends by position, and the new file has a completely different column count (11 vs 19), the simplest safe approach is:

**Revised approach**: Create a **new source table** `TB_ARMANINO_SOURCE_V2` for the new format, update `TB_CONFIG_API_DETAILS` to point to it, and update the TRF procedure to UNION from both source tables.

Actually wait — looking more carefully at the ingestion proc, for clients other than INTEGRATED_FOOD_SERVICES and REDGOLD, it does:
```python
df1 = session.create_dataframe(df)
df1.write.mode("append").save_as_table(f"{raw_db}.{tgt_tb}")
```

Snowpark's `save_as_table` in append mode uses **column names** from the DataFrame to match to the target table. If the DataFrame has columns not in the table, it would error. If the table has columns not in the DataFrame, those get NULL.

So the mapping is by NAME (uppercase). The old CSV headers become: `DISTRIBUTOR`, `ITEM`, `ITEM DESCRIPTION`, `PRODUCT PACK SIZE`, `SHIP DATE YEAR`, `MONTH`, `CASES 2026`, etc.

But the table has: `DISTRIBUTOR`, `ITEM_CODE`, `ITEM_DESCRIPTION`, `PRODUCT_PACK_SIZE_SIZE_UOM`, `YEAR`, `MONTH`...

These DON'T match (e.g. `ITEM` vs `ITEM_CODE`). So Snowpark must be using positional mapping or the table was created FROM the DataFrame initially (CTAS), and it keeps the original column names with spaces. Let me re-check the DESCRIBE output...

The DESCRIBE shows: `ITEM_CODE`, `ITEM_DESCRIPTION`, `PRODUCT_PACK_SIZE_SIZE_UOM`, `YEAR`, `MONTH`, `CASES_TY`, etc. — these have underscores. But the CSV headers have spaces. So either:
1. The table was manually created with these renamed columns
2. Or pandas automatically converts spaces to underscores (it doesn't)

Most likely: the table was created the FIRST time with `mode("overwrite")` (which creates from the DataFrame structure), and Snowflake automatically replaced special chars. Actually Snowpark `create_dataframe` from pandas preserves column names including spaces, but `save_as_table` with overwrite will create columns using those names. The columns would then have spaces.

But the DESCRIBE shows `ITEM_CODE` not `ITEM`. So the table DDL was manually created/altered at some point.

**Given this complexity**, the safest approach is:

### Revised Strategy: New Source Table + Dual-Source TRF Proc

1. **Create `TB_ARMANINO_SOURCE_V2`** with columns matching the new CSV header exactly
2. **Add a new row in `TB_CONFIG_API_DETAILS`** pointing to the new table (or update existing)
3. **Update `P_TRF_ARMANINO`** to read from BOTH source tables and produce the same TRF output
4. **Deactivate** the old config row (set `IS_ACTIVE = 'false'`) so old files aren't re-processed

### Step 1: Create new source table

```sql
CREATE TABLE DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_ARMANINO_SOURCE_V2 (
    CUSTOMER_ID VARCHAR(16777216),
    CUSTOMERNAME VARCHAR(16777216),
    ITEM VARCHAR(16777216),
    ITEM_DESCRIPTION VARCHAR(16777216),
    PACK_SIZE VARCHAR(16777216),
    CASE_SALES VARCHAR(16777216),
    TOTAL_LBS VARCHAR(16777216),
    DOLLAR_SALES VARCHAR(16777216),
    SHIP_DATE_YEAR VARCHAR(16777216),
    SHIP_DATE_MONTH VARCHAR(16777216),
    BROKER VARCHAR(16777216),
    FILE_DATE TIMESTAMP_NTZ(9),
    FILE_WEEK VARCHAR(2),
    FILE_MONTH NUMBER(38,0),
    FILE_YEAR NUMBER(38,0),
    BATCH_ID VARCHAR(36),
    INSERT_TIMESTAMP TIMESTAMP_TZ(9),
    FILE_NAME VARCHAR(100)
);
```

**Important**: Column names must match what Snowpark produces from the pandas DataFrame. The CSV header is: `CUSTOMER ID,CUSTOMERNAME,ITEM,ITEM DESCRIPTION,PACK SIZE,CASE SALES,TOTAL LBS,$$ SALES,SHIP DATE YEAR,SHIP DATE MONTH,BROKER`. After `pd.read_csv`, pandas columns will be exactly those strings. After `session.create_dataframe(df)`, Snowpark uppercases them. So Snowflake will see: `CUSTOMER ID`, `CUSTOMERNAME`, `ITEM`, `ITEM DESCRIPTION`, `PACK SIZE`, `CASE SALES`, `TOTAL LBS`, `$$ SALES`, `SHIP DATE YEAR`, `SHIP DATE MONTH`, `BROKER`.

These have SPACES and special chars (`$$`). Snowflake handles quoted identifiers. So the table must use quoted column names OR we rename in the ingestion. Since we can't modify P_DATA_INGESTION (it's a shared framework), the table column names must exactly match what Snowpark will produce.

Let me use quoted identifiers:

```sql
CREATE TABLE DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_ARMANINO_SOURCE_V2 (
    "CUSTOMER ID" VARCHAR(16777216),
    "CUSTOMERNAME" VARCHAR(16777216),
    "ITEM" VARCHAR(16777216),
    "ITEM DESCRIPTION" VARCHAR(16777216),
    "PACK SIZE" VARCHAR(16777216),
    "CASE SALES" VARCHAR(16777216),
    "TOTAL LBS" VARCHAR(16777216),
    "$$ SALES" VARCHAR(16777216),
    "SHIP DATE YEAR" VARCHAR(16777216),
    "SHIP DATE MONTH" VARCHAR(16777216),
    "BROKER" VARCHAR(16777216),
    "FILE_DATE" TIMESTAMP_NTZ(9),
    "FILE_WEEK" VARCHAR(2),
    "FILE_MONTH" NUMBER(38,0),
    "FILE_YEAR" NUMBER(38,0),
    "BATCH_ID" VARCHAR(36),
    "INSERT_TIMESTAMP" TIMESTAMP_TZ(9),
    "FILE_NAME" VARCHAR(100)
);
```

### Step 2: Update TB_CONFIG_API_DETAILS

- Update or insert a row for Armanino Source pointing `TGT_TABLE` to `TB_ARMANINO_SOURCE_V2`
- Mark old row as `IS_ACTIVE = 'false'` (old files are already archived)

### Step 3: Rewrite P_TRF_ARMANINO

The new procedure will:
1. Process old source table (`TB_ARMANINO_SOURCE`) as before for historical data
2. Process new source table (`TB_ARMANINO_SOURCE_V2`) with simplified logic:
   - `CUSTOMER ID` split into Distributor ID + Distributor Name  (or use `CUSTOMERNAME` as the customer)
   - `CASE SALES` → CASES
   - `TOTAL LBS` → LBS  
   - `$$ SALES` → GROSS_SALES (and NET_SALES = same, since no distinction)
   - `SHIP DATE YEAR` → DATA_YEAR
   - `SHIP DATE MONTH` → DATA_MONTH (already numeric)
3. Same delete-and-reload pattern per period
4. Same TRF output columns

### Step 4: Test Ingestion
- Call `P_DATA_INGESTION('PROD','ARMANINO')`
- Verify new file loads into `TB_ARMANINO_SOURCE_V2`

### Step 5: Test Transformation  
- Call `P_TRF_ARMANINO('PROD')`
- Verify TRF table has new rows

### Step 6: Validate Scorecard View
- Query `VW_ARMANINO_SCORECARD` for 2025 data (from new file) to confirm it works

### Step 7: Time Travel Safety
- Record timestamps before each DDL/DML change
- If failure: `SELECT * FROM TABLE AT(TIMESTAMP => '<pre_change>') `

## Risk Mitigation
- No existing data is dropped or altered
- Old source table stays intact with IS_ACTIVE='false' on its config row
- TRF proc handles both old and new format
- Time travel available for 14 days on all tables
