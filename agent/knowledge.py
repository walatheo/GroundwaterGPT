"""
Knowledge Base - ChromaDB Connection for RAG

Connects to the existing ChromaDB with hydrogeology documents.
"""

from pathlib import Path
from typing import List, Optional

import chromadb
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Configuration
BASE_DIR = Path(__file__).parent.parent
CHROMA_DIR = BASE_DIR / "chroma_db"
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


def add_document(content: str, metadata: Optional[dict] = None):
    """
    Add a new document to the knowledge base.

    Args:
        content: Document content
        metadata: Optional metadata dictionary
    """
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
