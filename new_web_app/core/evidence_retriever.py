"""
Evidence Retriever for RAG-based Question Generation

Uses ChromaDB for semantic search over extracted chapter files.
Provides evidence packs with main sources, updates, and sibling entities.
"""

import os
import re
from glob import glob
from dataclasses import dataclass, field
from typing import Optional

def normalize_turkish(text: str) -> str:
    """Properly lowercases Turkish strings handling I/ı and İ/i."""
    if not text:
        return ""
    translation_table = str.maketrans("İI", "iı")
    return text.translate(translation_table).lower()


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class EvidenceChunk:
    """A single chunk of evidence text."""
    text: str
    source_file: str
    chunk_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class EvidencePack:
    """Collection of evidence for a generation request."""
    main_evidence: list[EvidenceChunk] = field(default_factory=list)
    update_evidence: list[EvidenceChunk] = field(default_factory=list)
    sibling_evidence: list[EvidenceChunk] = field(default_factory=list)
    # New: Tracking scope
    scope: dict = field(default_factory=dict) # {source: ..., topic: ...}
    
    def get_main_text(self, max_chars: int = 8000) -> str:
        """Get concatenated main evidence text."""
        if not self.main_evidence:
            return ""
        text = "\n\n---\n\n".join([c.text for c in self.main_evidence])
        return text[:max_chars]
    
    def get_update_text(self, max_chars: int = 4000) -> str:
        """Get concatenated update evidence text."""
        if not self.update_evidence:
            return ""
        text = "\n\n---\n\n".join([c.text for c in self.update_evidence])
        return text[:max_chars]
    
    def get_sibling_text(self, max_chars: int = 4000) -> str:
        """Get concatenated sibling evidence text."""
        if not self.sibling_evidence:
            return ""
        text = "\n\n---\n\n".join([c.text for c in self.sibling_evidence])
        return text[:max_chars]


# ============================================================================
# TEXT CHUNKING
# ============================================================================

def semantic_chunk(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """
    Split text into overlapping chunks, trying to break at paragraph boundaries.
    
    Args:
        text: Full text to chunk
        chunk_size: Target size per chunk
        overlap: Overlap between chunks
        
    Returns:
        List of text chunks
    """
    # Split by paragraphs first
    paragraphs = re.split(r'\n\n+', text)
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += "\n\n" + para if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Start new chunk with overlap from previous
            if chunks and overlap > 0:
                prev_text = chunks[-1]
                overlap_text = prev_text[-overlap:] if len(prev_text) > overlap else prev_text
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def clean_text(text: str) -> str:
    """Clean extracted text from PDFs."""
    # Remove watermarks and artifacts
    patterns = [
        r'YUSUF-KEMAL TUNA',
        r'YUSUF KEMAL TUNA',
        r'\d{10,}',  # Long numeric IDs
        r'https?://\S+',  # URLs
        r'©.*?(?=\n|$)',  # Copyright notices
        r'Sayfa \d+',  # Page numbers
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()


# ============================================================================
# SIMPLE RETRIEVER (No ChromaDB - File-based)
# ============================================================================

class SimpleEvidenceRetriever:
    """
    Simple file-based retriever that searches extracted chapter files.
    Uses keyword matching instead of embeddings.
    
    This is a lightweight alternative when ChromaDB is not available.
    """
    
    def __init__(self, base_path: str = "."):
        """
        Initialize the retriever.
        
        Args:
            base_path: Base path where extracted chapter files are located
        """
        self.base_path = base_path
        self.chapter_files = {}
        self.update_files = {}
        self._load_files()
    
    def _load_files(self):
        """Load all text files from base_path and subdirectories."""
        import pathlib
        
        # 1. Recursive search for all .txt files
        base = pathlib.Path(self.base_path)
        all_txts = list(base.rglob("*.txt"))
        
        print(f"📂 Scanning {self.base_path}... Found {len(all_txts)} text files.")
        
        for p in all_txts:
            filename = p.name
            # Use relative path as key for better scoping
            rel_path = str(p) 
            
            # Skip system/log files if any?
            if filename.startswith("."): continue
            
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    content = clean_text(f.read())
                    
                # Classify as Update vs Main
                if "update" in filename.lower():
                    self.update_files[rel_path] = content
                else:
                    self.chapter_files[rel_path] = content
            except Exception as e:
                print(f"⚠️ Could not read {p}: {e}")
        
        print(f"📚 Loaded {len(self.chapter_files)} chapter files, {len(self.update_files)} update files")
    
    def _keyword_search(self, text: str, keywords: list[str], context_chars: int = 1500) -> list[str]:
        """
        Search for keywords in text, merge adjacent windows, and return snippets.
        
        Args:
            text: Text to search
            keywords: List of keywords (0-th index should be the full concept name)
            context_chars: Characters of context around each match
        """
        if not keywords:
            return []
            
        text_lower = normalize_turkish(text)
        windows = [] # List of (start, end, score)
        
        # 1. Collect all match positions
        for i, kw in enumerate(keywords):
            kw_lower = normalize_turkish(kw)
            # Full concept gets highest score
            score = 10 if i == 0 else 1
            
            start_pos = 0
            count = 0
            while count < 10: # Limit matches per keyword to avoid bloat
                pos = text_lower.find(kw_lower, start_pos)
                if pos == -1:
                    break
                
                # Create raw window
                w_start = max(0, pos - context_chars)
                w_end = min(len(text), pos + len(kw) + context_chars)
                windows.append([w_start, w_end, score])
                
                start_pos = pos + 1
                count += 1
        
        if not windows:
            return []
            
        # 2. Merge overlapping windows
        windows.sort(key=lambda x: x[0])
        merged = []
        if windows:
            curr = windows[0]
            for i in range(1, len(windows)):
                nxt = windows[i]
                if nxt[0] <= curr[1] + 100: # Merge if within 100 chars
                    curr[1] = max(curr[1], nxt[1])
                    curr[2] += nxt[2] # Sum scores
                else:
                    merged.append(curr)
                    curr = nxt
            merged.append(curr)
            
        # 3. Refine boundaries to paragraph/sentence
        results = []
        for start, end, score in merged:
            # Expand to boundaries
            while start > 0 and text[start] not in '\n.':
                start -= 1
            while end < len(text) and text[end] not in '\n.':
                end += 1
            
            snippet = text[start:end].strip()
            if snippet:
                results.append((snippet, score))
                
        # 4. Sort by score (descending)
        results.sort(key=lambda x: x[1], reverse=True)
        
        # Return only the snippets
        return [r[0] for r in results[:10]] # Take top 10 best snippets
    
    def get_evidence_for_topic(self, topic: str) -> str:
        """
        Get the full chapter content for a topic.
        
        Args:
            topic: Topic name (e.g., "Nöroloji", "Endokrin")
            
        Returns:
            Full chapter text or empty string
        """
        # Try to find matching chapter file
        # Strict matching preferred: filename must CONTAIN the topic slug
        # Normalize aggressively to match filenames (often ascii)
        topic_slug = normalize_turkish(topic, aggressive=True).replace(' ', '_')
        
        best_match = None
        max_score = 0
        
        for filename, content in self.chapter_files.items():
            filename_lower = filename.lower()
            
            # 1. Exact slug match in filename
            if topic_slug in filename_lower:
                return content
            
            # 2. Part match?
            # Implementation detail: We want strict gating.
            # If we don't find it, we return ""
            pass
            
        return ""
    
    def _is_file_in_scope(self, filename: str, source_material: str, topic: str) -> bool:
        """
        CRITICAL: Check if file belongs to the requested source and topic.
        Does NOT allow fuzzy global matches.
        """
        filename_only = os.path.basename(filename)
        # Normalize filename to match topic slug format (underscores)
        filename_lower = normalize_turkish(filename_only, aggressive=True)
        for char in ",;:.()[]{}!/":
             filename_lower = filename_lower.replace(char, ' ')
        filename_lower = filename_lower.replace(' ', '_').strip('_')
        while '__' in filename_lower: 
            filename_lower = filename_lower.replace('__', '_')

        topic_slug = normalize_turkish(topic, aggressive=True)
        # Remove punctuation for matching
        for char in ",;:.()[]{}!/":
            topic_slug = topic_slug.replace(char, ' ')
        
        topic_slug = topic_slug.replace(' ', '_')
        while '__' in topic_slug:
            topic_slug = topic_slug.replace('__', '_')
        topic_slug = topic_slug.strip('_')
        
        source_slug = normalize_turkish(source_material, aggressive=True).replace(' ', '_') if source_material else ""
        
        # 1. Chunk Special Case (Topic contains filename)
        if "chunk" in topic_slug:
             # If topic is "Chunk: ... -- filename.txt", then topic_slug will contain the filename part
             if filename_lower in topic_slug or topic_slug in filename_lower:
                 pass # Match!
             else:
                 return False
        # 2. Standard Topic Match (Topic is "Diabet")
        elif topic_slug not in filename_lower:
            return False
            
        # 3. Source Match
        # In Turkish, Pathology is Patoloji. The UI might send 'Patoloji' but filename has 'Patoloji'
        if source_slug and source_slug not in filename_lower:
             return False
        
        return True

    def get_evidence_pack(
        self,
        concept: str,
        topic: str,
        sibling_concepts: Optional[list[str]] = None,
        source_material: str = ""
    ) -> EvidencePack:
        """
        Build an evidence pack for a generation request.
        STRICTLY SCOPED to (source_material, topic).
        """
        pack = EvidencePack(scope={"source": source_material, "topic": topic})
        
        # Split concept into keywords
        keywords = [concept] + concept.replace('-', ' ').replace('_', ' ').split()
        keywords = list(set([k for k in keywords if len(k) > 2]))
        
        # 1. Search MAIN chapter files (Scoped)
        scoped_files_found = 0
        
        for filename, content in self.chapter_files.items():
            # STRICT SCOPE CHECK
            if self._is_file_in_scope(filename, source_material, topic):
                scoped_files_found += 1
                # Get specific evidence for concept
                matches = self._keyword_search(content, keywords)
                for i, match in enumerate(matches):
                    pack.main_evidence.append(EvidenceChunk(
                        text=match,
                        source_file=filename,
                        chunk_id=f"{filename}_{i}",
                        metadata={"topic": topic, "concept": concept, "scope": "scoped"}
                    ))
        
        # Fallback: If no keywords found, but we have a scoped file, take its intro/summary
        if not pack.main_evidence and scoped_files_found > 0:
             # Find that file again (inefficient but safe)
             for filename, content in self.chapter_files.items():
                 if self._is_file_in_scope(filename, source_material, topic):
                     # NEW: Try one more keyword search even if _keyword_search initially failed 
                     # (e.g. if the caller forgot to pass correct keywords or we need a wider window)
                     emergency_matches = self._keyword_search(content, keywords, context_chars=1500)
                     if emergency_matches:
                         for i, match in enumerate(emergency_matches[:3]):
                             pack.main_evidence.append(EvidenceChunk(
                                text=match,
                                source_file=filename,
                                chunk_id=f"{filename}_emergency_{i}",
                                metadata={"topic": topic, "warning": "Keyword found in secondary pass."}
                             ))
                     else:
                         # If still nothing, take the first 8000 chars (expanded from 6000)
                         sample_text = content[:8000]
                         pack.main_evidence.append(EvidenceChunk(
                            text=sample_text, 
                            source_file=filename,
                            chunk_id=f"{filename}_intro",
                            metadata={"topic": topic, "fallback": True, "warning": "No direct keyword matches found in scoped file."}
                         ))
                     break
        
        # 2. Search UPDATE files (Scoped)
        for filename, content in self.update_files.items():
            if self._is_file_in_scope(filename, source_material, topic):
                matches = self._keyword_search(content, keywords, context_chars=300)
                for i, match in enumerate(matches):
                    pack.update_evidence.append(EvidenceChunk(
                        text=match,
                        source_file=filename,
                        chunk_id=f"{filename}_{i}",
                        metadata={"type": "update"}
                    ))
        
        # 3. Search SIBLINGS (Scoped)
        if sibling_concepts:
            for sibling in sibling_concepts:
                sibling_keywords = [sibling] + sibling.replace('-', ' ').split()
                for filename, content in self.chapter_files.items():
                     if self._is_file_in_scope(filename, source_material, topic):
                        matches = self._keyword_search(content, sibling_keywords, context_chars=300)
                        for i, match in enumerate(matches[:2]):  # Limit per sibling
                            pack.sibling_evidence.append(EvidenceChunk(
                                text=match,
                                source_file=filename,
                                chunk_id=f"sibling_{sibling}_{i}",
                                metadata={"sibling_concept": sibling}
                            ))
        
        return pack


# ============================================================================
# CHROMADB RETRIEVER (Advanced - Optional)
# ============================================================================

class ChromaDBRetriever:
    """
    Advanced retriever using ChromaDB for semantic search.
    Requires chromadb package.
    """
    
    def __init__(self, persist_directory: str = "./data/vector_index"):
        """
        Initialize ChromaDB retriever.
        
        Args:
            persist_directory: Directory for storing the vector index
        """
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise ImportError("ChromaDB not installed. Run: pip install chromadb")
        
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        # Create or get collections
        self.main_collection = self.client.get_or_create_collection(
            name="main_sources",
            metadata={"description": "Main textbook sources"}
        )
        
        self.update_collection = self.client.get_or_create_collection(
            name="update_sources",
            metadata={"description": "Update/revision sources"}
        )
    
    def index_chapter(self, filepath: str, is_update: bool = False):
        """
        Index a chapter file into the appropriate collection.
        
        Args:
            filepath: Path to the extracted chapter file
            is_update: Whether this is an update file
        """
        filename = os.path.basename(filepath)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = clean_text(f.read())
        
        chunks = semantic_chunk(content)
        collection = self.update_collection if is_update else self.main_collection
        
        ids = [f"{filename}_{i}" for i in range(len(chunks))]
        metadatas = [{"source_file": filename, "chunk_index": i} for i in range(len(chunks))]
        
        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas
        )
        
        print(f"  Indexed {len(chunks)} chunks from {filename}")
    
    def search(self, query: str, n_results: int = 5, collection: str = "main") -> list[EvidenceChunk]:
        """
        Search for relevant evidence.
        
        Args:
            query: Search query
            n_results: Number of results to return
            collection: Which collection to search ("main" or "update")
            
        Returns:
            List of EvidenceChunks
        """
        coll = self.main_collection if collection == "main" else self.update_collection
        
        results = coll.query(
            query_texts=[query],
            n_results=n_results
        )
        
        chunks = []
        if results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i] if results['metadatas'] else {}
                chunks.append(EvidenceChunk(
                    text=doc,
                    source_file=meta.get('source_file', 'unknown'),
                    chunk_id=results['ids'][0][i],
                    metadata=meta
                ))
        
        return chunks
    
    def get_evidence_pack(
        self,
        concept: str,
        topic: str,
        sibling_concepts: Optional[list[str]] = None
    ) -> EvidencePack:
        """Build evidence pack using semantic search."""
        pack = EvidencePack()
        
        # Search main sources
        query = f"{concept} {topic}"
        pack.main_evidence = self.search(query, n_results=8, collection="main")
        
        # Search update sources
        pack.update_evidence = self.search(query, n_results=4, collection="update")
        
        # Search for siblings
        if sibling_concepts:
            for sibling in sibling_concepts:
                sibling_chunks = self.search(sibling, n_results=2, collection="main")
                for chunk in sibling_chunks:
                    chunk.metadata['sibling_concept'] = sibling
                pack.sibling_evidence.extend(sibling_chunks)
        
        return pack


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def get_retriever(use_chromadb: bool = False, base_path: str = ".") -> SimpleEvidenceRetriever | ChromaDBRetriever:
    """
    Get the appropriate retriever based on configuration.
    
    Args:
        use_chromadb: Whether to use ChromaDB (requires package installed)
        base_path: Base path for file-based retriever
        
    Returns:
        Retriever instance
    """
    if use_chromadb:
        try:
            return ChromaDBRetriever()
        except ImportError:
            print("⚠️ ChromaDB not available, falling back to simple retriever")
    
    return SimpleEvidenceRetriever(base_path)


if __name__ == "__main__":
    # Test the simple retriever
    retriever = SimpleEvidenceRetriever(".")
    
    print("\n📌 Testing evidence retrieval for 'Migren'...")
    pack = retriever.get_evidence_pack("Migren", "Nöroloji", ["Cluster Headache", "Tension Headache"])
    
    print(f"\nMain evidence chunks: {len(pack.main_evidence)}")
    if pack.main_evidence:
        print(f"  First chunk: {pack.main_evidence[0].text[:200]}...")
    
    print(f"\nUpdate evidence chunks: {len(pack.update_evidence)}")
    print(f"Sibling evidence chunks: {len(pack.sibling_evidence)}")
