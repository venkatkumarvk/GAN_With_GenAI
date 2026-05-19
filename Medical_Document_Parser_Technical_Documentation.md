# Medical Document Parser - Technical Documentation
## RAG-Based Production System

**Author:** @VK_Venkatkumar  
**Version:** Production v2.0  
**Date:** May 2026  
**Organization:** EXL Service

---

## 1. Project Explanation

### 1.1 Overview

The Medical Document Parser is a production-grade, Azure-based RAG (Retrieval-Augmented Generation) pipeline that automatically extracts structured data from medical credentialing documents. It processes PDFs, images, and office documents for healthcare providers, extracting 34 fields including personal information, licenses, certifications, vaccines, and insurance details.

### 1.2 Problem Statement

Medical credentialing requires manually reviewing 50-200+ documents per healthcare provider to extract and verify information like licenses, DEA registrations, board certifications, and immunization records. This process takes 2-4 hours per provider manually.

### 1.3 Solution

An automated pipeline that:
- Processes all documents for a provider through OCR
- Chunks and indexes text in Azure AI Search
- Uses per-field RAG to find relevant sections for each of 34 fields
- Extracts values using GPT-5 with multimodal (text + vision) capabilities
- Aggregates results across documents using frequency voting and confidence scoring
- Evaluates extraction quality using 6 evaluation metrics
- Outputs structured JSON, CSV, and cost estimation files

### 1.4 Key Numbers

- 34 extraction fields (16 single-value + 18 multi-value)
- 100+ providers per batch run
- 50-200 documents per provider
- 15 parallel workers for extraction
- 6 evaluation metrics (4 LLM-based, 2 local)
- ~1.5 hours for 100 providers with 15 workers

---

## 2. Key Capabilities

### 2.1 Extraction Capabilities

- **Per-Field RAG Search**: Each field gets its own targeted search query with field-specific hints, not one prompt for all fields
- **Multimodal Extraction**: Combines OCR text + document images for vision-capable extraction (GPT-5)
- **Text RAG Mode**: OCR-only extraction for text-heavy documents
- **Parallel Processing**: 1-15 concurrent field extractions using ThreadPoolExecutor
- **Reranking**: Optional semantic reranker for better chunk selection (config-driven)
- **Batch API Support**: 50% cheaper extraction using Azure OpenAI Batch API

### 2.2 Aggregation Capabilities

- **Frequency Voting**: Most common value across documents wins
- **Confidence Scoring**: Weighted average confidence per field
- **Multi-Value Deduplication**: Key-field signature matching (ignores dates for dedup)
- **Source Tracking**: Tracks which document and folder each value came from

### 2.3 Evaluation Capabilities (6 Metrics)

- **LLM-as-Judge**: GPT evaluates format, normalization, quality per field
- **Hallucination Detection**: Checks if extracted value exists in source OCR text (free, local)
- **Completeness**: Percentage of fields extracted per provider (free, local)
- **Groundedness**: Is extracted value supported by the RAG chunks? (LLM-based)
- **Relevance**: Is extracted value relevant to the field query? (LLM-based)
- **Retrieval Quality**: Did RAG search return relevant chunks? (LLM-based)
- **Field Accuracy**: Exact + fuzzy match vs ground truth (free, local, optional)

### 2.4 Production Capabilities

- **Config-Driven**: All behavior controlled via config.json, no code changes for new doctypes
- **Multi-Doctype**: Support for unlimited document types (cred, invoice, etc.)
- **Azure Key Vault Integration**: Secure credential management
- **SQL Logging**: Provider-level status tracking in SQL Server
- **Cost Tracking**: Per-provider and per-field token usage and cost estimation
- **Auto-Archiving**: Optional provider archiving after processing
- **Azure AI Search Auto-Cleanup**: Automatic index cleanup based on configurable retention days
- **Confidence-Based Routing**: High/low confidence output folders

### 2.5 Universal Design

- **Prompt-Driven**: Add any key to field definitions, automatically included in GPT prompt
- **Evaluation-Driven**: Evaluation rules defined in prompt files, evaluator reads them dynamically
- **Test-Driven**: Tests auto-discover new doctypes, fields, and evaluation prompts

---

## 3. Flowchart

```
START
  │
  ├─ Load Configuration (config.json)
  ├─ Setup Logger (doctype_ragparser_timestamp.log)
  ├─ Validate Doctype Config
  ├─ Load Prompt Module (prompts/parser/cred_prompt.py)
  ├─ Initialize Azure Services
  │    ├─ Key Vault → resolve secrets
  │    ├─ Blob Storage → input/output containers
  │    ├─ Document Intelligence → OCR
  │    ├─ Azure OpenAI → GPT-5 + embeddings
  │    ├─ Azure AI Search → vector index
  │    ├─ Cost Tracker
  │    └─ SQL Logger
  │
  ├─ Discover Providers (scan blob container)
  │
  ├─ FOR EACH PROVIDER:
  │    │
  │    ├─ FOR EACH DOCUMENT:
  │    │    ├─ Step 1: OCR (Document Intelligence)
  │    │    ├─ Step 2: Convert to Images (multimodal mode)
  │    │    ├─ Step 3: Semantic Chunking + Azure AI Search Indexing
  │    │    ├─ Step 4: Per-Field RAG Extraction (parallel)
  │    │    │    ├─ Build field query (name + description + hints)
  │    │    │    ├─ Embed query → Azure AI Search → top 3 chunks
  │    │    │    ├─ Build prompt (universal, reads all keys from field_info)
  │    │    │    ├─ GPT-5 extraction (text + image)
  │    │    │    └─ Store value + confidence + RAG chunks (in-memory)
  │    │    └─ Return extracted_data + OCR text
  │    │
  │    ├─ Aggregate Results
  │    │    ├─ Single-value: frequency voting + confidence tiebreak
  │    │    └─ Multi-value: merge + deduplicate by key fields
  │    │
  │    ├─ Evaluation (if enabled)
  │    │    ├─ LLM-as-Judge (per field)
  │    │    ├─ Hallucination check (per field, uses OCR text)
  │    │    ├─ Groundedness (per field, uses RAG chunks)
  │    │    ├─ Relevance (per field)
  │    │    ├─ Retrieval quality (per field, uses RAG chunks)
  │    │    └─ Completeness (provider-level summary)
  │    │
  │    ├─ Strip internal keys (_rag_context, _rag_query, _ocr_text)
  │    │
  │    ├─ Save Results
  │    │    ├─ Confidence routing (high/low)
  │    │    ├─ JSON output (with evaluation)
  │    │    ├─ CSV output (flattened)
  │    │    ├─ Cost estimation JSON
  │    │    └─ Source documents (preserved folder structure)
  │    │
  │    └─ SQL update (COMPLETED/FAILED)
  │
  ├─ Archive (if enabled)
  └─ Final Summary (costs, tokens, providers)
END
```

---

## 4. Block Diagram - Component Discussion

### Block 1: Configuration Layer

**Files:** `config/config.json`, `utils/config_loader.py`

Loads and validates all configuration. Supports Azure Key Vault references for secrets. Each doctype has its own section with extraction model, evaluation model, AI Search index, and folder configurations. The entire pipeline behavior is controlled here -- no code changes needed for new doctypes.

### Block 2: Prompt Layer

**Files:** `prompts/parser/cred_prompt.py`, `prompts/evaluation/cred_eval_prompt.py`

Defines all field extraction rules (FIELD_LIBRARY) and evaluation guidelines (FIELD_EVALUATION_GUIDELINES). The prompt builder reads ANY key from field definitions automatically -- adding "note", "special_handling", "validation" or any future key to a field definition automatically includes it in the GPT prompt without code changes.

### Block 3: OCR & Document Processing

**Files:** `services/ocr.py`, `services/document_converter.py`

Azure Document Intelligence extracts text from PDFs, images, and office documents. DocumentConverter converts documents to page images for multimodal extraction. Supports PDF, PNG, JPG, TIFF, BMP, DOCX, RTF formats.

### Block 4: Semantic Chunking & Indexing

**Files:** `extraction/semantic_chunker.py`, `services/azure_clients.py` (SearchManager)

SemanticChunkerV2 splits OCR text into overlapping chunks (target 3000 chars) respecting section boundaries. Chunks are embedded using Azure OpenAI embeddings and indexed in Azure AI Search with provider/folder metadata for filtering.

### Block 5: RAG Extraction Engine

**Files:** `extraction/text_rag.py`, `extraction/multimodal_rag.py`

Per-field RAG: each of 34 fields gets its own search query, embedding, vector search, and GPT extraction call. Supports text-only (text_rag) and multimodal (text + image, multimodal_rag) modes. Parallel processing with ThreadPoolExecutor (1-15 workers). Retry with exponential backoff on rate limits.

### Block 6: Aggregation Engine

**File:** `utils/aggregator.py`

Cross-document aggregation. Single-value fields use frequency voting with confidence tiebreak. Multi-value fields merge arrays and deduplicate by key identifying fields (number + state, ignoring dates). Carries RAG context through for evaluation.

### Block 7: Evaluation Engine

**Files:** `evaluation/eval_runner.py`, `evaluation/evaluator.py`, `evaluation/metrics/*`

Config-driven evaluation orchestrator. Runs selected metrics based on doctype config. All LLM-based metrics use direct Azure OpenAI calls (custom implementation, no SDK dependency). Works with any model (GPT-4o, GPT-5, future models). Adds `evaluation` dict to each field with per-metric scores.

### Block 8: Output Layer

**File:** `utils/result_saver.py`

Saves JSON (with evaluation), CSV (flattened with eval columns), cost estimation, and source documents to Azure Blob Storage. Confidence-based routing to highconfidence/lowconfidence folders. Strips internal keys before saving.

### Block 9: Azure Services

**Files:** `services/azure_clients.py`, `services/keyvault_manager.py`, `services/sql_logger.py`, `services/cost_tracker.py`, `services/archive_manager.py`

BlobManager (Azure Blob Storage), OpenAIManager (Azure OpenAI GPT + embeddings + batch), SearchManager (Azure AI Search with vector indexing), KeyVaultManager (Azure Key Vault), SQLLogger (SQL Server logging), CostTracker (per-provider cost tracking), ArchiveManager (post-processing archiving).

---

## 5. Step-by-Step Function Reference

### 5.1 Entry Point

#### `main.py`

##### main()
- **Objective:** Application entry point. Parses arguments, orchestrates the pipeline.
- **Brief:** Loads config, sets up logging, validates doctype, initializes services, discovers providers, and processes all providers.
- **Key Steps:**
  1. Parse CLI arguments (--apitype, --doctype, --archive)
  2. Load configuration from config.json
  3. Setup logger with doctype prefix
  4. Set runtime config (api_type, archive flag)
  5. Validate doctype configuration
  6. Load prompt module for the doctype
  7. Initialize all Azure services
  8. Discover providers from blob container
  9. Process all providers
- **Returns:** None (writes output to Azure Blob Storage)

---

### 5.2 Configuration Layer (`utils/config_loader.py`)

##### load_configuration(config_path)
- **Objective:** Load JSON configuration file.
- **Brief:** Reads config.json from disk. Called before logger setup (silent).
- **Key Steps:**
  1. Check file exists
  2. Read and parse JSON
- **Returns:** Dict (full configuration)

##### validate_doctype_config(config, doctype)
- **Objective:** Validate doctype-specific configuration has all required keys.
- **Brief:** Checks for azure_openai, azure_openai_embedding, azure_ai_search, folder_configs, prompt_module.
- **Key Steps:**
  1. Check doctype exists in config
  2. Validate required keys present
  3. Store current doctype in config for evaluation
  4. Log doctype details
- **Returns:** Dict (doctype configuration)

##### load_prompt_module(prompt_module_path)
- **Objective:** Dynamically import prompt module.
- **Brief:** Uses __import__ to load prompts.parser.cred_prompt or any prompt module path.
- **Key Steps:**
  1. Split module path into parts
  2. Dynamic import using __import__
  3. Count fields in FIELD_LIBRARY
- **Returns:** Module object (with FIELD_LIBRARY, SYSTEM_PROMPT_CONFIG)

##### initialize_azure_services(config, doctype_config)
- **Objective:** Initialize all Azure service connections.
- **Brief:** Creates clients for Key Vault, Blob Storage, Document Intelligence, OpenAI, AI Search, Cost Tracker, SQL Logger.
- **Key Steps:**
  1. Initialize Key Vault Manager
  2. Resolve all @azureKeyVault() references in config
  3. Initialize Blob Storage client
  4. Initialize Document Intelligence (OCR) client
  5. Initialize OpenAI Manager (GPT + embeddings + optional batch)
  6. Initialize AI Search Manager + create/verify index
  7. Initialize Cost Tracker and SQL Logger
- **Returns:** Dict (services dict with all clients)

##### discover_providers(blob_manager, input_container)
- **Objective:** Scan blob container for provider folders.
- **Brief:** Lists all top-level folders in the input container. Each folder = one provider.
- **Key Steps:**
  1. Get folder structure from blob container
  2. Extract provider names
  3. Log provider count and first 5 names
- **Returns:** Tuple (providers list, folder_structure dict)

---

### 5.3 Provider Processing (`utils/provider_processor.py`)

##### process_document_with_rag(doc_blob, provider, folder, fields, services, config, prompt_module)
- **Objective:** Process a single document using RAG extraction.
- **Brief:** Routes to text or multimodal RAG based on config. Downloads document, determines extension, calls extraction function.
- **Key Steps:**
  1. Download document bytes from blob
  2. Determine file extension
  3. Build RAG parameters (parallel_workers, rag_config)
  4. Route to text_rag or multimodal_rag based on config
  5. Return extracted data
- **Returns:** Dict (extracted fields) or None on failure

##### process_single_provider(provider, folder_structure, blob_manager, config, services, doctype, doctype_config, prompt_module, archiver)
- **Objective:** Process all documents for one provider.
- **Brief:** Finds matching folder, processes each document, aggregates results, runs evaluation, saves output, updates SQL.
- **Key Steps:**
  1. Set provider in cost tracker
  2. Find matching folder from folder_configs
  3. List all documents in folder
  4. SQL: insert begin record
  5. For each document: extract fields, collect OCR text
  6. Aggregate results using frequency voting
  7. Save results (with evaluation)
  8. SQL: update complete
  9. Archive if enabled
- **Returns:** None (writes to blob storage and SQL)

##### process_providers(providers, folder_structure, config, services, doctype, doctype_config, prompt_module)
- **Objective:** Process all providers in batches.
- **Brief:** Loops through providers in configurable batch sizes. Runs auto-cleanup, archiving, and final summary.
- **Key Steps:**
  1. Auto-cleanup old AI Search data
  2. Calculate batches
  3. Initialize archiver if enabled
  4. For each batch: process each provider
  5. Finalize archive
  6. Print final summary (costs, tokens, providers)
- **Returns:** None

##### _print_final_summary(services, config)
- **Objective:** Print final processing summary.
- **Brief:** Shows RAG mode, API type, provider stats, token usage, and cost breakdown.
- **Key Steps:**
  1. Get cost summary from tracker
  2. Calculate processed/unprocessed providers
  3. Log token usage per provider
  4. Log cost breakdown (OCR, embedding, GPT)
- **Returns:** None (logs to file)

---

### 5.4 Text RAG Extraction (`extraction/text_rag.py`)

##### process_document_text_rag(doc_bytes, doc_name, extension, provider, folder, fields, ocr, openai_manager, search_manager, cost_tracker, prompt_module, api_type, parallel_workers, rag_config)
- **Objective:** Extract fields from a document using text-based RAG.
- **Brief:** OCR → chunk → index → per-field search → GPT extraction.
- **Key Steps:**
  1. OCR: extract text from document
  2. Semantic chunking (3000 char target, 300 overlap)
  3. Embed and index chunks in Azure AI Search
  4. Route to general (real-time) or batch API
  5. Store OCR text in result for hallucination detection
- **Returns:** Tuple (extracted_data dict, success bool)

##### _extract_fields_general(fields, chunks, provider, folder, openai_manager, search_manager, cost_tracker, field_library, system_config, parallel_workers, rag_config)
- **Objective:** Extract fields using real-time General API.
- **Brief:** Sequential or parallel per-field RAG extraction.
- **Key Steps:**
  1. If parallel_workers > 1: route to _extract_fields_parallel
  2. For each field: build query, embed, search, build prompt, GPT extract
  3. Store RAG chunks with each result (_rag_context, _rag_query)
- **Returns:** Dict (field_name → result)

##### _extract_fields_parallel(fields, chunks, provider, folder, ..., max_workers, rag_config)
- **Objective:** Extract fields concurrently using ThreadPoolExecutor.
- **Brief:** Same logic as sequential but 1-15 fields at a time. Thread-safe cost tracking with lock. Retry with exponential backoff on 429 errors.
- **Key Steps:**
  1. Create ThreadPoolExecutor with max_workers
  2. Submit extract_single_field for each field
  3. Collect results as they complete
  4. Track retries and rate limit hits
  5. Store RAG chunks per field
- **Returns:** Dict (field_name → result)

##### _build_field_prompt(field_name, field_info, similar_docs, fallback_text, system_config)
- **Objective:** Build extraction prompt for one field.
- **Brief:** Universal prompt builder -- reads ANY key from field_info automatically.
- **Key Steps:**
  1. Build system instructions from SYSTEM_PROMPT_CONFIG
  2. Build field definition (auto-includes all keys: description, format, examples, extraction_hints, confidence_factors, note, special_handling, validation, any future key)
  3. Add RAG context from similar_docs
  4. Add output format instructions (JSON)
- **Returns:** String (complete prompt)

##### _extract_fields_batch(fields, chunks, provider, folder, ...)
- **Objective:** Extract fields using Azure OpenAI Batch API (50% cheaper).
- **Brief:** Creates JSONL batch request, submits, waits, parses results.
- **Key Steps:**
  1. Build batch requests (one per field)
  2. Submit batch job
  3. Wait for completion (polling)
  4. Parse batch results
- **Returns:** Dict (field_name → result)

---

### 5.5 Multimodal RAG Extraction (`extraction/multimodal_rag.py`)

##### process_document_multimodal_rag(doc_bytes, doc_name, extension, provider, folder, fields, ocr, openai_manager, search_manager, cost_tracker, prompt_module, api_type, parallel_workers, rag_config)
- **Objective:** Extract fields using text + vision (multimodal) RAG.
- **Brief:** Same as text RAG but also sends document image to GPT-5 for vision-based extraction.
- **Key Steps:**
  1. OCR: extract text
  2. Convert document to page images
  3. Semantic chunking + indexing (same as text mode)
  4. Per-field RAG extraction with image (general or batch)
  5. Store OCR text and RAG chunks in result
- **Returns:** Tuple (extracted_data dict, success bool)

##### _extract_fields_multimodal_general(fields, chunks, provider, folder, ..., image_b64, image_format, parallel_workers, rag_config)
- **Objective:** Extract fields with vision using General API.
- **Brief:** Same as text general but includes base64 image in each GPT call.
- **Key Steps:**
  1. If parallel: route to text_rag._extract_fields_parallel (with use_vision=True)
  2. For each field: search + build multimodal prompt + GPT extract with image
  3. Store RAG chunks per field
- **Returns:** Dict (field_name → result)

##### _build_multimodal_prompt(field_name, field_info, similar_docs, fallback_text, system_config)
- **Objective:** Build multimodal extraction prompt.
- **Brief:** Same as text prompt but adds instruction to use document image. Universal key reading.
- **Key Steps:**
  1. Build field definition (universal, all keys auto-included)
  2. Add RAG text context
  3. Add vision instructions ("Also examine the document image")
  4. Add JSON output format
- **Returns:** String (prompt)

##### _convert_to_images(doc_bytes, doc_name, extension)
- **Objective:** Convert document to page images for GPT vision.
- **Brief:** Uses DocumentConverter to convert PDF/images to base64 page images.
- **Key Steps:**
  1. Create DocumentConverter
  2. Convert document bytes to images
  3. Convert images to base64
- **Returns:** List of dicts [{base64, format}]

---

### 5.6 Semantic Chunking (`extraction/semantic_chunker.py`)

##### class SemanticChunkerV2
- **Objective:** Split text into overlapping, section-aware chunks for RAG indexing.
- **Brief:** Adaptive chunking that respects document section boundaries. Target 3000 chars, min 500, max 6000, 300 char overlap.

##### SemanticChunkerV2.chunk_document(text, doc_id)
- **Objective:** Chunk a document into RAG-ready pieces.
- **Key Steps:**
  1. Calculate adaptive chunk size based on text length
  2. Try section-based splitting (finds headers, numbered sections)
  3. If sections found: merge small sections, split large ones
  4. If no sections: fall back to overlap-based splitting
  5. Validate coverage (every char accounted for)
  6. Return chunks with metadata
- **Returns:** List of dicts [{text, doc_id, chunk_index, char_start, char_end}]

---

### 5.7 Aggregation (`utils/aggregator.py`)

##### calculate_best_values(documents, fields, folder_name, prompt_module)
- **Objective:** Aggregate extraction results across all documents for a provider.
- **Brief:** Routes each field to single or multi aggregation based on cardinality.
- **Key Steps:**
  1. Get FIELD_LIBRARY from prompt module
  2. For each field: check cardinality (single/multi)
  3. Route to _aggregate_single_field or _aggregate_multi_field
- **Returns:** Dict (field_name → aggregated result with metadata)

##### _aggregate_single_field(field, documents, folder_name)
- **Objective:** Pick the best single value using frequency voting.
- **Brief:** Counts how often each value appears across documents, picks most frequent, uses highest confidence for ties.
- **Key Steps:**
  1. Collect all occurrences (value, confidence, source_file, rag_context)
  2. Count value frequencies
  3. Pick most common value
  4. Among candidates with that value, pick highest confidence
  5. Calculate average confidence
  6. Carry RAG context from best occurrence
- **Returns:** Dict {value, confidence, source_folder, source_file, frequency, total_documents, _rag_context, _rag_query}

##### _aggregate_multi_field(field, documents, folder_name, field_info)
- **Objective:** Merge and deduplicate multi-value arrays.
- **Brief:** Collects all items across documents, deduplicates by key fields (number + state, ignoring dates/status), keeps highest confidence version.
- **Key Steps:**
  1. Collect all items from all documents
  2. Build signature from key fields (skip dates, status, id)
  3. Deduplicate: same signature = keep highest confidence version
  4. Build final array with sequential IDs
  5. Carry RAG context per sub-field
- **Returns:** List of dicts [{id, sub_field: {value, confidence, ...}}]

##### _avg_item_confidence(item)
- **Objective:** Calculate average confidence across sub-fields.
- **Brief:** Used for multi-value deduplication tiebreaking.
- **Returns:** Float (average confidence)

---

### 5.8 Evaluation Engine

#### `evaluation/eval_runner.py`

##### class EvalRunner
- **Objective:** Config-driven evaluation orchestrator. Runs selected metrics on extracted data.

##### EvalRunner.__init__(eval_config, eval_prompt_module)
- **Objective:** Initialize enabled metrics from config.
- **Key Steps:**
  1. Check if evaluation is enabled
  2. Initialize LLM Judge (if llm_judge: true)
  3. Initialize Hallucination metric (if metrics.hallucination: true)
  4. Initialize Completeness metric (if metrics.completeness: true)
  5. Initialize Field Accuracy metric (if metrics.field_accuracy.enabled: true)
  6. Initialize Custom AI Eval (if metrics.azure_ai_eval.enabled: true)
- **Returns:** EvalRunner instance with active metrics list

##### EvalRunner.evaluate_and_enrich(extracted_data, context)
- **Objective:** Run all metrics on all fields, add evaluation results to data.
- **Key Steps:**
  1. For each single-value field with value: run _evaluate_single
  2. For each multi-value sub-field with value: run _evaluate_single
  3. Store results as field_data['evaluation'] = {...}
  4. Empty values get evaluation: {}
- **Returns:** Dict (enriched extracted_data with evaluation keys)

##### EvalRunner._evaluate_single(field_name, field_data, context)
- **Objective:** Run all active metrics on one field.
- **Key Steps:**
  1. Build eval_context from passed context + field's _rag_context
  2. For each metric: call appropriate method
  3. LLM Judge: _run_llm_judge
  4. Custom AI Eval: evaluate_field (returns groundedness, relevance, retrieval)
  5. Hallucination: evaluate_field (checks OCR text)
  6. Completeness: skip (provider-level)
  7. Collect all metric results
- **Returns:** Dict {llm_judge: {...}, hallucination: {...}, groundedness: {...}, ...}

##### EvalRunner.get_provider_summary(extracted_data, context)
- **Objective:** Generate provider-level evaluation summary.
- **Key Steps:**
  1. Run completeness on full extracted_data
  2. Aggregate hallucination scores → hallucination_rate
  3. Average groundedness, relevance, retrieval, llm_judge scores
  4. Count fields evaluated and fields with issues
- **Returns:** Dict {completeness: {...}, avg_groundedness, avg_relevance, fields_with_issues, ...}

#### `evaluation/evaluator.py`

##### class LLMJudge
- **Objective:** LLM-based field quality evaluator. Uses GPT to score extraction quality.

##### LLMJudge.__init__(config, eval_prompt_module)
- **Objective:** Initialize with Azure OpenAI client and guidelines.
- **Key Steps:**
  1. Load guidelines from eval_prompt_module
  2. Load system prompt
  3. Initialize Azure OpenAI client from config
- **Returns:** LLMJudge instance

##### LLMJudge._call_llm(field_name, value, guideline)
- **Objective:** Send field to GPT for evaluation.
- **Key Steps:**
  1. Build evaluation prompt with field value + expected format + rules
  2. Call GPT-5 (max_completion_tokens, no temperature)
  3. Parse JSON response
  4. Extract score, issues, suggestion
- **Returns:** Dict {score, issues, suggestion} or None on failure

#### `evaluation/metrics/hallucination.py`

##### class HallucinationMetric
- **Objective:** Check if extracted value exists in source OCR text. Free, no API call.

##### HallucinationMetric.evaluate_field(field_name, field_data, context)
- **Key Steps:**
  1. Get value from field_data
  2. Get ocr_texts from context
  3. Search value (case-insensitive) in all OCR texts
  4. If found: score 1.0, found_in_source: true
  5. If not found: try word-by-word partial match
  6. If nothing found: score 0.0, found_in_source: false
- **Returns:** Dict {score, found_in_source} or None if no value/no OCR

#### `evaluation/metrics/completeness.py`

##### class CompletenessMetric
- **Objective:** Calculate what percentage of fields have values. Free, no API call.

##### CompletenessMetric.evaluate_provider(extracted_data)
- **Key Steps:**
  1. Count total fields
  2. Count fields with non-empty values (single: value != '', multi: has items with values)
  3. Track missing field names
  4. Calculate percentage
- **Returns:** Dict {score, total_fields, extracted_fields, empty_fields, missing_field_names}

#### `evaluation/metrics/custom_ai_eval.py`

##### class CustomAIEvalMetric
- **Objective:** Custom groundedness, relevance, retrieval evaluation. No SDK dependency. Works with any model.

##### CustomAIEvalMetric.evaluate_field(field_name, field_data, context)
- **Key Steps:**
  1. Get value, query, rag_context from field_data and context
  2. If groundedness enabled + rag_context available: send groundedness prompt to GPT
  3. If relevance enabled: send relevance prompt to GPT
  4. If retrieval enabled + rag_context available: send retrieval prompt to GPT
  5. Parse JSON response, normalize score to 0.0-1.0
- **Returns:** Dict {groundedness: {score, label, reason}, relevance: {...}, retrieval: {...}}

##### CustomAIEvalMetric._call_evaluator(prompt)
- **Objective:** Send evaluation prompt to GPT. GPT-5 compatible.
- **Key Steps:**
  1. Call Azure OpenAI with max_completion_tokens (not max_tokens)
  2. Parse JSON response
  3. Clamp score to 0.0-1.0
  4. Set label: pass (>= 0.6) or fail (< 0.6)
- **Returns:** Dict {score, label, reason} or None on failure

#### `evaluation/metrics/field_accuracy.py`

##### class FieldAccuracyMetric
- **Objective:** Compare extracted values against ground truth. Free, no API call.

##### FieldAccuracyMetric.evaluate_field(field_name, field_data, context)
- **Key Steps:**
  1. Get extracted value
  2. Look up ground truth for this provider + field
  3. Calculate exact match (case-insensitive)
  4. Calculate fuzzy match (Levenshtein ratio)
  5. Score: 1.0 (exact), 0.9 (fuzzy > 90%), 0.75, 0.5, 0.0
- **Returns:** Dict {score, exact_match, fuzzy_score, ground_truth}

---

### 5.9 Result Saving (`utils/result_saver.py`)

##### save_results(provider, extracted_data, output_container, input_container, blob_manager, config, total_documents, folder_name, source_documents, cost_tracker, sql_doc_key, ocr_texts)
- **Objective:** Save extraction results to Azure Blob Storage.
- **Key Steps:**
  1. Calculate confidence metrics (min, avg)
  2. Route to highconfidence or lowconfidence folder
  3. Run evaluation if enabled (EvalRunner)
  4. Strip internal keys (_rag_context, _rag_query, _ocr_text)
  5. Build JSON output with evaluation_summary
  6. Save JSON, CSV, cost estimation, source documents
- **Returns:** Float (min_confidence for SQL logging)

##### _strip_internal_keys(extracted_data)
- **Objective:** Remove internal metadata before saving to JSON.
- **Brief:** Removes _rag_context, _rag_query, _ocr_text. These are in-memory only, never saved to disk.
- **Returns:** None (modifies dict in place)

---

### 5.10 Azure Services

#### `services/azure_clients.py`

##### class BlobManager
- **Objective:** Azure Blob Storage operations.
- **Functions:** get_folder_structure, list_folder_documents, list_blobs_in_folder, download_blob, upload_blob

##### class OpenAIManager
- **Objective:** Azure OpenAI GPT + Embedding operations.
- **Functions:** generate_embedding, extract_fields, create_batch_request, submit_batch_job, wait_for_batch, parse_batch_results

##### class SearchManager
- **Objective:** Azure AI Search vector indexing and search.
- **Functions:** create_universal_index, upload_document, search_similar (with optional reranking), delete_provider_chunks, delete_old_documents

##### SearchManager.search_similar(vector, provider, folder, top_k, query_text, reranking, reranking_top_k)
- **Objective:** Find similar documents using vector search with optional semantic reranking.
- **Key Steps:**
  1. Build OData filter (provider + optional folder)
  2. If reranking: retrieve reranking_top_k candidates, semantic rerank, return top_k
  3. If no reranking: direct vector search for top_k
  4. Fallback: if reranking fails, retry without it
- **Returns:** List [{content, score}]

##### SearchManager.delete_old_documents(days, provider)
- **Objective:** Auto-cleanup old chunks from AI Search index.
- **Key Steps:**
  1. Calculate cutoff date
  2. Try 3 filters: timestamp < cutoff, timestamp = null, timestamp = ''
  3. Paginate (1000 per batch) and delete
  4. Handle chunks with and without upload_timestamp field
- **Returns:** Int (total chunks deleted)

#### `services/ocr.py`

##### class DocumentIntelligenceOCR
- **Objective:** Azure Document Intelligence OCR.
- **Functions:** extract_text, _extract_text_direct, _extract_with_base64, test_connection

#### `services/cost_tracker.py`

##### class CostTracker
- **Objective:** Track token usage and costs per provider.
- **Functions:** set_provider, add_ocr, add_embedding, add_gpt_tokens, get_summary

#### `services/sql_logger.py`

##### class SQLLogger
- **Objective:** Log provider processing status to SQL Server.
- **Functions:** insert_begin, update_status, update_complete

#### `services/keyvault_manager.py`

##### class KeyVaultManager
- **Objective:** Resolve @azureKeyVault() references in config.
- **Functions:** resolve_value, get_secret

##### resolve_config_values(config, kv_manager)
- **Objective:** Walk config dict and resolve all Key Vault references recursively.

---

### 5.11 Prompt Modules

#### `prompts/parser/cred_prompt.py`

- **FIELD_LIBRARY:** Dict of 34 fields with cardinality, description, format, examples, extraction_hints, confidence_factors, and any custom keys (note, special_handling, validation)
- **SYSTEM_PROMPT_CONFIG:** System-level prompt instructions for GPT

#### `prompts/evaluation/cred_eval_prompt.py`

- **FIELD_EVALUATION_GUIDELINES:** Dict of 34 fields with expected_format, rules (type-based validation rules), sub_field_rules for multi-value fields
- **JUDGE_SYSTEM_PROMPT:** System prompt for LLM-as-Judge
- **EVALUATION_CONFIG:** Default model, max_tokens settings

---

## 6. Cost Estimation and Services Used

### 6.1 Azure Services

| Service | Purpose | Pricing |
|---------|---------|---------|
| Azure OpenAI (GPT-5) | Field extraction, LLM evaluation | ~$10/1M input tokens, ~$30/1M output tokens |
| Azure OpenAI (Embeddings) | Chunk and query embeddings | ~$0.10/1M tokens |
| Azure Document Intelligence | OCR | ~$0.01/page |
| Azure AI Search | Vector index + search | ~$0.01/1000 queries + index storage |
| Azure Blob Storage | Document storage | ~$0.018/GB/month |
| Azure Key Vault | Secret management | ~$0.03/10,000 operations |
| SQL Server | Provider status logging | Existing infrastructure |

### 6.2 Cost per Provider (typical: 20 documents, 34 fields)

| Component | Tokens/Pages | Cost |
|-----------|-------------|------|
| OCR | ~87 pages | $0.87 |
| Embeddings | ~12,800 tokens | $0.001 |
| GPT Extraction | ~263,500 tokens | $3.00 |
| GPT Evaluation (4 metrics) | ~62,400 tokens | $0.94 |
| AI Search | ~34 queries | $0.001 |
| **Total per provider** | | **~$4.81** |

### 6.3 Cost per Batch (100 providers)

| Configuration | Time | Cost |
|--------------|------|------|
| General API, 10 workers, no eval | ~2 hours | ~$388 |
| General API, 15 workers, with eval | ~1.5 hours | ~$481 |
| Batch API, no eval | ~3 hours (async) | ~$194 (50% cheaper) |

### 6.4 Cost Optimization Strategies

1. **Batch API**: 50% reduction in GPT costs
2. **Parallel workers**: Reduces time but same total cost
3. **Selective evaluation**: Run eval on 10% of providers, not all
4. **Reranking disabled**: Saves ~$0.01/1000 queries (negligible)
5. **Content filter**: Allow all for medical content (prevents retries)
6. **TPM quota**: 5M TPM prevents 429 rate limit retries

---

## Appendix: File Structure

```
medical_document_parser/
├── main.py                              (101 lines - entry point)
├── config/
│   └── config.json                      (all configuration)
├── prompts/
│   ├── parser/
│   │   └── cred_prompt.py               (34 field extraction rules)
│   └── evaluation/
│       └── cred_eval_prompt.py          (34 field evaluation guidelines)
├── utils/
│   ├── config_loader.py                 (config, validation, services init)
│   ├── aggregator.py                    (frequency voting, dedup)
│   ├── result_saver.py                  (JSON, CSV, cost output)
│   ├── provider_processor.py            (document + provider processing)
│   └── logger_helper.py                 (logging setup)
├── extraction/
│   ├── text_rag.py                      (text-only RAG extraction)
│   ├── multimodal_rag.py                (text + vision RAG extraction)
│   └── semantic_chunker.py              (document chunking)
├── evaluation/
│   ├── evaluator.py                     (LLM-as-Judge)
│   ├── eval_runner.py                   (metric orchestrator)
│   └── metrics/
│       ├── base_metric.py               (abstract base)
│       ├── hallucination.py             (OCR text check, free)
│       ├── completeness.py              (field count, free)
│       ├── field_accuracy.py            (ground truth comparison, free)
│       └── custom_ai_eval.py            (groundedness/relevance/retrieval)
├── services/
│   ├── azure_clients.py                 (Blob, OpenAI, Search managers)
│   ├── ocr.py                           (Document Intelligence)
│   ├── cost_tracker.py                  (per-provider cost tracking)
│   ├── sql_logger.py                    (SQL Server logging)
│   ├── keyvault_manager.py              (Key Vault secret resolution)
│   ├── archive_manager.py               (post-processing archiving)
│   └── document_converter.py            (PDF/image conversion)
└── tests/
    └── test_parser.py                   (69 tests, auto-discovers)
```

---

## Appendix: For New Doctypes

Only create/edit 3 files:

1. **`config/config.json`** — add doctype section with model, index, fields, evaluation
2. **`prompts/parser/xxx_prompt.py`** — define FIELD_LIBRARY with extraction rules
3. **`prompts/evaluation/xxx_eval_prompt.py`** — define evaluation guidelines

Never touch: main.py, utils/*, extraction/*, evaluation/*, services/*, tests/*
