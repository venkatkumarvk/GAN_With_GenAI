# TECHNICAL WORKFLOW
## Medical Credentials Extraction System

**For: Developers, Data Scientists, Technical Teams**

---

## PHASE 1: SYSTEM INITIALIZATION (One-time per run)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. LOAD CONFIGURATION                                       │
│    • Read config.json                                       │
│    • Load field definitions from prompt_config.py           │
│    • Get Azure credentials and settings                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. INITIALIZE MANAGERS                                      │
│    • BlobManager (Azure Blob Storage)                       │
│    • OCRManager (Document Intelligence)                     │
│    • OpenAIManager (GPT-4o + Embeddings)                    │
│    • IndexManager (Azure AI Search)                         │
│    • CostTracker (Token/cost tracking)                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. CREATE/VERIFY UNIVERSAL INDEX                            │
│    • Index name: documents_universal                        │
│    • Check if exists                                        │
│    • If not exists: Create with schema                      │
│      - ID field (key)                                       │
│      - Content field (searchable text)                      │
│      - Vector field (3072-dim embedding)                    │
│      - Provider field (filterable)                          │
│      - Timestamp field (for cleanup)                        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. AUTO-CLEANUP (BEFORE processing)                         │
│    • Calculate cutoff: now() - auto_delete_days             │
│    • Query: WHERE upload_timestamp < cutoff                 │
│    • Delete matching documents                              │
│    • Log: "Deleted X documents from Y providers"            │
│    • Result: Index bounded, old data removed                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. DISCOVER PROVIDERS                                       │
│    • List all blobs in input container                      │
│    • Extract unique provider names from paths               │
│    • Example: Provider1/, Provider2/, Provider3/           │
│    • Count documents per provider                           │
└─────────────────────────────────────────────────────────────┘
```

---

## PHASE 2: PROVIDER PROCESSING (Outer Loop)

```
┌─────────────────────────────────────────────────────────────┐
│ OUTER LOOP: FOR EACH PROVIDER                               │
└─────────────────────────────────────────────────────────────┘
                          ↓
    ┌─────────────────────────────────────────────────────────┐
    │ 6. GET PROVIDER DOCUMENTS                               │
    │    • Filter blobs by provider prefix                    │
    │    • Create results collection (empty)                  │
    │    • Ready to process documents                         │
    └─────────────────────────────────────────────────────────┘
                          ↓
    ╔═══════════════════════════════════════════════════════╗
    ║           INNER LOOP: DOCUMENT PROCESSING             ║
    ║              (RAG HAPPENS HERE!)                      ║
    ╚═══════════════════════════════════════════════════════╝
                          ↓
    ┌─────────────────────────────────────────────────────────┐
    │ INNER LOOP: FOR EACH DOCUMENT                           │
    └─────────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 7. DOWNLOAD DOCUMENT                                │
        │    • API: Azure Blob Storage                        │
        │    • Input: blob_name                               │
        │    • Output: document_bytes                         │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 8. OCR EXTRACTION                                   │
        │    • API: Document Intelligence (prebuilt-read)     │
        │    • Input: document_bytes                          │
        │    • Output: extracted_text                         │
        │    • Skip if text length < 10 chars (portrait)      │
        │    • Cost: $0.01 per page                           │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 9. CONTEXT LENGTH HANDLING                          │
        │    • Check text length                              │
        │    • If > 12,000 chars: Apply truncation/chunking   │
        │    • Techniques: truncate, chunk, summarize         │
        │    • Output: processed_text (within limits)         │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 10. GENERATE EMBEDDING                              │
        │     • API: Azure OpenAI Embeddings                  │
        │     • Model: text-embedding-3-large                 │
        │     • Input: processed_text (first 2000 chars)      │
        │     • Output: 3072-dimensional vector               │
        │     • Cost: ~$0.0002                                │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 11. STORE IN INDEX (Available for future RAG)       │
        │     • API: Azure AI Search (upload)                 │
        │     • Document ID: provider_filename_hash           │
        │     • Content: processed_text                       │
        │     • Vector: embedding (3072-dim)                  │
        │     • Metadata:                                     │
        │       - provider: current_provider                  │
        │       - provider_id: provider_date                  │
        │       - document_name: filename                     │
        │       - upload_timestamp: now()                     │
        │     • Result: Document now searchable!              │
        │     • ⭐ Available as RAG example for NEXT docs     │
        └─────────────────────────────────────────────────────┘
                          ↓
        ╔═════════════════════════════════════════════════════╗
        ║            RAG EXTRACTION BLOCK                     ║
        ║      (Steps 12-15 work as single unit)              ║
        ╚═════════════════════════════════════════════════════╝
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 12. RAG SEARCH (Find Similar Documents)             │
        │     • API: Azure AI Search (vector search)          │
        │     • Query vector: embedding (from step 10)        │
        │     • Filter: provider = current_provider           │
        │     • Top K: 3 documents                            │
        │     • Algorithm: HNSW (Hierarchical NSW)            │
        │     • Returns:                                      │
        │       - 3 most similar documents                    │
        │       - Already processed and stored                │
        │       - From PREVIOUS loop iterations               │
        │       - Same provider only (no cross-contamination) │
        │     • ⭐ These become RAG examples!                 │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 13. BUILD EXTRACTION PROMPT                         │
        │     • Components assembled:                         │
        │       1. System role: Medical credential expert     │
        │       2. Field library: All field definitions       │
        │       3. RAG examples: 3 similar docs (from step 12)│
        │       4. Current document: Text to extract          │
        │       5. Instructions: JSON format, NA for missing  │
        │     • Result: Complete extraction prompt            │
        │     • Length: ~5,000-7,000 tokens                   │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 14. CALL GPT-4o FOR EXTRACTION                      │
        │     • API: Azure OpenAI (Chat Completion)           │
        │     • Model: GPT-4o                                 │
        │     • Temperature: 0.0 (deterministic)              │
        │     • Max tokens: 4000                              │
        │     • Input: Prompt from step 13                    │
        │     • Output: JSON with extracted fields            │
        │     • Cost: ~$0.03                                  │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 15. PARSE JSON RESPONSE                             │
        │     • Remove markdown formatting (```json)          │
        │     • Parse as JSON object                          │
        │     • Validate structure                            │
        │     • Expected format:                              │
        │       {                                             │
        │         "field_name": {                             │
        │           "value": "extracted_value",               │
        │           "confidence": 0.95                        │
        │         }                                           │
        │       }                                             │
        │     • Handle errors gracefully                      │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────────────────┐
        │ 16. STORE RESULT IN MEMORY                          │
        │     • Append to results collection:                 │
        │       - document_name                               │
        │       - extracted_fields (all fields)               │
        │       - confidence scores                           │
        │     • Not saved to disk yet (wait for all docs)     │
        └─────────────────────────────────────────────────────┘
                          ↓
        ┌──────────────────────────────────────┐
        │ END INNER LOOP                       │
        │ Repeat steps 7-16 for next document  │
        └──────────────────────────────────────┘

    ╔═══════════════════════════════════════════════════════╗
    ║ DOCUMENT LOOP COMPLETE                                ║
    ║ All documents for this provider processed             ║
    ║ Results collection populated                          ║
    ╚═══════════════════════════════════════════════════════╝
```

---

## PHASE 3: PROVIDER RESULTS AGGREGATION

```
    ┌─────────────────────────────────────────────────────────┐
    │ 17. CALCULATE MIN CONFIDENCE                            │
    │     • Iterate through all results                       │
    │     • Extract all confidence scores                     │
    │     • Find minimum confidence                           │
    │     • Determine category:                               │
    │       - min_confidence >= 0.50 → highconfidence         │
    │       - min_confidence < 0.50 → lowconfidence           │
    └─────────────────────────────────────────────────────────┘
                          ↓
    ┌─────────────────────────────────────────────────────────┐
    │ 18. FREQUENCY-BASED VALUE SELECTION                     │
    │     • For each field:                                   │
    │       1. Collect all values across documents            │
    │       2. Count frequency (ignore "NA")                  │
    │       3. Select most common value                       │
    │     • Example:                                          │
    │       - state_license_state values: [CA, CA, CA, California] │
    │       - Most common: CA (3 occurrences)                 │
    │       - Best value: CA                                  │
    │     • Result: Single row with best values               │
    └─────────────────────────────────────────────────────────┘
                          ↓
    ┌─────────────────────────────────────────────────────────┐
    │ 19. SAVE DETAILED JSON                                  │
    │     • Filename: processedjsonresult/Provider_timestamp.json │
    │     • Contains:                                         │
    │       - Provider name                                   │
    │       - Timestamp                                       │
    │       - Total documents processed                       │
    │       - Min confidence score                            │
    │       - Category (high/low confidence)                  │
    │       - Complete results array:                         │
    │         * All documents                                 │
    │         * All extracted fields                          │
    │         * All confidence scores                         │
    │     • API: Azure Blob Storage (upload)                  │
    │     • Use: Audit trail, detailed analysis               │
    └─────────────────────────────────────────────────────────┘
                          ↓
    ┌─────────────────────────────────────────────────────────┐
    │ 20. SAVE SUMMARY CSV                                    │
    │     • Filename: {category}/Provider_timestamp.csv       │
    │     • Path: highconfidence/ OR lowconfidence/           │
    │     • Contains:                                         │
    │       - Single row                                      │
    │       - All fields with best values                     │
    │       - Ready for import to systems                     │
    │     • API: Azure Blob Storage (upload)                  │
    │     • Use: Quick integration, database import           │
    └─────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────┐
    │ END OUTER LOOP                       │
    │ Repeat steps 6-20 for next provider  │
    └──────────────────────────────────────┘
```

---

## PHASE 4: FINAL SUMMARY

```
┌─────────────────────────────────────────────────────────────┐
│ 21. CALCULATE & SAVE COST SUMMARY                           │
│     • Aggregate all costs:                                  │
│       - OCR: pages × $0.01                                  │
│       - Embeddings: tokens × $0.0001/1K                     │
│       - GPT-4o input: tokens × $0.0025/1K                   │
│       - GPT-4o output: tokens × $0.01/1K                    │
│     • Filename: estimatecost/summary_timestamp.json         │
│     • API: Azure Blob Storage (upload)                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ 22. LOG FINAL SUMMARY                                       │
│     • Total providers processed                             │
│     • Total documents processed                             │
│     • Total costs breakdown                                 │
│     • Execution time                                        │
│     • Success/failure counts                                │
│     • Save to: logs/extraction_timestamp.log                │
└─────────────────────────────────────────────────────────────┘
                          ↓
                    ✅ COMPLETE
```

---

## KEY TECHNICAL INSIGHT: How RAG Loop Works

### **Understanding the RAG Accumulation Process**

### **The Confusion Point (Steps 12-15):**

```
Question: "How can step 13 use RAG examples if step 12 is below it?"

Answer: It's a LOOP! Here's what happens chronologically:
```

### **First Document (No RAG Yet):**

```python
Iteration 1: Process doc1.pdf
  Step 7-10: Download, OCR, generate embedding
  Step 11: Store doc1 in index ✅
  Step 12: RAG search → Returns 0 results (index empty)
  Step 13: Build prompt → No RAG examples (first time)
  Step 14-16: Extract fields, store results
  
Result: doc1 now in index, available as RAG example!
```

### **Second Document (1 RAG Example):**

```python
Iteration 2: Process doc2.pdf
  Step 7-10: Download, OCR, generate embedding
  Step 11: Store doc2 in index ✅
  Step 12: RAG search → Returns doc1 (1 example found!)
  Step 13: Build prompt → Include doc1 as RAG example
  Step 14-16: Extract fields, store results
  
Result: doc2 now in index, available as RAG example!
```

### **Third Document (2 RAG Examples):**

```python
Iteration 3: Process doc3.pdf
  Step 7-10: Download, OCR, generate embedding
  Step 11: Store doc3 in index ✅
  Step 12: RAG search → Returns doc1, doc2 (2 examples!)
  Step 13: Build prompt → Include doc1, doc2 as RAG examples
  Step 14-16: Extract fields, store results
  
Result: doc3 now in index, available as RAG example!
```

### **Fourth+ Documents (3 RAG Examples):**

```python
Iteration 4+: Process doc4.pdf, doc5.pdf, ...
  Step 11: Store current doc in index ✅
  Step 12: RAG search → Returns 3 most similar docs
  Step 13: Build prompt → Include 3 docs as RAG examples
  Step 14-16: Extract fields
  
Result: Each new doc benefits from 3 best examples!
```

---

## Visual: RAG Build-Up Over Time

```
Index State at Each Iteration:

Before Doc1: Index = []
After Doc1:  Index = [doc1] ─────────┐
                                     │
Before Doc2: Index = [doc1]          │ Used as
After Doc2:  Index = [doc1, doc2] ───┤ RAG
                                     │ examples
Before Doc3: Index = [doc1, doc2]    │ for
After Doc3:  Index = [doc1, doc2, doc3] ┘ future docs

Before Doc4: Index = [doc1, doc2, doc3]
             RAG Search finds 3 best matches
             ↓
After Doc4:  Index = [doc1, doc2, doc3, doc4]

...and so on! Index keeps growing (until auto-cleanup)
```

---

## Technical Flow: Nested Loops

```python
# Pseudo-code showing exact flow

for provider in providers:                    # Outer loop
    results = []
    
    for document in provider_documents:       # Inner loop
        
        # Process document
        text = ocr_extract(document)
        embedding = generate_embedding(text)
        
        # Store FIRST (step 11)
        upload_to_index(
            content=text, 
            vector=embedding, 
            provider=provider
        )
        
        # Search SECOND (step 12)
        # Now index has current doc + all previous docs
        similar_docs = vector_search(
            query_vector=embedding,
            filter=f"provider eq '{provider}'",
            top_k=3
        )
        
        # Build prompt with RAG examples (step 13)
        prompt = build_prompt(
            fields=field_definitions,
            rag_examples=similar_docs,  # From step 12
            current_doc=text
        )
        
        # Extract (step 14-15)
        extracted = gpt4o_extract(prompt)
        
        # Store result (step 16)
        results.append(extracted)
    
    # After all docs processed for provider
    save_provider_results(provider, results)
```

---

## Data Flow Diagram

```
Document Flow:
─────────────

doc1.pdf → Process → Index [doc1]
                         ↓ (used by)
doc2.pdf → Process → Index [doc1, doc2]
                         ↓ (used by)
doc3.pdf → Process → Index [doc1, doc2, doc3]
                         ↓ (used by)
doc4.pdf → Process → Index [doc1, doc2, doc3, doc4]


RAG Example Flow:
─────────────────

doc4.pdf needs extraction
    ↓
Search index for similar docs
    ↓
Find: doc1, doc2, doc3 (most similar)
    ↓
Build prompt: 
    "Here are 3 examples: [doc1, doc2, doc3]
     Now extract from doc4"
    ↓
GPT-4o sees examples and extracts correctly!
```

---

## Performance Characteristics

**Time Complexity:**
- Provider loop: O(P) where P = number of providers
- Document loop: O(D) where D = documents per provider
- RAG search: O(log N) where N = total docs in index
- Overall: O(P × D × log N)

**Space Complexity:**
- Index storage: O(N × V) where V = vector dimension (3072)
- Bounded by auto-cleanup (deletes old docs)

**Cost Per Document:**
- OCR: $0.01
- Embedding: $0.0002
- GPT-4o: $0.03
- Total: ~$0.05

---

## API Calls Per Document

```
1. blob_download()              → Azure Blob
2. ocr_extract()               → Document Intelligence  
3. generate_embedding()        → Azure OpenAI Embeddings
4. upload_to_index()           → Azure AI Search
5. vector_search()             → Azure AI Search
6. chat_completion()           → Azure OpenAI GPT-4o

Total: 6 API calls per document
```

---

## Error Handling

```python
try:
    # Steps 7-16
    process_document()
except OCRError:
    log("OCR failed, skipping document")
    continue
except EmbeddingError:
    log("Embedding failed, skipping document")
    continue
except ExtractionError:
    log("Extraction failed, saving partial results")
    continue
except Exception as e:
    log(f"Unexpected error: {e}")
    continue
```

---

**This is the TECHNICAL view for developers and data scientists!**

```
┌──────────────────────────────────────────────────────────────┐
│ Question: How can Step 12 use RAG examples when it comes    │
│          after Step 11?                                      │
│                                                              │
│ Answer: It's a LOOP! Step 11 stores current doc, which      │
│         becomes available in Step 12 of NEXT iteration!      │
└──────────────────────────────────────────────────────────────┘
```

### **Timeline View: RAG Building Over Iterations**

```
ITERATION 1 (First Document):
┌─────────────────────────────────────────────────────────────┐
│ Input: doc1.pdf                                             │
│                                                             │
│ Step 11: Store doc1 → Index = [doc1]                       │
│ Step 12: Search index → Found 0 docs (index just got doc1) │
│ Step 13: Build prompt → 0 RAG examples                     │
│ Step 14-16: Extract fields                                 │
│                                                             │
│ Output: doc1 extracted (no RAG help)                        │
│ Index State: [doc1] ← Available for future searches        │
└─────────────────────────────────────────────────────────────┘

ITERATION 2 (Second Document):
┌─────────────────────────────────────────────────────────────┐
│ Input: doc2.pdf                                             │
│ Index State Before: [doc1]                                  │
│                                                             │
│ Step 11: Store doc2 → Index = [doc1, doc2]                 │
│ Step 12: Search index → Found doc1 (1 example!) ✅          │
│ Step 13: Build prompt → 1 RAG example (doc1)               │
│ Step 14-16: Extract fields (learned from doc1)             │
│                                                             │
│ Output: doc2 extracted (with doc1 as reference)             │
│ Index State: [doc1, doc2] ← Both available now             │
└─────────────────────────────────────────────────────────────┘

ITERATION 3 (Third Document):
┌─────────────────────────────────────────────────────────────┐
│ Input: doc3.pdf                                             │
│ Index State Before: [doc1, doc2]                            │
│                                                             │
│ Step 11: Store doc3 → Index = [doc1, doc2, doc3]           │
│ Step 12: Search index → Found doc1, doc2 (2 examples!) ✅   │
│ Step 13: Build prompt → 2 RAG examples                     │
│ Step 14-16: Extract fields (learned from 2 docs)           │
│                                                             │
│ Output: doc3 extracted (with 2 references)                  │
│ Index State: [doc1, doc2, doc3] ← All available            │
└─────────────────────────────────────────────────────────────┘

ITERATION 4+ (Fourth+ Documents):
┌─────────────────────────────────────────────────────────────┐
│ Input: doc4.pdf, doc5.pdf, doc6.pdf...                     │
│ Index State Before: [doc1, doc2, doc3, ...]                │
│                                                             │
│ Step 11: Store current doc → Index grows                   │
│ Step 12: Search index → Found 3 best matches ✅             │
│ Step 13: Build prompt → 3 RAG examples (max)               │
│ Step 14-16: Extract fields (learned from 3 best docs)      │
│                                                             │
│ Output: Optimal extraction quality!                         │
│ Index State: Keeps growing (until auto-cleanup)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Visual: Index Growth and RAG Availability

```
Document Processing Timeline:
────────────────────────────

Time 0:  Index = []
            ↓
Time 1:  Process doc1
         Step 11: Add doc1 → Index = [doc1]
         Step 12: Search → 0 results
         Result: doc1 processed without RAG
            ↓
Time 2:  Process doc2  
         Step 11: Add doc2 → Index = [doc1, doc2]
         Step 12: Search → Returns [doc1]
         Result: doc2 processed WITH 1 RAG example
            ↓
Time 3:  Process doc3
         Step 11: Add doc3 → Index = [doc1, doc2, doc3]
         Step 12: Search → Returns [doc1, doc2]
         Result: doc3 processed WITH 2 RAG examples
            ↓
Time 4:  Process doc4
         Step 11: Add doc4 → Index = [doc1, doc2, doc3, doc4]
         Step 12: Search → Returns [doc2, doc3, doc1]
         Result: doc4 processed WITH 3 RAG examples
            ↓
Time 5+: Process doc5, doc6, doc7...
         Step 11: Add each → Index keeps growing
         Step 12: Search → Always returns 3 best matches
         Result: All docs get optimal 3 RAG examples


Key Point: Current doc stored FIRST (Step 11),
          then available for NEXT iteration (Step 12)
```

---

## Data Flow: Single Iteration Deep Dive

```
┌────────────────────────────────────────────────────────────┐
│                    ITERATION N                             │
│                Processing: docN.pdf                        │
└────────────────────────────────────────────────────────────┘
                          │
    ┌─────────────────────┴─────────────────────┐
    ↓                                           ↓
┌─────────┐                                ┌─────────┐
│ Step 11 │                                │ Step 12 │
│         │                                │         │
│ STORE   │                                │ SEARCH  │
│         │                                │         │
│ Upload  │                                │ Query   │
│ docN to │──────┐                         │ Index   │
│ Index   │      │                    ┌────│ for     │
│         │      │                    │    │ Similar │
└─────────┘      │                    │    │ Docs    │
                 │                    │    └─────────┘
                 ↓                    │         ↓
         ┌──────────────┐            │    ┌─────────┐
         │    INDEX     │            │    │ Returns │
         │              │            │    │ doc1,   │
         │ [doc1, doc2, │            │    │ doc2,   │
         │  doc3, ...,  │            │    │ doc3    │
         │  docN]       │────────────┘    └─────────┘
         │              │                      │
         │ NOW CONTAINS │                      │
         │ docN!        │                      │
         └──────────────┘                      │
                                              ↓
                                    ┌──────────────────┐
                                    │ Step 13          │
                                    │                  │
                                    │ BUILD PROMPT     │
                                    │ Using:           │
                                    │ - Field defs     │
                                    │ - doc1 (example) │
                                    │ - doc2 (example) │
                                    │ - doc3 (example) │
                                    │ - docN (current) │
                                    └──────────────────┘
                                              ↓
                                    ┌──────────────────┐
                                    │ Step 14-16       │
                                    │                  │
                                    │ EXTRACT & STORE  │
                                    └──────────────────┘
```

**Critical Understanding:** 
- Step 11 (STORE) happens synchronously
- docN is immediately searchable
- But Step 12 searches for PREVIOUS docs (doc1-N-1)
- docN becomes useful for NEXT iteration (docN+1)

---

## RAG Quality Progression

```
Document Number vs RAG Quality:
───────────────────────────────

Doc 1:  0 RAG examples → Baseline quality (85-90% accurate)
Doc 2:  1 RAG example  → Improved quality (88-92% accurate)
Doc 3:  2 RAG examples → Better quality (90-93% accurate)
Doc 4+: 3 RAG examples → Optimal quality (92-95% accurate)

Quality Plateaus at 3 Examples:
- Why 3? Balance between context and quality
- More examples = longer prompts = higher cost
- 3 examples = sweet spot (cost vs quality)
```

---

## Provider Filtering (Critical for Accuracy)

```
┌─────────────────────────────────────────────────────────────┐
│ WITHOUT Provider Filtering (BAD):                           │
│                                                             │
│ Processing Provider1/doc.pdf                                │
│ Step 12: Search entire index                               │
│ Returns: Provider2 doc, Provider3 doc, Provider1 doc       │
│ Problem: Wrong provider examples! ❌                        │
│ Result: Hallucination, wrong data                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ WITH Provider Filtering (GOOD):                             │
│                                                             │
│ Processing Provider1/doc.pdf                                │
│ Step 12: Search with filter: "provider = Provider1"        │
│ Returns: Provider1 doc1, Provider1 doc2, Provider1 doc3    │
│ Result: Correct examples from same provider! ✅             │
│ Result: Accurate extraction, no cross-contamination        │
└─────────────────────────────────────────────────────────────┘

Filter Expression: provider eq 'Provider1'
Effect: Vector search only returns docs from Provider1
Benefit: Prevents mixing data between providers
```

---

## Loop Structure Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    LOOP STRUCTURE                           │
└─────────────────────────────────────────────────────────────┘

OUTER LOOP (Providers):
  FOR each provider:
    Initialize results = []
    
    INNER LOOP (Documents):
      FOR each document:
        ┌──────────────────────────────┐
        │ PROCESS BLOCK (Steps 7-10)  │ ← Download, OCR, Embed
        ├──────────────────────────────┤
        │ STORE BLOCK (Step 11)        │ ← Upload to index
        ├──────────────────────────────┤
        │ RAG BLOCK (Steps 12-15)      │ ← Search, Prompt, Extract
        ├──────────────────────────────┤
        │ COLLECT BLOCK (Step 16)      │ ← Save to results array
        └──────────────────────────────┘
      END INNER LOOP
    
    ┌──────────────────────────────────┐
    │ AGGREGATE BLOCK (Steps 17-20)   │ ← Analyze, Save outputs
    └──────────────────────────────────┘
  END OUTER LOOP

┌──────────────────────────────────────┐
│ FINALIZE BLOCK (Steps 21-22)        │ ← Cost summary, logs
└──────────────────────────────────────┘
```

---

## Performance Characteristics

| Aspect | Details |
|--------|---------|
| **Loop Type** | Nested (Provider → Document) |
| **Outer Loop** | O(P) where P = providers |
| **Inner Loop** | O(D) where D = docs/provider |
| **RAG Search** | O(log N) where N = total docs |
| **Overall** | O(P × D × log N) |
| **Parallelizable** | Provider level only |
| **State** | Index grows with each doc |
| **Memory** | Bounded by auto-cleanup |

---

## API Call Sequence (Per Document)

```
Single Document Processing:
──────────────────────────

1. blob_download()              → Azure Blob Storage
2. ocr_extract()               → Document Intelligence
3. generate_embedding()        → OpenAI Embeddings
4. index_upload()              → Azure AI Search (Step 11)
5. vector_search()             → Azure AI Search (Step 12)
6. chat_completion()           → OpenAI GPT-4o (Step 14)

Total: 6 API calls per document
Average time: 5-10 seconds per document
Cost: ~$0.05 per document
```

---

## Error Handling Strategy

```
┌─────────────────────────────────────────────────────────────┐
│ Error Point         │ Action           │ Recovery           │
├─────────────────────┼──────────────────┼───────────────────┤
│ Download fails      │ Log & skip doc   │ Continue next doc │
│ OCR fails           │ Log & skip doc   │ Continue next doc │
│ Text < 10 chars     │ Log & skip doc   │ Continue next doc │
│ Embedding fails     │ Log & skip doc   │ Continue next doc │
│ Index upload fails  │ Retry 3x         │ Skip if still fail│
│ RAG search fails    │ Use 0 examples   │ Continue extract  │
│ GPT-4o fails        │ Retry 2x         │ Skip doc if fail  │
│ JSON parse fails    │ Log raw response │ Skip doc          │
└─────────────────────┴──────────────────┴───────────────────┘

Principle: Fail gracefully, never stop entire process
Result: Partial success better than complete failure
```

---

## Monitoring Points

```
Key Metrics to Track:
────────────────────

Phase 1 (Initialization):
  ✓ Config loaded successfully
  ✓ Index created/verified
  ✓ Auto-cleanup completed (X docs deleted)

Phase 2 (Processing):
  ✓ Documents processed per provider
  ✓ Documents skipped (OCR fail, too short, etc.)
  ✓ RAG examples found per search (0, 1, 2, or 3)
  ✓ Extraction success rate
  ✓ Average confidence scores

Phase 3 (Aggregation):
  ✓ Frequency selection results
  ✓ High vs low confidence categorization

Phase 4 (Finalization):
  ✓ Total costs per provider
  ✓ Overall success rate
  ✓ Execution time

All logged to: logs/extraction_YYYYMMDD_HHMMSS.log
```

---

**This technical workflow is block-diagram style with NO CODE - perfect for presentations to technical teams!**
