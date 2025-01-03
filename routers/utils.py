import bleach


def clean_student_answer(text: str) -> str:
    """
    Clean and standardize student answer text.
    Removes HTML tags and converts to lowercase.
    """
    # Configure bleach to strip all HTML tags
    cleaned_text = bleach.clean(text, tags=[], strip=True)

    # Convert to lowercase
    cleaned_text = cleaned_text.lower()

    return cleaned_text.strip()
