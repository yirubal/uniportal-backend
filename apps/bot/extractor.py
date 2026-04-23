import json
import logging
import time
from datetime import datetime  # use datetime instead if you need it
from django.conf import settings

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """
You are an expert at extracting exam questions from Ethiopian university exam papers.

Extract ALL questions from the text below — do not skip any question regardless of its type.
Return ONLY a valid JSON array. No explanation, no markdown, no backticks.

Each question object must have exactly these fields:
{
  "question_type": "mcq",
  "question": "the full question text",
  "option_a": "...",
  "option_b": "...",
  "option_c": "...",
  "option_d": "...",
  "option_e": "...",
  "correct_option": "a",
  "explanation": ""
}

question_type must be one of these five values:

1. "mcq" — Multiple choice question with labeled options (A B C D or A B C D E)
   - Fill option_a through option_d (and option_e if 5 options exist)
   - Set correct_option to "a", "b", "c", "d", or "e" (lowercase)
   - Leave correct_option as empty string if answer not shown

2. "true_false" — Question answered with True or False
   - Set option_a to "True", option_b to "False"
   - Set option_c, option_d, option_e to empty string
   - Set correct_option to "a" if answer is True, "b" if answer is False
   - Leave correct_option as empty string if answer not shown

3. "fill_blank" — Sentence with a blank (___) to fill in
   - Set option_a through option_e all to empty string
   - Put the correct answer in correct_option as text (e.g. "photosynthesis")
   - Leave correct_option as empty string if answer not shown

4. "matching" — Match items from two columns
   - Each option represents one pair, written as "Left term → Right answer"
   - Example: option_a = "Keyboard → Input device"
   - Set correct_option to empty string (matching has no single correct option)

5. "essay" — Open-ended question asking student to explain, discuss, describe, or write
   - Set option_a through option_e all to empty string
   - Set correct_option to empty string
   - Put any model answer or marking guide in explanation if visible

Rules:
- Extract EVERY question you find in the order it appears
- Questions are numbered like 1. 2. 3. or I. II. III. or Part A, Part B etc
- Clean up OCR errors where obvious (joined words, wrong spacing)
- If a question has only 4 options leave option_e as empty string
- Return ONLY the JSON array, nothing else

Text to extract from:
"""


def extract_questions_from_text(raw_text: str) -> list[dict]:
    """
    Sends raw extracted text to Groq AI and returns structured
    list of question dicts supporting mcq, true_false, fill_blank,
    matching, and essay types.
    For large texts processes in chunks of 8000 chars.
    """
    if not raw_text or len(raw_text.strip()) < 50:
        logger.warning('Text too short for question extraction')
        return []

    api_key = settings.GROQ_API_KEY
    if not api_key:
        logger.error('GROQ_API_KEY not configured')
        return []

    chunk_size = 8000
    chunks = [
        raw_text[i:i + chunk_size]
        for i in range(0, len(raw_text), chunk_size)
    ]

    logger.info(f'Processing {len(chunks)} chunk(s) from {len(raw_text)} chars')

    all_questions = []
    for chunk_index, chunk in enumerate(chunks):
        logger.info(f'Processing chunk {chunk_index + 1} of {len(chunks)}')

        # Wait between chunks to avoid Groq rate limiting
        if chunk_index > 0:
            time.sleep(60)  # wait 60 seconds between chunks
        questions = _extract_from_chunk(api_key, chunk)
        all_questions.extend(questions)

    logger.info(f'Total extracted: {len(all_questions)} questions')
    return all_questions


def _extract_from_chunk(api_key: str, text_chunk: str) -> list[dict]:
    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {
                    'role': 'user',
                    'content': EXTRACTION_PROMPT + text_chunk,
                }
            ],
            temperature=0.1,
            max_tokens=8000,
        )

        content = response.choices[0].message.content.strip()
        logger.info(f'AI response (first 200 chars): {content[:200]}')

        # Strip markdown code fences if present
        if '```' in content:
            parts = content.split('```')
            for part in parts:
                if part.startswith('json'):
                    content = part[4:].strip()
                    break
                elif part.strip().startswith('['):
                    content = part.strip()
                    break

        content = content.strip()

        # Fix truncated JSON
        if not content.endswith(']'):
            last_complete = content.rfind('},')
            if last_complete != -1:
                content = content[:last_complete + 1] + ']'
                logger.warning('Fixed truncated JSON response')
            else:
                logger.error('Could not fix truncated JSON')
                return []

        questions = json.loads(content)

        if not isinstance(questions, list):
            logger.error('AI returned non-list response')
            return []

        valid_questions = []
        valid_types = {'mcq', 'true_false', 'fill_blank', 'matching', 'essay'}

        for q in questions:
            # Must have a question text
            if not q.get('question', '').strip():
                logger.warning(f'Skipping question with no text: {q}')
                continue

            # Normalize question_type
            q_type = q.get('question_type', '').strip().lower()
            if q_type not in valid_types:
                # Try to guess the type if AI returned something unexpected
                q_type = _guess_type(q)
                logger.warning(f'Unknown type "{q.get("question_type")}", guessed "{q_type}"')
            q['question_type'] = q_type

            # Ensure all option fields exist
            for opt in ['option_a', 'option_b', 'option_c', 'option_d', 'option_e']:
                if opt not in q:
                    q[opt] = ''
                q[opt] = (q[opt] or '').strip()

            # Normalize correct_option
            correct = q.get('correct_option', '')

            if q_type == 'mcq' or q_type == 'true_false':
                # Must be a single letter a-e
                correct = str(correct).lower().strip()
                if correct not in ['a', 'b', 'c', 'd', 'e']:
                    correct = ''

            elif q_type == 'fill_blank':
                # correct_option holds the answer text — keep as-is
                correct = str(correct).strip()

            elif q_type in ('matching', 'essay'):
                # No correct_option for these types
                correct = ''

            q['correct_option'] = correct

            # Ensure true_false always has the right options
            if q_type == 'true_false':
                q['option_a'] = 'True'
                q['option_b'] = 'False'
                q['option_c'] = ''
                q['option_d'] = ''
                q['option_e'] = ''

            # Ensure explanation field exists
            if 'explanation' not in q:
                q['explanation'] = ''
            q['explanation'] = (q['explanation'] or '').strip()

            valid_questions.append(q)

        logger.info(f'Valid questions from chunk: {len(valid_questions)}')
        _log_type_summary(valid_questions)
        return valid_questions

    except json.JSONDecodeError as e:
        logger.error(f'JSON parse error: {e}')
        return []
    except Exception as e:
        logger.error(f'Chunk extraction failed: {e}')
        return []


def _guess_type(q: dict) -> str:
    """
    Fallback type guesser when AI returns an unrecognized question_type.
    """
    text = q.get('question', '').lower()
    option_a = q.get('option_a', '').lower().strip()

    if option_a in ('true', 'false'):
        return 'true_false'
    if '___' in text or '____' in text or 'fill in' in text:
        return 'fill_blank'
    if any(word in text for word in ('explain', 'discuss', 'describe', 'write', 'elaborate', 'analyze')):
        return 'essay'
    if q.get('option_a') and '→' in q.get('option_a', ''):
        return 'matching'
    if q.get('option_a') and q.get('option_b'):
        return 'mcq'
    return 'essay'


def _log_type_summary(questions: list[dict]):
    """Log a breakdown of extracted question types for debugging."""
    from collections import Counter
    counts = Counter(q.get('question_type') for q in questions)
    summary = ', '.join(f'{t}: {c}' for t, c in sorted(counts.items()))
    logger.info(f'Question types — {summary}')