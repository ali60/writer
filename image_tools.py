"""Placeholder image tools for editorial workflow."""

def search_images(query: str, max_results: int = 5):
    """Placeholder for image search."""
    return []

def insert_image_markdown(image_url: str, alt_text: str, caption: str = ""):
    """Placeholder for image markdown insertion."""
    return f"![{alt_text}]({image_url})\n{caption}\n" if caption else f"![{alt_text}]({image_url})\n"
