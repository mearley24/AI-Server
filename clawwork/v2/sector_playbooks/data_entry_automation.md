# Data Entry & Automation — Sector Playbook

**Tier:** 3 (Volume Fill)  
**Avg Task Value:** $10–80  
**Target Platforms:** Upwork, Fiverr, Amazon Mechanical Turk (AMT)  
**Bob's Role:** High-speed automated processing engine  

---

## Sector Overview

Data entry and automation is the workhorse sector. Tasks are low-complexity, high-volume, and fast to complete. This is not where Bob earns his biggest paydays — but it is where he:
- Builds early platform review velocity
- Fills idle minutes between high-value tasks
- Generates consistent, predictable micro-revenue
- Practices throughput and quality control systems

**Target:** Never more than 10% of total ClawWork hours in this sector. More than that is opportunity cost.

---

## Task Type Breakdown

### 1. PDF Extraction and Restructuring
**What it looks like:**
- "Extract all line items from these 50 PDF invoices into a spreadsheet"
- "Convert this scanned menu into a formatted Excel file"
- "Pull the data from these 200 PDF reports into a CSV"

**Bob's approach:**
1. Use Python + pdfplumber/camelot for structured PDFs
2. Use OCR (pytesseract) for scanned documents
3. Output: clean CSV or XLSX with consistent column headers
4. Always validate row count matches source document count
5. Flag anomalies (missing data, parsing errors) in a separate "exceptions" tab

**Time estimate:** 3–8 minutes per 10-page PDF batch (automated)
**Quality checklist:**
- [ ] All rows present (count matches)
- [ ] No empty columns that should have data
- [ ] Consistent date format (YYYY-MM-DD)
- [ ] Currency values clean (no $ signs or commas in numeric columns)
- [ ] Exception tab included for any parsing failures

---

### 2. Spreadsheet Cleanup and Normalization
**What it looks like:**
- "This Excel file is a mess — clean it up and standardize the format"
- "Merge these 12 monthly CSV exports into one clean master file"
- "Remove duplicates, fix the date column, and add summary totals"

**Bob's approach:**
1. pandas for all data manipulation
2. Standard cleaning steps:
   - Normalize column names (lowercase, underscore-separated)
   - Parse and standardize dates
   - Strip whitespace from string fields
   - Remove exact duplicates
   - Flag near-duplicates for human review
   - Fill or flag missing values per column
3. Provide a "cleaning log" sheet documenting what changed

**Template script structure:**
```python
import pandas as pd

def clean_spreadsheet(input_path, output_path):
    df = pd.read_excel(input_path)
    log = []
    
    # 1. Column normalization
    original_cols = df.columns.tolist()
    df.columns = [c.lower().strip().replace(' ', '_') for c in df.columns]
    log.append(f"Normalized {len(df.columns)} column names")
    
    # 2. Duplicate removal
    n_before = len(df)
    df = df.drop_duplicates()
    log.append(f"Removed {n_before - len(df)} duplicate rows")
    
    # 3. Date standardization (detect and parse date columns)
    for col in df.columns:
        if 'date' in col or 'time' in col:
            df[col] = pd.to_datetime(df[col], errors='coerce')
    
    # 4. Whitespace cleanup
    str_cols = df.select_dtypes(include='object').columns
    df[str_cols] = df[str_cols].apply(lambda x: x.str.strip())
    
    # 5. Export
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Clean Data', index=False)
        pd.DataFrame({'Change': log}).to_excel(writer, sheet_name='Cleaning Log', index=False)
    
    return log
```

**Time estimate:** 5–15 minutes depending on dataset size
**Rate target:** $20–60 per file

---

### 3. Web Research and Data Collection
**What it looks like:**
- "Collect the contact info for 100 companies in this list"
- "Find the LinkedIn profile URL for each person on this spreadsheet"
- "Get the current pricing for each product on this list"

**Bob's approach:**
1. Treat this as structured web research, not manual lookup
2. Use the ClawWork web_search tool (max 5 searches per task)
3. Batch similar queries to maximize information per search
4. Output: CSV with a "confidence" column (high/medium/low/not found)
5. Never fabricate data — "not found" is always preferable to invented data

**Rate target:** $0.50–2.00 per record researched
**Quality requirement:** 100% accuracy on found records; honest about not-found

---

### 4. Data Classification and Labeling
**What it looks like:**
- "Categorize each of these 500 customer comments as positive/neutral/negative"
- "Tag each of these product descriptions with the correct category from this list"
- "Classify these support tickets into one of 8 issue types"

**Bob's approach:**
1. Request the classification taxonomy upfront if not provided
2. Apply classification criteria consistently (build a decision tree for ambiguous cases)
3. Flag cases where the classification is genuinely uncertain (>20% ambiguity rate is a signal the taxonomy needs work — surface this)
4. Output: original data + new classification column + confidence column

**Time estimate:** 1–3 seconds per record with AI assist
**Rate target:** $0.05–0.25 per record labeled

---

## Platform-Specific Tactics

### Amazon Mechanical Turk
- Maintain ≥ 99% approval rate — this is everything on AMT
- Complete qualification tests before starting any HIT type
- Start with high-approval-rate requesters (use Turkopticon to vet)
- Batch HITs of the same type for efficiency
- Target $15+/hr effective rate; if a HIT type pays below $12/hr, skip it

### Fiverr
- Create a "Data Cleanup & Excel Formatting" gig — high search volume, low competition
- Price entry tier at $25 (small dataset), standard at $75 (medium), premium at $150 (large)
- Deliver a sample of cleaned data before asking for feedback — shows work quality immediately
- Upsell opportunity: "I can automate this process with a Python script for $X extra"

### Upwork
- Target "Data Entry" and "Data Processing" jobs
- In proposals, emphasize accuracy, delivery speed, and Python automation capability
- Show a portfolio example (anonymized cleaned spreadsheet)
- Minimum bid: $25 for any fixed-price project in this sector

---

## Quality Standards

| Check | Required |
|-------|----------|
| Row count validation | Always |
| No fabricated data | Always |
| Consistent date format | Always |
| Exceptions documented | When applicable |
| Column headers labeled | Always |
| No leading/trailing whitespace in string fields | Always |

---

## When to Decline

- Tasks requiring HIPAA-protected data handling (medical records)
- Tasks where the only input is an image with poor OCR quality (>20% error rate)
- Tasks requiring login to client systems (security risk)
- Any task where the instructions are unclear and clarification is blocked
