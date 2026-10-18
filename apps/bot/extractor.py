import json
import logging
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
  "option_f": "...",
  "correct_option": "a",
  "explanation": ""
}

question_type must be one of these five values:

1. "mcq" — Multiple choice question with up to six labeled options (A through F)
   - Fill the options shown, including option_e and option_f when present
   - Set correct_option to "a", "b", "c", "d", "e", or "f" (lowercase)
   - Leave correct_option as empty string if answer not shown

2. "true_false" — Question answered with True or False
   - Set option_a to "True", option_b to "False"
   - Set option_c, option_d, option_e, option_f to empty string
   - Set correct_option to "a" if answer is True, "b" if answer is False
   - Leave correct_option as empty string if answer not shown

3. "fill_blank" — Sentence with a blank (___) to fill in
   - Set option_a through option_f all to empty string
   - Put the correct answer in correct_option as text (e.g. "photosynthesis")
   - Leave correct_option as empty string if answer not shown

4. "matching" — Match items from two columns
   - Each option represents one pair, written as "Left term → Right answer"
   - Example: option_a = "Keyboard → Input device"
   - Set correct_option to empty string (matching has no single correct option)

5. "essay" — Open-ended question asking student to explain, discuss, describe, or write
   - Set option_a through option_f all to empty string
   - Set correct_option to empty string
   - Put any model answer or marking guide in explanation if visible

Rules:
- Extract EVERY question you find in the order it appears
- Questions are numbered like 1. 2. 3. or I. II. III. or Part A, Part B etc
- Clean up OCR errors where obvious (joined words, wrong spacing)
- Leave unused options empty (for four choices, option_e and option_f are empty)
- Return ONLY the JSON array, nothing else

Text to extract from:
"""


EXTRACTION_VERSION = 'questions-v3'


def validate_questions(questions):
    if not isinstance(questions, list) or len(questions) > settings.AI_MAX_QUESTIONS:
        raise ValueError('AI output must be a bounded question list.')
    valid_types = {'mcq', 'true_false', 'fill_blank', 'matching', 'essay'}
    cleaned = []
    for row in questions:
        if not isinstance(row, dict) or row.get('question_type') not in valid_types:
            raise ValueError('AI returned an invalid question type/shape.')
        result = {'question_type': row['question_type']}
        for field, limit in [('question', 20000), ('correct_option', 100), ('explanation', 10000),
                             *[(f'option_{letter}', 500) for letter in 'abcdef']]:
            value = row.get(field, '')
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'AI returned an invalid {field}.')
            result[field] = value.strip()
        if not result['question']:
            raise ValueError('AI returned an empty question.')
        if result['question_type'] in {'mcq', 'true_false'}:
            correct = result['correct_option'].lower()
            allowed = 'ab' if result['question_type'] == 'true_false' else 'abcdef'
            if correct and (correct not in allowed or len(correct) != 1 or not result[f'option_{correct}']):
                raise ValueError('AI returned an answer without a matching option.')
            result['correct_option'] = correct
        cleaned.append(result)
    return cleaned


def extract_questions_from_text(raw_text):
    if not raw_text or len(raw_text.strip()) < 50:
        raise ValueError('Text too short for question extraction.')
    if len(raw_text) > settings.AI_MAX_INPUT_CHARS:
        raise ValueError('AI input exceeds the configured size limit; split the document.')
    questions = []
    for start in range(0, len(raw_text), 8000):
        questions.extend(_extract_from_chunk(settings.GEMINI_API_KEY, raw_text[start:start + 8000]))
    return validate_questions(questions)


def _extract_from_chunk(api_key, text_chunk):
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY is not configured.')
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60000))
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL, contents=EXTRACTION_PROMPT + text_chunk,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=8000,
                                           response_mime_type='application/json'),
    )
    content = response.text or ''
    if len(content) > 1000000:
        raise ValueError('AI response exceeds the output limit.')
    # Incomplete JSON is a visible failure; never publish a silently truncated set.
    try:
        return validate_questions(json.loads(content))
    except json.JSONDecodeError as exc:
        raise ValueError('AI returned incomplete or invalid JSON; manual review required.') from exc
