"""Contextual Embedding: Kontextsatz + Chunk-Text zum Embedding-Input (#109).

Der Kontextsatz kommt seit #632 ausschliesslich aus dem deterministischen
Offline-Default :func:`academic_vault.chunking.default_context_sentence` — die
frueher hier angebundene Generierung ueber das Anthropic-SDK ist entfallen,
weil keine Plugin-Funktion einen eigenen ``ANTHROPIC_API_KEY`` voraussetzen
darf.
"""


def build_contextual_embedding_text(
    context_sentence: str,
    chunk_text: str,
) -> str:
    """Kombiniert context_sentence und chunk_text zu Embedding-Input.

    Der Kontext-Satz kommt VOR dem Chunk-Text, damit das Embedding
    den Chunk im Kontext des Papers repraesentiert.

    Args:
        context_sentence: 1-Satz-Kontext, z.B. aus
            :func:`academic_vault.chunking.default_context_sentence`.
        chunk_text: Originaler Chunk-Text aus dem Paper.

    Returns:
        Kombinierter Text fuer Embedding: "<context_sentence> <chunk_text>"
    """
    return f"{context_sentence} {chunk_text}"
