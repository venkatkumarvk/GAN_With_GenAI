"""
Pure LLM-as-Judge Evaluator
=============================

UNIVERSAL: No hardcoded rules. LLM evaluates everything based on guidelines.
Guidelines come from eval_prompt module (prompts/evaluation/xxx_eval_prompt.py).

For new fields/doctypes: only edit eval_prompt file. Never touch this file.

Output:
  - Value exists + no issues → eval_score: 1.0, eval_description: "No issues found"
  - Value exists + issues    → eval_score: 0.0-0.99, eval_description: "issue details"
  - Value empty              → no eval_score, no eval_description
"""

import json
import logging
import os
import sys
from typing import Dict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

logger = logging.getLogger(__name__)


class LLMJudge:
    """Pure LLM-as-Judge. LLM decides scores based on guidelines from eval_prompt."""
    
    def __init__(self, config: dict = None, eval_prompt_module=None):
        self.client = None
        self.deployment = None
        self.guidelines = {}
        self.system_prompt = ""
        
        if eval_prompt_module:
            self.guidelines = getattr(eval_prompt_module, 'FIELD_EVALUATION_GUIDELINES', {})
            self.system_prompt = getattr(eval_prompt_module, 'JUDGE_SYSTEM_PROMPT', '')
            eval_cfg = getattr(eval_prompt_module, 'EVALUATION_CONFIG', {})
            self.model = eval_cfg.get('model', 'gpt-5')
            self.max_tokens = eval_cfg.get('max_tokens', 4000)
            self.temperature = eval_cfg.get('temperature', 0.0)
        else:
            self.model = 'gpt-5'
            self.max_tokens = 4000
            self.temperature = 0.0
        
        if config:
            self._init_client(config)
    
    def _init_client(self, config: dict):
        """Initialize Azure OpenAI client."""
        try:
            from openai import AzureOpenAI
            eval_config = config.get('azure_openai', {})
            if eval_config.get('endpoint') and eval_config.get('api_key'):
                self.client = AzureOpenAI(
                    azure_endpoint=eval_config['endpoint'],
                    api_key=eval_config['api_key'],
                    api_version=eval_config.get('api_version', '2024-12-01-preview')
                )
                self.deployment = eval_config.get('deployment', self.model)
                logger.info(f"LLM Judge initialized: deployment={self.deployment}")
        except ImportError:
            logger.warning("LLM Judge: openai not installed")
    
    def set_client(self, client, deployment: str):
        """Set client manually."""
        self.client = client
        self.deployment = deployment
    
    def evaluate_and_enrich(self, extracted_data: dict) -> dict:
        """
        Evaluate fields using LLM and add eval_score + eval_description.
        
        - Value exists: LLM evaluates → eval_score + eval_description
        - Value empty: no eval_score, no eval_description added
        """
        for field_name, field_data in extracted_data.items():
            guideline = self.guidelines.get(field_name, {})
            
            # Single-value field
            if isinstance(field_data, dict) and 'value' in field_data:
                value = field_data.get('value', '')
                if not value:
                    field_data['eval_score'] = ''
                    field_data['eval_description'] = ''
                    continue
                
                result = self._evaluate_value(field_name, value, guideline)
                field_data['eval_score'] = result['score']
                field_data['eval_description'] = result['description']
            
            # Multi-value field
            elif isinstance(field_data, list):
                if not field_data:
                    continue
                
                sub_field_rules = guideline.get('sub_field_rules', {})
                
                for item in field_data:
                    if not isinstance(item, dict):
                        continue
                    for sub_field, sub_data in item.items():
                        if sub_field == 'id':
                            continue
                        if not isinstance(sub_data, dict):
                            continue
                        if not sub_data.get('value'):
                            sub_data['eval_score'] = ''
                            sub_data['eval_description'] = ''
                            continue
                        
                        sub_guideline = sub_field_rules.get(sub_field, [])
                        result = self._evaluate_value(
                            f"{field_name}.{sub_field}", 
                            sub_data['value'],
                            {'rules': sub_guideline} if isinstance(sub_guideline, list) else sub_guideline
                        )
                        sub_data['eval_score'] = result['score']
                        sub_data['eval_description'] = result['description']
                
                # Check duplicates
                dup_indices = self._find_duplicate_indices(field_data)
                if dup_indices:
                    dup_msg = guideline.get('rules', [{}])
                    dup_message = "Duplicate entry detected"
                    for r in (dup_msg if isinstance(dup_msg, list) else []):
                        if r.get('type') == 'no_duplicates':
                            dup_message = r.get('message', dup_message)
                    
                    for idx in dup_indices:
                        item = field_data[idx]
                        for sub_field, sub_data in item.items():
                            if sub_field == 'id':
                                continue
                            if isinstance(sub_data, dict):
                                sub_data['eval_score'] = 0.25
                                sub_data['eval_description'] = dup_message
        
        return extracted_data
    
    def _evaluate_value(self, field_name: str, value: str, guideline: dict) -> dict:
        """
        Evaluate a single value. Uses LLM if available, otherwise returns default.
        
        Returns:
            {"score": 1.0, "description": "No issues found"}
            or {"score": 0.5, "description": "issue details"}
        """
        if not guideline:
            return {'score': 1.0, 'description': 'No issues found'}
        
        # Use LLM if available
        if self.client:
            llm_result = self._call_llm(field_name, value, guideline)
            if llm_result:
                score = llm_result.get('score', 1.0)
                issues = llm_result.get('issues', [])
                if score >= 1.0 or not issues:
                    return {'score': 1.0, 'description': 'No issues found'}
                return {
                    'score': round(score, 2),
                    'description': '; '.join(issues) if issues else 'No issues found'
                }
        
        # No LLM available - return default (evaluation couldn't run fully)
        return {'score': 1.0, 'description': 'No issues found'}
    
    def _call_llm(self, field_name: str, value: str, guideline: dict) -> dict:
        """Send field to LLM for evaluation."""
        try:
            expected_format = guideline.get('expected_format', '')
            rules = guideline.get('rules', [])
            sub_field_rules = guideline.get('sub_field_rules', {})
            
            # Build evaluation prompt
            rules_text = ""
            if isinstance(rules, list) and rules:
                rules_text = "\n".join([f"  - {r.get('message', r.get('type', ''))}" for r in rules])
            elif isinstance(rules, dict):
                rules_text = json.dumps(rules)
            
            prompt = f"""Evaluate this extracted value against the guidelines.

Field: {field_name}
Extracted Value: "{value}"
Expected Format: {expected_format}
Validation Rules:
{rules_text}

Score the value:
  1.0  = Perfect, correct format, no issues
  0.75 = Minor format issue (extra spaces, case)
  0.50 = Wrong format but correct data (e.g., "New York" instead of "NY")
  0.25 = Major issue (wrong format, partially correct)
  0.0  = Wrong value or hallucinated

Respond ONLY with JSON:
{{"score": 0.0-1.0, "issues": ["list of issues or empty if none"], "suggestion": "fix or empty"}}"""

            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": self.system_prompt or "You are a data quality evaluator. Respond in JSON only."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            content = response.choices[0].message.content
            if not content:
                return None
            
            # Parse JSON
            clean = content.strip()
            start = clean.find('{')
            end = clean.rfind('}')
            if start != -1 and end != -1:
                return json.loads(clean[start:end+1])
            return None
            
        except Exception as e:
            logger.warning(f"LLM Judge failed for {field_name}: {e}")
            return None
    
    def _find_duplicate_indices(self, items: list) -> list:
        """Find indices of duplicate items (keep first, mark rest)."""
        signatures = {}
        duplicates = []
        
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            sig_parts = []
            for key, val in sorted(item.items()):
                if key == 'id':
                    continue
                if isinstance(val, dict):
                    v = str(val.get('value', '')).strip().lower()
                    if v and 'date' not in key and 'status' not in key:
                        sig_parts.append(v)
            sig = '|'.join(sig_parts)
            if not sig:
                continue
            if sig in signatures:
                duplicates.append(idx)
            else:
                signatures[sig] = idx
        
        return duplicates


def load_eval_prompt_module(module_path: str):
    """Load evaluation prompt module dynamically."""
    try:
        parts = module_path.split('.')
        return __import__(module_path, fromlist=[parts[-1]])
    except ImportError:
        logger.warning(f"Eval prompt module not found: {module_path}")
        return None
