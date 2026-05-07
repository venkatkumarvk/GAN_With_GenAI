"""
Multimodal RAG Extraction Module
==================================

Text + Vision extraction pipeline:
  OCR -> Semantic Chunking -> Embedding -> AI Search Index ->
  Per-field RAG Search -> Convert page to image ->
  GPT Vision (text + image) Extraction

Config: rag.mode = "multimodal"

Same as text_rag.py EXCEPT at the GPT extraction step:
  - text_rag: sends only text chunks to GPT
  - multimodal_rag: sends text chunks AND the document page image to GPT Vision

RAG search is ALWAYS text-based (AI Search indexes text, not images).
The image is added at the GPT call for visual context (handwriting,
checkboxes, stamps, signatures, table layouts).

Adding new document types:
  1. Create new prompt file in prompts/ (copy cred_prompt.py as template)
  2. Add doctype entry in config.json with folder_configs and fields
  3. Done - this module adapts automatically via prompt_module parameter
"""

import logging
import hashlib
import base64
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def process_document_multimodal_rag(
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
    Extract fields using multimodal RAG (text + vision).
    
    Note: Batch API is NOT supported for multimodal mode because
    Note: Batch API supports multimodal (text + image) inputs.
    Images are embedded as base64 in the JSONL request body.
    
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
    
    Returns:
        (extracted_data, success)
    """
    logger.info(f"    Document: {doc_name} - Multimodal RAG extraction (text + vision)")
    
    # ========================================================================
    # STEP 1: OCR (text extraction for RAG search - same as text mode)
    # ========================================================================
    text, pages, success = ocr.extract_text(doc_bytes, extension)
    
    if not success or len(text) < 100:
        logger.warning(f"      FAILED: Insufficient text from OCR")
        return {}, False
    
    cost_tracker.add_ocr(pages)
    logger.info(f"      Step 1: OCR complete ({len(text)} chars, {pages} pages)")
    
    # ========================================================================
    # STEP 2: CONVERT DOCUMENT TO IMAGES (for vision)
    # ========================================================================
    page_images = _convert_to_images(doc_bytes, doc_name, extension)
    
    if not page_images:
        logger.warning(f"      Could not convert to images, falling back to text-only")
        # Fall back to text-only extraction
        from extraction.text_rag import process_document_text_rag
        return process_document_text_rag(
            doc_bytes, doc_name, extension, provider, folder,
            fields, ocr, openai_manager, search_manager,
            cost_tracker, prompt_module
        )
    
    logger.info(f"      Step 2: Converted to {len(page_images)} page image(s)")
    
    # Use first page image for per-field extraction
    # (most credential documents have key info on page 1)
    primary_image_b64 = page_images[0]['base64']
    primary_image_format = page_images[0]['format']
    
    # ========================================================================
    # STEP 3: SEMANTIC CHUNKING + INDEXING (same as text mode)
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
    logger.info(f"      Step 3a: {summary['total_chunks']} chunks "
               f"({summary['total_text_length']} chars)")
    
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
    
    logger.info(f"      Step 3b: Indexed {uploaded_chunks}/{len(chunks)} chunks")
    
    # ========================================================================
    # STEP 4: EXTRACT FIELDS
    # ========================================================================
    FIELD_LIBRARY = getattr(prompt_module, 'FIELD_LIBRARY', {})
    SYSTEM_PROMPT_CONFIG = getattr(prompt_module, 'SYSTEM_PROMPT_CONFIG', {})
    
    if api_type == 'batch':
        extracted_data = _extract_fields_multimodal_batch(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            FIELD_LIBRARY, SYSTEM_PROMPT_CONFIG,
            primary_image_b64, primary_image_format, doc_name
        )
    else:
        extracted_data = _extract_fields_multimodal_general(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            FIELD_LIBRARY, SYSTEM_PROMPT_CONFIG,
            primary_image_b64, primary_image_format,
            parallel_workers=parallel_workers,
            rag_config=rag_config or {}
        )
    
    logger.info(
        f"      Step 4 complete: {len(extracted_data)}/{len(fields)} fields"
    )
    
    return extracted_data, True


def _extract_fields_multimodal_general(
    fields, chunks, provider, folder,
    openai_manager, search_manager, cost_tracker,
    field_library, system_config,
    image_b64, image_format, parallel_workers=1,
    rag_config=None
) -> Dict:
    """Extract fields using real-time General API with vision. Supports parallel + reranking."""
    if rag_config is None:
        rag_config = {}
    
    reranking = rag_config.get('reranking', False)
    reranking_top_k = rag_config.get('reranking_top_k', 10)
    top_k = rag_config.get('top_k', 3)
    
    if parallel_workers > 1:
        from extraction.text_rag import _extract_fields_parallel
        mode = "RERANKING" if reranking else "MULTIMODAL GENERAL"
        logger.info(f"      Step 4: Extracting {len(fields)} fields ({mode}, {parallel_workers} parallel workers)...")
        return _extract_fields_parallel(
            fields, chunks, provider, folder,
            openai_manager, search_manager, cost_tracker,
            field_library, system_config,
            use_vision=True, image_b64=image_b64, image_format=image_format,
            max_workers=parallel_workers,
            rag_config=rag_config
        )
    
    mode = "RERANKING" if reranking else "MULTIMODAL GENERAL"
    logger.info(f"      Step 4: Extracting {len(fields)} fields ({mode})...")
    
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
            
            # Build prompt and extract with vision
            prompt = _build_multimodal_prompt(
                field_name=field_name,
                field_info=field_info,
                similar_docs=similar_docs,
                fallback_text=chunks[0]['text'] if chunks else "",
                system_config=system_config
            )
            
            result, tokens = openai_manager.extract_fields(
                prompt=prompt, temperature=0.1,
                use_vision=True,
                image_base64=image_b64,
                image_format=image_format
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


def _extract_fields_multimodal_batch(
    fields, chunks, provider, folder,
    openai_manager, search_manager, cost_tracker,
    field_library, system_config,
    image_b64, image_format, doc_name
) -> Dict:
    """
    Extract fields using Batch API with vision (text + image in JSONL).
    
    Each batch request includes the base64 image alongside the text prompt,
    matching the Azure Batch API multimodal format.
    """
    logger.info(f"      Step 4: Extracting {len(fields)} fields (MULTIMODAL BATCH)...")
    
    import re
    
    # Phase 1: Build batch requests with image
    batch_requests = []
    field_order = []
    
    for field_idx, field_name in enumerate(fields, 1):
        try:
            field_info = field_library.get(field_name, {})
            field_desc = field_info.get('description', field_name)
            
            logger.info(f"        Field {field_idx}/{len(fields)}: {field_name} (preparing)")
            
            # RAG search
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
            prompt = _build_multimodal_prompt(
                field_name=field_name,
                field_info=field_info,
                similar_docs=similar_docs,
                fallback_text=chunks[0]['text'] if chunks else "",
                system_config=system_config
            )
            
            # Build multimodal batch request (text + image in content array)
            safe_doc = re.sub(r'[^a-zA-Z0-9_-]', '_', doc_name)
            safe_field = re.sub(r'[^a-zA-Z0-9_-]', '_', field_name)
            custom_id = f"{safe_doc}_{safe_field}"
            
            deployment = openai_manager.batch_deployment or openai_manager.gpt_deployment
            
            batch_req = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/chat/completions",
                "body": {
                    "model": deployment,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": [
                            {
                                "type": "text",
                                "text": "Extract the field from this document. Use both the OCR text above and the attached image."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{image_format};base64,{image_b64}"
                                }
                            }
                        ]}
                    ],
                    "max_completion_tokens": 4000
                }
            }
            
            batch_requests.append(batch_req)
            field_order.append(field_name)
            
        except Exception as e:
            logger.error(f"          ERROR preparing {field_name}: {e}")
    
    if not batch_requests:
        logger.error("      No batch requests created")
        return {f: {'value': '', 'confidence': 0.0} for f in fields}
    
    # Phase 2: Submit batch job
    logger.info(f"      Submitting multimodal batch job ({len(batch_requests)} requests)...")
    
    try:
        batch_id = openai_manager.submit_batch_job(batch_requests)
        logger.info(f"      Batch job submitted: {batch_id}")
        
        batch_response = openai_manager.wait_for_batch(batch_id)
        
        logger.info(f"      Parsing batch results...")
        batch_results = openai_manager.parse_batch_results(batch_response)
        
    except Exception as e:
        logger.error(f"      Batch job failed: {e}")
        return {f: {'value': '', 'confidence': 0.0} for f in fields}
    
    # Phase 3: Map results back
    extracted_data = {}
    
    for field_name in fields:
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


def _convert_to_images(
    doc_bytes: bytes, doc_name: str, extension: str
) -> List[Dict]:
    """
    Convert document to base64-encoded page images.
    
    Returns:
        List of {'base64': str, 'format': str, 'page': int}
        Empty list if conversion fails
    """
    try:
        ext = extension.lower().strip('.')
        
        # Already an image - encode directly
        image_extensions = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp']
        if ext in image_extensions:
            b64 = base64.b64encode(doc_bytes).decode('utf-8')
            fmt = ext.replace('jpg', 'jpeg')
            return [{'base64': b64, 'format': fmt, 'page': 1}]
        
        # PDF or Office - convert pages to images
        if ext in ['pdf', 'docx', 'doc', 'tiff', 'tif']:
            from services.document_converter import DocumentConverter
            converter = DocumentConverter(dpi=200)
            images = converter.convert_to_images(doc_bytes, doc_name)
            
            if not images:
                return []
            
            result = []
            for img_bytes, page_info in images:
                b64 = base64.b64encode(img_bytes).decode('utf-8')
                page_num = int(page_info.replace('page_', '').replace('image', '1'))
                result.append({
                    'base64': b64,
                    'format': 'png',
                    'page': page_num
                })
            
            return result
        
        return []
        
    except Exception as e:
        logger.error(f"Document to image conversion failed: {e}")
        return []


def _build_multimodal_prompt(
    field_name: str,
    field_info: dict,
    similar_docs: list,
    fallback_text: str,
    system_config: dict
) -> str:
    """
    Build extraction prompt for multimodal mode.
    
    Same as text mode prompt but adds instruction to use the attached image
    for visual verification (handwriting, checkboxes, stamps, layouts).
    """
    field_desc = field_info.get('description', field_name)
    
    parts = []
    
    # System role
    parts.append(system_config.get('role', 'You are a data extraction assistant.'))
    parts.append("")
    
    # Task (multimodal-specific instruction)
    parts.append(f"TASK: Extract the '{field_name}' field from the document.")
    parts.append("You have both the OCR text AND the original document image.")
    parts.append("Use the image to verify handwritten text, checkboxes, stamps,")
    parts.append("signatures, and any visual elements that OCR may have missed.")
    parts.append("")
    
    # Field definition - UNIVERSAL: reads ANY key from field_info
    parts.append("FIELD DEFINITION:")
    parts.append(f"  Name: {field_name}")
    parts.append(f"  Description: {field_desc}")
    
    # Keys handled specially
    SPECIAL_KEYS = {'cardinality', 'description', 'item_fields', 'examples'}
    
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
    
    # Document context from RAG (text-based)
    parts.append("OCR TEXT (from relevant sections):")
    parts.append("-" * 40)
    
    if similar_docs:
        total_chars = 0
        max_chars = 6000  # Slightly smaller than text mode (image takes tokens too)
        
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
        parts.append(fallback_text[:3000] if fallback_text else "")
    
    parts.append("-" * 40)
    parts.append("")
    
    # Vision instruction
    parts.append("IMPORTANT: Also examine the attached document IMAGE carefully.")
    parts.append("The image may contain information not captured by OCR, such as")
    parts.append("handwritten entries, checked boxes, stamps, or visual layouts.")
    parts.append("")
    
    # Output format - different for single vs multi cardinality
    cardinality = field_info.get('cardinality', 'single')
    
    if cardinality == 'multi':
        item_fields = field_info.get('item_fields', {})
        parts.append("OUTPUT FORMAT (JSON only, no markdown):")
        parts.append("")
        parts.append("IMPORTANT: Search the ENTIRE document AND the attached image thoroughly.")
        parts.append("Look in tables, lists, headers, footers, and all sections.")
        parts.append("Do NOT return empty array if data exists anywhere in the document or image.")
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
        parts.append('    }')
        parts.append('  ]')
        parts.append('}')
    else:
        parts.append("OUTPUT FORMAT (JSON only, no markdown):")
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
