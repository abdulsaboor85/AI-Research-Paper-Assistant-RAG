"""
chunker.py  -  cut a paper into small pieces called "chunks".

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
A whole paper is too big to search at once, so we cut it into small pieces
(about 300 letters each). Neighbouring pieces SHARE 50 letters, so a sentence
that falls on the cut is not lost. We prefer to cut at a paragraph, then a line,
then a space.

FUNCTION GUIDE
------------------------------------------------------------
   chunk_text    cut the text into a list of chunks
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
SEPARATORS = ["\n\n", "\n", " "]


def chunk_text(text):
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE,
                                              chunk_overlap=CHUNK_OVERLAP,
                                              separators=SEPARATORS)
    return splitter.split_text(text)