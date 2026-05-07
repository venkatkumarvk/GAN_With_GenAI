"""
Text RAG Extraction Module
===========================

Text-based extraction pipeline:
  OCR -> Semantic Chunking -> Embedding -> AI Search Index -> 
  Per-field RAG Search -> Text-only GPT Extraction

Config: rag.mode = "text"

For each field:
  1. Search AI Search index for chunks most relevant to this field
  2. Send retrieved text chunks to GPT (text-only, no vision)
  3. Extract field value with confidence score

Adding new document types:
  1. Create new prompt file in prompts/ (copy cred_prompt.py as template)
  2. Add doctype entry in config.json with folder_configs and fields
  3. Done - this module adapts automatically via prompt_module parameter
"""

import logging
import hashlib
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def process_document_text_rag(
    doc_bytes: bytes,
    doc_name: str,
    extension: str,
    provider: str,
    folder: str,
    fields: List[str],
    ocr,
    openai_manager,
    search_manager,
    cost_tracker,
    prompt_module,
    api_type: str = "general",
    parallel_workers: int = 1,
    rag_config: dict = None
) -> Tuple[Dict, bool]:
    """
    Extract fields using text-based RAG.
    
    Supports two API modes:
      - "general": Real-time per-field GPT calls (default)
      - "batch": Collect all field prompts, submit as one batch job, wait, parse
    
    Args:
        doc_bytes: Document bytes
        doc_name: Document name
        extension: File extension
        provider: Provider name
        folder: Folder name
        fields: List of field names to extract
        ocr: OCR service
        openai_manager: OpenAI service
        search_manager: AI Search service
        cost_tracker: Cost tracker
        prompt_module: Prompt module with FIELD_LIBRARY
        api_type: "general" (real-time) or "batch" (Azure Batch API)
    
    Returns:
        (extracted_data, success)
    """
    logger.info(f"    Document: {doc_name} - Text RAG extraction (api: {api_type})")
    
    # ========================================================================
    # STEP 1: OCR
    # ========================================================================
    text, pages, success = ocr.extract_text(doc_bytes, extension)
    
    if not success or len(text) < 100:
        logger.warning(f"      FAILED: Insufficient text")
        return {}, False
    
    cost_tracker.add_ocr(pages)
    logger.info(f"      Step 1: OCR complete ({len(text)} chars, {pages} pages)")
    
    # ========================================================================
    # STEP 2: SEMANTIC CHUNKING (zero data loss)
    # ========================================================================
    from extraction.semantic_chunker import SemanticChunkerV2
    
    chunker = SemanticChunkerV2(
        target_chunk_size=3000,
        min_chunk_size=500,
        max_chunk_size=6000,
        overlap_size=300,
        adaptive=True
    )
    
    chunks = chunker.chunk_document(text, doc_name)
    summary = chunker.get_chunk_summary(chunks)
    logger.info(f"      Step 2: {summary['total_chunks']} chunks "
               f"({summary['total_text_length']} chars)")
    
    # ========================================================================
    # STEP 3: GENERATE EMBEDDINGS AND INDEX ALL CHUNKS
    # ========================================================================
    content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    
    uploaded_chunks = 0
    for chunk in chunks:
        try:
            chunk_embedding, tokens = openai_manager.generate_embedding(chunk['text'])
            cost_tracker.add_embedding(tokens)
            
            chunk_doc_id = f"{content_hash}_{chunk['chunk_index']}"
            
            success = search_manager.upload_document(
                doc_id=chunk_doc_id,
                content=chunk['text'],
                vector=chunk_embedding,
                provider=provider,
                folder=folder,
                document_name=doc_name,
                chunk_index=chunk['chunk_index'],
                total_chunks=chunk['total_chunks']
            )
            
            if success:
                uploaded_chunks += 1
        except Exception as e:
            logger.warning(f"      Failed to upload chunk {chunk['chunk_index']}: {e}")
            continue
    
    if uploaded_chunks == 0:
        logger.warning(f"      FAILED: Could not upload any chunks")
        return {}, False
    
    logger.info(f"      Step 3: Indexed {uploaded_chunks}/{len(chunks)} chunks")
    
    # ========================================================================
    # STEP 4: EXTRACT FIELDS
    # ========================================================================
    FIELD_LIBRARY = getattr(prompt_module, 'FIELD_LIBRARY', {})
    SYSTEM_PROMPT_CONFIG = getattr(prompt_module, 'SYSTEM_PROMPT_CONFIG', {})
    
    if api_type == 'batch':
        extracted_data = _extract_fields_batch(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            FIELD_LIBRARY, SYSTEM_PROMPT_CONFIG, doc_name
        )
    else:
        extracted_data = _extract_fields_general(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            FIELD_LIBRARY, SYSTEM_PROMPT_CONFIG,
            parallel_workers=parallel_workers,
            rag_config=rag_config or {}
        )
    
    logger.info(
        f"      Step 4 complete: {len(extracted_data)}/{len(fields)} fields"
    )
    
    return extracted_data, True


def _extract_fields_general(
    fields, chunks, provider, folder,
    openai_manager, search_manager, cost_tracker,
    field_library, system_config, parallel_workers=1,
    rag_config=None
) -> Dict:
    """
    Extract fields using real-time General API.
    Supports parallel extraction with ThreadPoolExecutor.
    Supports reranking via rag_config.
    """
    if rag_config is None:
        rag_config = {}
    
    reranking = rag_config.get('reranking', False)
    reranking_top_k = rag_config.get('reranking_top_k', 10)
    top_k = rag_config.get('top_k', 3)
    
    if parallel_workers > 1:
        mode = "RERANKING" if reranking else "GENERAL"
        logger.info(f"      Step 4: Extracting {len(fields)} fields ({mode} API, {parallel_workers} parallel workers)...")
        return _extract_fields_parallel(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            field_library, system_config,
            use_vision=False, image_b64=None, image_format=None,
            max_workers=parallel_workers,
            rag_config=rag_config
        )
    
    mode = "RERANKING" if reranking else "GENERAL"
    logger.info(f"      Step 4: Extracting {len(fields)} fields ({mode} API)...")
    
    extracted_data = {}
    
    for field_idx, field_name in enumerate(fields, 1):
        try:
            field_info = field_library.get(field_name, {})
            field_desc = field_info.get('description', field_name)
            
            logger.info(f"        Field {field_idx}/{len(fields)}: {field_name}")
            
            # Field-specific RAG search
            field_query_parts = [
                field_name.replace('_', ' '), field_desc
            ]
            hints = field_info.get('extraction_hints', [])
            if hints:
                field_query_parts.append(' '.join(hints[:2]))
            
            query_text = ' '.join(field_query_parts)
            
            field_embedding, query_tokens = openai_manager.generate_embedding(query_text)
            cost_tracker.add_embedding(query_tokens)
            
            similar_docs = search_manager.search_similar(
                vector=field_embedding, provider=provider,
                folder=folder, top_k=top_k,
                query_text=query_text if reranking else None,
                reranking=reranking,
                reranking_top_k=reranking_top_k
            )
            
            search_mode = "reranked" if reranking else "vector"
            logger.info(f"          RAG: {len(similar_docs)} chunks found ({search_mode})")
            
            # Build prompt and extract
            prompt = _build_field_prompt(
                field_name=field_name,
                field_info=field_info,
                similar_docs=similar_docs,
                fallback_text=chunks[0]['text'] if chunks else "",
                system_config=system_config
            )
            
            result, tokens = openai_manager.extract_fields(
                prompt=prompt, temperature=0.1, use_vision=False
            )
            
            cost_tracker.add_gpt_tokens(
                tokens['input_tokens'], tokens['output_tokens']
            )
            
            if field_name in result:
                extracted_data[field_name] = result[field_name]
                field_result = result[field_name]
                if isinstance(field_result, dict):
                    value = field_result.get('value', '')
                    conf = field_result.get('confidence', 0.0)
                    logger.info(f"          Result: {value} (conf: {conf:.2f})")
                elif isinstance(field_result, list):
                    logger.info(f"          Result: {len(field_result)} items extracted")
                else:
                    logger.info(f"          Result: {field_result}")
            else:
                extracted_data[field_name] = {
                    'value': '', 'confidence': 0.0
                }
                logger.info(f"          WARNING: Field not in response")
        
        except Exception as e:
            logger.error(f"          ERROR: {e}")
            extracted_data[field_name] = {
                'value': '', 'confidence': 0.0
            }
    
    return extracted_data


def _extract_fields_batch(
    fields, chunks, provider, folder,
    openai_manager, search_manager, cost_tracker,
    field_library, system_config, doc_name
) -> Dict:
    """
    Extract fields using Azure Batch API (all fields in one batch job).
    
    Workflow:
      1. RAG search for each field (same as general)
      2. Build all prompts
      3. Submit as single batch job
      4. Wait for completion
      5. Parse results
    
    Cost: 50% cheaper than general API
    Trade-off: Takes minutes-hours instead of seconds
    """
    logger.info(f"      Step 4: Extracting {len(fields)} fields (BATCH API)...")
    
    # Phase 1: Build all batch requests (with RAG search per field)
    batch_requests = []
    field_order = []
    
    for field_idx, field_name in enumerate(fields, 1):
        try:
            field_info = field_library.get(field_name, {})
            field_desc = field_info.get('description', field_name)
            
            logger.info(f"        Field {field_idx}/{len(fields)}: {field_name} (preparing)")
            
            # RAG search (same as general mode)
            field_query_parts = [
                field_name.replace('_', ' '), field_desc
            ]
            hints = field_info.get('extraction_hints', [])
            if hints:
                field_query_parts.append(' '.join(hints[:2]))
            
            field_embedding, query_tokens = openai_manager.generate_embedding(
                ' '.join(field_query_parts)
            )
            cost_tracker.add_embedding(query_tokens)
            
            similar_docs = search_manager.search_similar(
                vector=field_embedding, provider=provider,
                folder=folder, top_k=3
            )
            
            # Build prompt
            prompt = _build_field_prompt(
                field_name=field_name,
                field_info=field_info,
                similar_docs=similar_docs,
                fallback_text=chunks[0]['text'] if chunks else "",
                system_config=system_config
            )
            
            # Create batch request (sanitize custom_id for JSONL safety)
            import re
            safe_doc = re.sub(r'[^a-zA-Z0-9_-]', '_', doc_name)
            safe_field = re.sub(r'[^a-zA-Z0-9_-]', '_', field_name)
            custom_id = f"{safe_doc}_{safe_field}"
            batch_req = openai_manager.create_batch_request(
                custom_id=custom_id,
                prompt=prompt,
                temperature=0.1
            )
            batch_requests.append(batch_req)
            field_order.append(field_name)
            
        except Exception as e:
            logger.error(f"          ERROR preparing {field_name}: {e}")
    
    if not batch_requests:
        logger.error("      No batch requests created")
        return {f: {'value': '', 'confidence': 0.0} for f in fields}
    
    # Phase 2: Submit batch job
    logger.info(f"      Submitting batch job ({len(batch_requests)} requests)...")
    
    try:
        batch_id = openai_manager.submit_batch_job(batch_requests)
        logger.info(f"      Batch job submitted: {batch_id}")
        
        # Phase 3: Wait for completion
        logger.info(f"      Waiting for batch completion...")
        batch_response = openai_manager.wait_for_batch(batch_id)
        
        # Phase 4: Parse results
        logger.info(f"      Parsing batch results...")
        batch_results = openai_manager.parse_batch_results(batch_response)
        
    except Exception as e:
        logger.error(f"      Batch job failed: {e}")
        return {f: {'value': '', 'confidence': 0.0} for f in fields}
    
    # Phase 5: Map results back to fields
    extracted_data = {}
    
    for field_name in fields:
        import re
        safe_doc = re.sub(r'[^a-zA-Z0-9_-]', '_', doc_name)
        safe_field = re.sub(r'[^a-zA-Z0-9_-]', '_', field_name)
        custom_id = f"{safe_doc}_{safe_field}"
        
        if custom_id in batch_results:
            result_data = batch_results[custom_id].get('data', {})
            tokens = batch_results[custom_id].get('tokens', {})
            
            cost_tracker.add_gpt_tokens(
                tokens.get('input_tokens', 0),
                tokens.get('output_tokens', 0)
            )
            
            if field_name in result_data:
                extracted_data[field_name] = result_data[field_name]
                field_result = result_data[field_name]
                if isinstance(field_result, dict):
                    value = field_result.get('value', '')
                    conf = field_result.get('confidence', 0.0)
                    logger.info(f"          {field_name}: {value} (conf: {conf:.2f})")
                elif isinstance(field_result, list):
                    logger.info(f"          {field_name}: {len(field_result)} items extracted")
                else:
                    logger.info(f"          {field_name}: {field_result}")
            else:
                extracted_data[field_name] = {
                    'value': '', 'confidence': 0.0
                }
        else:
            extracted_data[field_name] = {
                'value': '', 'confidence': 0.0
            }
            logger.warning(f"          {field_name}: not found in batch results")
    
    return extracted_data


def _build_field_prompt(
    field_name: str,
    field_info: dict,
    similar_docs: list,
    fallback_text: str,
    system_config: dict
) -> str:
    """
    Build extraction prompt for a single field using RAG-retrieved context.
    
    Args:
        field_name: Name of field to extract
        field_info: Field definition from FIELD_LIBRARY
        similar_docs: RAG search results (relevant chunks)
        fallback_text: Fallback text if no RAG results
        system_config: System prompt configuration
    
    Returns:
        Complete prompt string
    """
    field_desc = field_info.get('description', field_name)
    
    parts = []
    
    # System role
    parts.append(system_config.get('role', 'You are a data extraction assistant.'))
    parts.append("")
    
    # Task
    parts.append(f"TASK: Extract the '{field_name}' field from the document.")
    parts.append("")
    
    # Field definition - UNIVERSAL: reads ANY key from field_info
    parts.append("FIELD DEFINITION:")
    parts.append(f"  Name: {field_name}")
    parts.append(f"  Description: {field_desc}")
    
    cardinality = field_info.get('cardinality', 'single')
    
    # Keys handled specially (with custom formatting)
    SPECIAL_KEYS = {'cardinality', 'description', 'item_fields', 'examples'}
    
    # Process examples with special formatting
    if 'examples' in field_info:
        examples = field_info['examples']
        if isinstance(examples, list) and examples:
            if isinstance(examples[0], dict):
                import json
                parts.append(f"  Example entries:")
                for ex in examples[:2]:
                    parts.append(f"    {json.dumps(ex)}")
            else:
                parts.append(f"  Valid examples: {', '.join(str(e) for e in examples)}")
    
    # Auto-include ALL other keys from field_info
    for key, value in field_info.items():
        if key in SPECIAL_KEYS:
            continue
        
        # Format key nicely: extraction_hints -> Extraction hints
        display_key = key.replace('_', ' ').capitalize()
        
        if isinstance(value, list) and value:
            parts.append(f"  {display_key}:")
            for item in value:
                if isinstance(item, str):
                    parts.append(f"    - {item}")
                elif isinstance(item, dict):
                    import json
                    parts.append(f"    - {json.dumps(item)}")
        elif isinstance(value, dict) and value:
            parts.append(f"  {display_key}:")
            for k, v in value.items():
                parts.append(f"    {k}: {v}")
        elif isinstance(value, str) and value:
            parts.append(f"  {display_key}: {value}")
    
    parts.append("")
    
    # Document context from RAG
    parts.append("DOCUMENT CONTENT (most relevant sections):")
    parts.append("-" * 40)
    
    if similar_docs:
        total_chars = 0
        max_chars = 8000
        
        for idx, doc in enumerate(similar_docs, 1):
            doc_content = doc.get('content', '')
            doc_score = doc.get('score', 0)
            
            if total_chars + len(doc_content) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 200:
                    parts.append(f"\n[Section {idx} (relevance: {doc_score:.2f})]:")
                    parts.append(doc_content[:remaining])
                break
            
            parts.append(f"\n[Section {idx} (relevance: {doc_score:.2f})]:")
            parts.append(doc_content)
            total_chars += len(doc_content)
    else:
        parts.append(fallback_text)
    
    parts.append("-" * 40)
    parts.append("")
    
    # Output format - different for single vs multi cardinality
    cardinality = field_info.get('cardinality', 'single')
    
    if cardinality == 'multi':
        item_fields = field_info.get('item_fields', {})
        parts.append("OUTPUT FORMAT (JSON only, no markdown):")
        parts.append("")
        parts.append("IMPORTANT: Search the ENTIRE document thoroughly for ALL occurrences.")
        parts.append("Look in tables, lists, headers, footers, and all sections.")
        parts.append("Do NOT return empty array if data exists anywhere in the document.")
        parts.append("If truly not found after thorough search, return empty array [].")
        parts.append("")
        parts.append("Return each occurrence as an array item with sequential id:")
        parts.append('{')
        parts.append(f'  "{field_name}": [')
        parts.append('    {')
        parts.append('      "id": 1,')
        for i, (sub_field, sub_desc) in enumerate(item_fields.items()):
            comma = "," if i < len(item_fields) - 1 else ""
            parts.append(f'      "{sub_field}": {{"value": "extracted_value", "confidence": 0.95}}{comma}')
        parts.append('    }')
        parts.append('  ]')
        parts.append('}')
        parts.append("")
        parts.append("Sub-field descriptions:")
        for sub_field, sub_desc in item_fields.items():
            parts.append(f"  - {sub_field}: {sub_desc}")
    else:
        parts.append("OUTPUT FORMAT (JSON only, no markdown):")
        parts.append("Extract the value. If not found, return empty string with confidence 0.0.")
        parts.append("")
        parts.append('{')
        parts.append(f'  "{field_name}": {{')
        parts.append('    "value": "extracted_value",')
        parts.append('    "confidence": 0.00-1.00')
        parts.append('  }')
        parts.append('}')
    parts.append("")
    
    # Rules
    rules = system_config.get('rules', [])
    if rules:
        parts.append("RULES:")
        for rule in rules[:3]:
            parts.append(f"  - {rule}")
    
    return "\n".join(parts)


# =============================================================================
# PARALLEL FIELD EXTRACTION (shared by text_rag and multimodal_rag)
# =============================================================================

def _extract_fields_parallel(
    fields, chunks, provider, folder,
    openai_manager, search_manager, cost_tracker,
    field_library, system_config,
    use_vision=False, image_b64=None, image_format=None,
    max_workers=3, rag_config=None
) -> Dict:
    """
    Extract fields in parallel using ThreadPoolExecutor.
    Same per-field RAG logic, just concurrent.
    Includes retry with backoff for 429 rate limit errors.
    Thread-safe cost tracking with lock.
    Supports reranking via rag_config.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    import time
    
    if rag_config is None:
        rag_config = {}
    
    reranking = rag_config.get('reranking', False)
    reranking_top_k = rag_config.get('reranking_top_k', 10)
    top_k = rag_config.get('top_k', 3)
    
    cost_lock = threading.Lock()
    extracted_data = {}
    completed = {'count': 0}
    total = len(fields)
    retry_stats = {'retries': 0, 'rate_limits': 0}
    
    def extract_single_field(field_name):
        """Extract one field - called by each thread."""
        field_info = field_library.get(field_name, {})
        field_desc = field_info.get('description', field_name)
        
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # RAG search (embedding + vector search)
                field_query_parts = [
                    field_name.replace('_', ' '), field_desc
                ]
                hints = field_info.get('extraction_hints', [])
                if hints:
                    field_query_parts.append(' '.join(hints[:2]))
                
                query_text = ' '.join(field_query_parts)
                
                field_embedding, query_tokens = openai_manager.generate_embedding(query_text)
                
                with cost_lock:
                    cost_tracker.add_embedding(query_tokens)
                
                similar_docs = search_manager.search_similar(
                    vector=field_embedding, provider=provider,
                    folder=folder, top_k=top_k,
                    query_text=query_text if reranking else None,
                    reranking=reranking,
                    reranking_top_k=reranking_top_k
                )
                
                # Build prompt
                if use_vision:
                    from extraction.multimodal_rag import _build_multimodal_prompt
                    prompt = _build_multimodal_prompt(
                        field_name=field_name,
                        field_info=field_info,
                        similar_docs=similar_docs,
                        fallback_text=chunks[0]['text'] if chunks else "",
                        system_config=system_config
                    )
                else:
                    prompt = _build_field_prompt(
                        field_name=field_name,
                        field_info=field_info,
                        similar_docs=similar_docs,
                        fallback_text=chunks[0]['text'] if chunks else "",
                        system_config=system_config
                    )
                
                # GPT extraction
                result, tokens = openai_manager.extract_fields(
                    prompt=prompt, temperature=0.1,
                    use_vision=use_vision,
                    image_base64=image_b64 if use_vision else None,
                    image_format=image_format if use_vision else None
                )
                
                with cost_lock:
                    cost_tracker.add_gpt_tokens(
                        tokens['input_tokens'], tokens['output_tokens']
                    )
                    completed['count'] += 1
                
                return field_name, result
                
            except Exception as e:
                error_str = str(e)
                
                # Rate limit (429) - retry with backoff
                if '429' in error_str or 'rate' in error_str.lower() or 'throttl' in error_str.lower():
                    wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                    retry_stats['retries'] += 1
                    retry_stats['rate_limits'] += 1
                    logger.warning(
                        f"          Rate limit on {field_name}, "
                        f"retry {attempt+1}/{max_retries} in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                
                # Other errors - retry once
                if attempt < max_retries - 1:
                    retry_stats['retries'] += 1
                    logger.warning(f"          Retry {field_name}: {error_str[:100]}")
                    time.sleep(3)
                    continue
                
                logger.error(f"          FAILED {field_name}: {error_str[:150]}")
                with cost_lock:
                    completed['count'] += 1
                return field_name, None
        
        return field_name, None
    
    # Submit all fields to thread pool
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for field_name in fields:
            future = executor.submit(extract_single_field, field_name)
            futures[future] = field_name
        
        # Collect results as they complete
        for future in as_completed(futures):
            field_name = futures[future]
            try:
                name, result = future.result()
                
                if result and name in result:
                    extracted_data[name] = result[name]
                    field_result = result[name]
                    if isinstance(field_result, dict):
                        value = field_result.get('value', '')
                        conf = field_result.get('confidence', 0.0)
                        logger.info(
                            f"        [{completed['count']}/{total}] "
                            f"{name}: {value} (conf: {conf:.2f})"
                        )
                    elif isinstance(field_result, list):
                        logger.info(
                            f"        [{completed['count']}/{total}] "
                            f"{name}: {len(field_result)} items"
                        )
                else:
                    extracted_data[field_name] = {'value': '', 'confidence': 0.0}
                    logger.info(
                        f"        [{completed['count']}/{total}] "
                        f"{field_name}: no result"
                    )
            except Exception as e:
                extracted_data[field_name] = {'value': '', 'confidence': 0.0}
                logger.error(f"        {field_name}: thread error: {e}")
    
    elapsed = time.time() - start_time
    logger.info(
        f"      Parallel extraction complete: {len(extracted_data)}/{total} fields "
        f"in {elapsed:.1f}s ({max_workers} workers, {retry_stats['retries']} retries, "
        f"{retry_stats['rate_limits']} rate limits)"
    )
    
    return extracted_data
