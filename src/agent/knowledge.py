"""
Knowledge Base - ChromaDB Vector Store for RAG.

This module manages the vector database (ChromaDB) that stores:
1. Hydrogeology PDF documents (chunked and embedded)
2. USGS groundwater monitoring data summaries
3. Research insights learned during agent sessions

Architecture:
    - Uses BAAI/bge-small-en-v1.5 embedding model (384 dimensions)
    - ChromaDB for persistent vector storage
    - LangChain for document processing and retrieval

Key Functions:
    - get_vectorstore(): Get or create the ChromaDB instance
    - search_knowledge(): Semantic search over documents
    - add_document(): Add verified documents to the knowledge base
    - get_knowledge_stats(): Get statistics about stored documents

Example:
    >>> from agent.knowledge import search_knowledge
    >>> results = search_knowledge("Biscayne Aquifer water levels", k=5)
    >>> for doc in results:
    ...     print(doc.page_content[:100])
"""

from pathlib import Path
from typing import List, Optional

import chromadb
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Configuration - Updated paths for new structure
BASE_DIR = Path(__file__).parent.parent.parent  # src/agent -> src -> root
CHROMA_DIR = BASE_DIR / "knowledge_base"
PDF_DIR = BASE_DIR / "resources" / "pdfs"
PDF_FILES = list(PDF_DIR.glob("*.pdf")) if PDF_DIR.exists() else []

# Fallback to old paths if new structure not complete
if not CHROMA_DIR.exists():
    CHROMA_DIR = BASE_DIR / "chroma_db"
if not PDF_FILES:
    PDF_FILES = list(BASE_DIR.glob("*.pdf"))


def get_embeddings():
    """Get the embedding model used for the knowledge base."""
    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en-v1.5",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vectorstore() -> Chroma:
    """
    Get or create the ChromaDB vector store.

    Returns:
        Chroma vector store instance
    """
    embeddings = get_embeddings()

    # Check if ChromaDB exists
    if CHROMA_DIR.exists() and (CHROMA_DIR / "chroma.sqlite3").exists():
        # Load existing database
        vectorstore = Chroma(
            persist_directory=str(CHROMA_DIR),
            embedding_function=embeddings,
            collection_name="hydrogeology_docs",
        )
        return vectorstore
    else:
        # Create new database and load PDFs
        return initialize_knowledge_base()


def initialize_knowledge_base() -> Chroma:
    """
    Initialize the knowledge base with hydrogeology PDFs.

    Returns:
        Chroma vector store with embedded documents
    """
    print("📚 Initializing knowledge base...")

    embeddings = get_embeddings()
    documents = []

    # Load all PDF files
    for pdf_path in PDF_FILES:
        if pdf_path.exists():
            print(f"   Loading: {pdf_path.name}")
            try:
                loader = PyPDFLoader(str(pdf_path))
                docs = loader.load()

                # Add metadata
                for doc in docs:
                    doc.metadata["source_file"] = pdf_path.name
                    doc.metadata["doc_type"] = "hydrogeology_reference"

                documents.extend(docs)
            except Exception as e:
                print(f"   ⚠️ Error loading {pdf_path.name}: {e}")

    if not documents:
        print("   ⚠️ No documents found to load")
        # Create empty vectorstore
        return Chroma(
            persist_directory=str(CHROMA_DIR),
            embedding_function=embeddings,
            collection_name="hydrogeology_docs",
        )

    # Split documents into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=50,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = text_splitter.split_documents(documents)
    print(f"   Split into {len(chunks)} chunks")

    # Create vector store
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
        collection_name="hydrogeology_docs",
    )

    print(f"✅ Knowledge base initialized with {len(chunks)} document chunks")
    return vectorstore


def search_knowledge(query: str, k: int = 5, score_threshold: float = 0.5) -> List[Document]:
    """
    Search the knowledge base for relevant documents.

    Args:
        query: Search query
        k: Number of results to return
        score_threshold: Minimum similarity score (0-1)

    Returns:
        List of relevant documents
    """
    vectorstore = get_vectorstore()

    # Perform similarity search with scores
    results = vectorstore.similarity_search_with_score(query, k=k)

    # Filter by threshold and return documents
    filtered_docs = []
    for doc, score in results:
        # ChromaDB returns distance, lower is better
        # Convert to similarity score (1 - distance for cosine)
        similarity = 1 - score if score <= 1 else 0
        if similarity >= score_threshold:
            doc.metadata["similarity_score"] = similarity
            filtered_docs.append(doc)

    return filtered_docs


def get_retriever(k: int = 5):
    """
    Get a retriever for the knowledge base.

    Args:
        k: Number of documents to retrieve

    Returns:
        LangChain retriever
    """
    vectorstore = get_vectorstore()
    return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": k})


def add_document(
    content: str,
    metadata: Optional[dict] = None,
    source_url: Optional[str] = None,
    require_verification: bool = True,
) -> bool:
    """
    Add a new document to the knowledge base with source verification.

    Args:
        content: Document content
        metadata: Optional metadata dictionary
        source_url: URL of the source for verification
        require_verification: If True, reject unverified sources (default: True)

    Returns:
        True if document was added, False if rejected
    """
    from .source_verification import TrustLevel, verify_source

    # Verify source if URL provided
    if source_url and require_verification:
        verification = verify_source(source_url)
        if not verification.is_approved:
            print(f"⚠️ Rejected unverified source: {source_url}")
            print(f"   Reason: {verification.reason}")
            return False

        # Add verification info to metadata
        if metadata is None:
            metadata = {}
        metadata["source_url"] = source_url
        metadata["trust_level"] = verification.trust_level.value
        metadata["verified"] = True
        metadata["organization"] = verification.organization

    vectorstore = get_vectorstore()

    # Create document
    doc = Document(page_content=content, metadata=metadata or {"source": "user_added"})

    # Split if needed
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=50,
    )
    chunks = text_splitter.split_documents([doc])

    # Add to vectorstore
    vectorstore.add_documents(chunks)

    if source_url:
        print(f"✅ Added verified document from: {source_url}")

    return True


def get_knowledge_stats() -> dict:
    """Get statistics about the knowledge base."""
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection("hydrogeology_docs")
        count = collection.count()

        return {
            "total_chunks": count,
            "pdf_files": len(PDF_FILES),
            "pdf_names": [p.name for p in PDF_FILES],
            "status": "loaded",
        }
    except Exception as e:
        return {
            "total_chunks": 0,
            "pdf_files": len(PDF_FILES),
            "status": f"error: {str(e)}",
        }


def search_usgs_data(
    site_name: str = None,
    site_id: str = None,
    county: str = None,
    aquifer: str = None,
    include_trends: bool = True,
    k: int = 10,
) -> List[Document]:
    """
    Search specifically for USGS groundwater monitoring data.

    This function uses optimized queries for retrieving USGS data,
    including statistics, annual averages, and trend information.
    Uses both semantic search and metadata filtering for better recall.

    Args:
        site_name: Site name (e.g., "Miami-Dade G-3764")
        site_id: USGS site number (e.g., "251241080385301")
        county: County name (e.g., "Miami-Dade")
        aquifer: Aquifer type (e.g., "Biscayne", "Floridan")
        include_trends: Whether to include trend data (default: True)
        k: Number of results per query strategy

    Returns:
        List of relevant USGS documents, deduplicated
    """
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    all_results = []
    seen_content = set()

    # Method 1: Direct metadata filtering (most accurate for specific sites)
    if site_name or site_id:
        try:
            # Get all documents with matching metadata
            all_docs = collection.get(include=["documents", "metadatas"])

            for i, meta in enumerate(all_docs["metadatas"]):
                # Check if this is a USGS document for the requested site
                if meta.get("doc_type") != "usgs_groundwater_data":
                    continue

                match = False
                if site_name and meta.get("site_name") == site_name:
                    match = True
                if site_id and meta.get("site_no") == site_id:
                    match = True

                if match:
                    content = all_docs["documents"][i]
                    content_hash = hash(content[:200])
                    if content_hash not in seen_content:
                        doc = Document(page_content=content, metadata=meta)
                        all_results.append(doc)
                        seen_content.add(content_hash)
        except Exception as e:
            print(f"Metadata search failed: {e}")

    # Method 2: Semantic search queries (for broader matches)
    queries = []

    if site_name:
        queries.append(f"USGS {site_name} groundwater monitoring")
        if include_trends:
            queries.append(f"{site_name} annual trend water level")

    if site_id:
        queries.append(f"USGS site {site_id} groundwater data")
        queries.append(f"site number {site_id}")

    if county:
        queries.append(f"{county} County groundwater monitoring USGS")

    if aquifer:
        queries.append(f"{aquifer} Aquifer water level statistics")

    # Default query if no specific filters
    if not queries and not all_results:
        queries = ["USGS groundwater monitoring Florida aquifer data"]

    # Execute semantic search queries
    for query in queries:
        results = vectorstore.similarity_search_with_score(query, k=k)

        for doc, score in results:
            content_hash = hash(doc.page_content[:200])
            if content_hash not in seen_content:
                if doc.metadata.get("doc_type") == "usgs_groundwater_data":
                    doc.metadata["similarity_score"] = 1 - score if score <= 1 else 0
                    all_results.append(doc)
                    seen_content.add(content_hash)

    # Sort by similarity score (documents from metadata search won't have scores)
    all_results.sort(key=lambda x: x.metadata.get("similarity_score", 0.5), reverse=True)

    return all_results[: k * 2]


def search_with_fallback(
    query: str,
    k: int = 5,
    score_threshold: float = 0.3,
    min_results: int = 3,
) -> List[Document]:
    """
    Search with automatic query expansion for better recall.

    If the initial search returns fewer than min_results, this function
    automatically tries alternative query formulations.

    Args:
        query: Search query
        k: Number of results to return
        score_threshold: Minimum similarity score
        min_results: Minimum acceptable results before trying alternatives

    Returns:
        List of relevant documents
    """
    # Try primary search
    results = search_knowledge(query, k=k, score_threshold=score_threshold)

    if len(results) >= min_results:
        return results

    # Try lowering threshold
    if len(results) < min_results:
        results = search_knowledge(query, k=k, score_threshold=0.2)

    if len(results) >= min_results:
        return results

    # Try query expansion - extract key terms
    import re

    # Extract site identifiers
    site_match = re.search(r"G-\d+|[0-9]{15}", query)
    aquifer_match = re.search(r"(biscayne|floridan|surficial)", query.lower())
    county_match = re.search(r"(miami-dade|lee|broward|palm beach)", query.lower())

    expanded_queries = []

    if site_match:
        expanded_queries.append(f"USGS {site_match.group()} groundwater")
    if aquifer_match:
        expanded_queries.append(f"{aquifer_match.group()} aquifer water level Florida")
    if county_match:
        expanded_queries.append(f"{county_match.group()} county groundwater monitoring")

    # Try expanded queries
    seen = set(doc.page_content[:100] for doc in results)

    for eq in expanded_queries:
        new_results = search_knowledge(eq, k=k, score_threshold=0.2)
        for doc in new_results:
            if doc.page_content[:100] not in seen:
                results.append(doc)
                seen.add(doc.page_content[:100])

    return results[: k * 2]
