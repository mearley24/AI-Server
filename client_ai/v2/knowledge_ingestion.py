#!/usr/bin/env python3
"""
knowledge_ingestion.py
Symphony Smart Homes — Concierge AI Knowledge Ingestion Pipeline

Converts Symphony project data (D-Tools exports, equipment lists, user manuals,
network topology) into a persistent ChromaDB vector store that powers the RAG
pipeline in concierge_server.py.

Usage:
    python knowledge_ingestion.py --project project.json
    python knowledge_ingestion.py --pdf "Sony VPL-XW5000 Manual.pdf"
    python knowledge_ingestion.py --project project.json --rebuild
    python knowledge_ingestion.py --status

Dependencies:
    pip install chromadb sentence-transformers pypdf2 pdfplumber lxml
"""

import argparse
import json
import logging
import os
import re
import sys
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/opt/symphony/concierge/logs/ingestion.log", mode="a"),
    ] if Path("/opt/symphony/concierge/logs").exists() else [logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("symphony.ingestion")

INGESTION_VERSION = "2.0.0"
DEFAULT_CHROMA_PATH = os.environ.get("CHROMA_PATH", "/opt/symphony/concierge/vectorstore")
DEFAULT_COLLECTION = "symphony_home_knowledge"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
EMBED_MODEL = "all-MiniLM-L6-v2"
MAX_PDF_PAGES = 200


def _import_chromadb():
    try:
        import chromadb
        from chromadb.config import Settings
        return chromadb, Settings
    except ImportError:
        logger.error("chromadb not installed. Run: pip install chromadb")
        sys.exit(1)


def _import_sentence_transformers():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer
    except ImportError:
        logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)


def _import_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except ImportError:
        try:
            import PyPDF2
            return None
        except ImportError:
            logger.warning("No PDF library found. Run: pip install pdfplumber")
            return False


def get_chroma_client(path: str):
    """Create or connect to the local ChromaDB vector store."""
    chromadb, Settings = _import_chromadb()
    client = chromadb.PersistentClient(
        path=path,
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )
    logger.info(f"ChromaDB connected at: {path}")
    return client


def get_or_create_collection(client, collection_name: str, embedding_fn=None):
    """Get or create a named ChromaDB collection."""
    chromadb, _ = _import_chromadb()
    try:
        collection = client.get_collection(
            name=collection_name,
            embedding_function=embedding_fn,
        )
        logger.info(f"Loaded existing collection '{collection_name}' ({collection.count()} docs)")
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Created new collection '{collection_name}'")
    return collection


class LocalEmbeddingFunction:
    """
    Wraps sentence-transformers for use as a ChromaDB embedding function.
    All embedding is done locally — no API calls, no data leaves the appliance.
    """

    def __init__(self, model_name: str = EMBED_MODEL):
        SentenceTransformer = _import_sentence_transformers()
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        logger.info("Embedding model loaded")

    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(input, show_progress_bar=False)
        return embeddings.tolist()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP, source: str = "") -> list[dict]:
    """Split text into overlapping chunks for ingestion."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:]
        else:
            search_end = min(end + 100, len(text))
            boundary = max(
                text.rfind(". ", start, search_end),
                text.rfind("\n", start, search_end),
            )
            if boundary > start + overlap:
                end = boundary + 1
            chunk = text[start:end]

        chunk = chunk.strip()
        if chunk and len(chunk) > 30:
            chunks.append({"text": chunk, "source": source, "chunk_index": chunk_index})
            chunk_index += 1

        start = max(start + chunk_size - overlap, start + 1)
        if start >= len(text):
            break

    return chunks


def parse_dtools_json(path: str) -> dict:
    """Parse a D-Tools project exported as JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info(f"Loaded D-Tools JSON: {path} ({len(str(data))} bytes)")
    return data


def parse_dtools_xml(path: str) -> dict:
    """Parse a D-Tools project exported as XML."""
    logger.info(f"Parsing D-Tools XML: {path}")
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"XML parse error: {e}")
        raise

    def _xml_to_dict(element) -> Any:
        result = {}
        if element.text and element.text.strip():
            result["_text"] = element.text.strip()
        result.update(element.attrib)
        children: dict[str, Any] = {}
        for child in element:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            child_data = _xml_to_dict(child)
            if tag in children:
                if not isinstance(children[tag], list):
                    children[tag] = [children[tag]]
                children[tag].append(child_data)
            else:
                children[tag] = child_data
        result.update(children)
        return result

    return _xml_to_dict(root)


def load_project_file(path: str) -> dict:
    """Load a D-Tools project file (auto-detects JSON or XML)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Project file not found: {path}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        return parse_dtools_json(path)
    elif suffix in (".xml", ".dtxml"):
        return parse_dtools_xml(path)
    else:
        try:
            return parse_dtools_json(path)
        except json.JSONDecodeError:
            return parse_dtools_xml(path)


def generate_room_documents(project: dict) -> list[dict]:
    """Generate one document per room describing all devices in that room."""
    rooms = project.get("rooms", [])
    systems = project.get("systems", {})
    client_name = project.get("client_name", "your home")
    documents = []
    room_device_map: dict[str, list[str]] = {r["name"]: [] for r in rooms}

    c4 = systems.get("control4", {})
    for tp in c4.get("touch_panels", []):
        loc = tp.get("location", "")
        if loc in room_device_map:
            room_device_map[loc].append(f"Control4 {tp.get('model', '')} touch panel")

    lutron = systems.get("lutron", {})
    for kp in lutron.get("keypads", []):
        loc = kp.get("location", "")
        for room_name in room_device_map:
            if room_name.lower() in loc.lower() or loc.lower() in room_name.lower():
                room_device_map[room_name].append(f"Lutron {kp.get('model', '')} keypad")
                break

    for shade in lutron.get("shades", []):
        loc = shade.get("location", "")
        if loc in room_device_map:
            room_device_map[loc].append(f"{shade.get('count', '')}x {shade.get('type', '')} motorized shades")

    audio = systems.get("audio", {})
    for s in audio.get("sonos", []):
        loc = s.get("location", "")
        if loc in room_device_map:
            room_device_map[loc].append(f"{s.get('model', '')} Sonos speaker ({s.get('name', '')})")

    video = systems.get("video", {})
    for d in video.get("displays", []):
        loc = d.get("location", "")
        if loc in room_device_map:
            room_device_map[loc].append(f"{d.get('brand', '')} {d.get('model', '')} {d.get('size', '')} display")

    for room in rooms:
        room_name = room["name"]
        devices = room_device_map.get(room_name, [])
        floor = room.get("floor", "?")
        device_text = "\n".join(f"  - {d}" for d in devices) if devices else "  (No specific devices mapped)"
        text = f"Room: {room_name}\nHome: {client_name}\nFloor: {floor}\n\nDevices:\n{device_text}\n"
        documents.extend(chunk_text(text, source=f"room:{room_name}"))

    logger.info(f"Generated {len(documents)} room documents for {len(rooms)} rooms")
    return documents


def generate_scene_documents(project: dict) -> list[dict]:
    """Generate documents for each programmed scene/automation."""
    c4 = project.get("systems", {}).get("control4", {})
    scenes = c4.get("scenes", [])
    client_name = project.get("client_name", "your home")
    documents = []

    for scene in scenes:
        name = scene.get("name", "")
        description = scene.get("description", "")
        text = f"""Scene: {name}\nHome: {client_name}\nWhat the '{name}' scene does: {description}\n
How to activate '{name}':\n1. Use the Control4 touchscreen\n2. Use the Control4 app\n3. Press the corresponding button on your remote\n
The '{name}' scene is useful when you want to {description.lower()}.
"""
        documents.extend(chunk_text(text, source=f"scene:{name}"))

    logger.info(f"Generated scene documents for {len(scenes)} scenes")
    return documents


def generate_network_documents(project: dict) -> list[dict]:
    """Generate network topology documents."""
    net = project.get("systems", {}).get("networking", {})
    if not net:
        return []

    client_name = project.get("client_name", "your home")
    documents = []
    gateway = net.get("gateway", {})
    vlans = net.get("vlans", [])
    aps = net.get("access_points", [])
    switches = net.get("switches", [])

    text = f"Network Infrastructure: {client_name}\n"
    text += f"Router/Gateway: {gateway.get('model', 'N/A')} at {gateway.get('ip', 'N/A')}\n"
    text += f"Internet Provider: {net.get('internet_provider', 'N/A')}\n"
    text += f"Internet Speed: {net.get('internet_speed', 'N/A')}\n\nWiFi Networks:\n"

    ssids_seen = set()
    for ap in aps:
        ssid = ap.get("ssid", "")
        if ssid and ssid not in ssids_seen:
            text += f"  - {ssid}: covering {ap.get('location', 'N/A')}\n"
            ssids_seen.add(ssid)

    text += "\nNetwork Segments (VLANs):\n"
    for vlan in vlans:
        text += f"  - VLAN {vlan.get('id', '?')} - {vlan.get('name', '?')} ({vlan.get('subnet', '?')}): {vlan.get('purpose', '')}\n"

    documents.extend(chunk_text(text, source="network:topology"))

    faq_text = f"Network Troubleshooting - {client_name}\n"
    faq_text += "Q: My phone can't connect to the smart home app\n"
    faq_text += f"A: Make sure you're on the main WiFi network. Control4 requires local network.\n\n"
    faq_text += "Q: Internet is down but does my smart home still work?\n"
    faq_text += "A: Yes! All local control functions work without internet.\n"
    documents.extend(chunk_text(faq_text, source="network:troubleshooting"))

    logger.info(f"Generated {len(documents)} network documents")
    return documents


def generate_troubleshooting_documents(project: dict) -> list[dict]:
    """Generate per-device troubleshooting documents from project data."""
    systems = project.get("systems", {})
    client_name = project.get("client_name", "your home")
    tech = project.get("tech_contact", {})
    tech_phone = tech.get("phone", "(480) 555-0100")
    documents = []

    c4 = systems.get("control4", {})
    if c4:
        text = f"Control4 Troubleshooting - {client_name}\n"
        text += f"Controller: {c4.get('controller', 'EA-5')} at {c4.get('ip', '192.168.10.100')}\n\n"
        text += "Touch panel black/unresponsive: Hold power button 5 seconds.\n"
        text += "Screen shows 'Connecting...': Wait 2-3 minutes for system startup.\n"
        text += f"When to call Symphony ({tech_phone}): System won't restart after troubleshooting.\n"
        documents.extend(chunk_text(text, source="troubleshoot:control4"))

    lutron = systems.get("lutron", {})
    if lutron:
        text = f"Lutron Lighting & Shades Troubleshooting - {client_name}\n"
        text += "Light doesn't respond to keypad: Press and hold the button for 2 seconds.\n"
        text += "Shade won't move: Check that the shade motor has power (small LED near motor).\n"
        text += f"When to call Symphony ({tech_phone}): Individual dimmers stop working.\n"
        documents.extend(chunk_text(text, source="troubleshoot:lutron"))

    audio = systems.get("audio", {})
    if audio:
        text = f"Audio System Troubleshooting - {client_name}\n"
        text += "No audio from Sonos: Open Sonos app, reconnect if offline. Unplug/replug if needed.\n"
        text += "In-ceiling speakers silent: Check Triad amplifier is powered on (green LED).\n"
        text += f"When to call Symphony ({tech_phone}): No audio after all troubleshooting steps.\n"
        documents.extend(chunk_text(text, source="troubleshoot:audio"))

    logger.info(f"Generated {len(documents)} troubleshooting documents")
    return documents


def generate_faq_documents(project: dict) -> list[dict]:
    """Generate common FAQ documents personalized to the client's system."""
    client_name = project.get("client_name", "your home")
    ai_name = project.get("ai_name", "Aria")
    tech = project.get("tech_contact", {})
    tech_phone = tech.get("phone", "(480) 555-0100")
    tech_email = tech.get("email", "support@symphonysmarthomes.com")

    text = f"""Frequently Asked Questions - {client_name}

Q: What can {ai_name} help me with?
A: I can help with anything related to your home's smart systems:
   - Operating Control4, Lutron, Sonos, cameras, and all other systems
   - Explaining what scenes and automations do
   - Step-by-step troubleshooting for devices that aren't working
   - Telling you what equipment is installed and where

Q: Can {ai_name} actually control my home?
A: No - I'm a knowledge assistant, not a controller. I can tell you how to
   control anything, but I don't have a live connection to your systems.

Q: Is my conversation private?
A: Yes, completely. {ai_name} runs entirely on a small computer in your home.
   Your conversations never leave the house.

Q: How do I contact Symphony Smart Homes?
A: Phone: {tech_phone}\n   Email: {tech_email}
   Hours: Monday-Friday, 8 AM-6 PM MST
   Emergency (system down): Available 24/7 via phone
"""
    documents = chunk_text(text, source="faq:general")
    logger.info(f"Generated {len(documents)} FAQ documents")
    return documents


def ingest_pdf(path: str, device_name: str = "") -> list[dict]:
    """Extract text from a PDF user manual and chunk it for ingestion."""
    pdfplumber = _import_pdfplumber()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    source_label = f"manual:{device_name or p.stem}"
    all_text = []

    if pdfplumber is not None and pdfplumber is not False:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages[:MAX_PDF_PAGES]
            for i, page in enumerate(pages):
                text = page.extract_text()
                if text and len(text.strip()) > 50:
                    all_text.append(f"[Page {i + 1}]\n{text.strip()}")
    else:
        try:
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
                    text = page.extract_text()
                    if text and len(text.strip()) > 50:
                        all_text.append(f"[Page {i + 1}]\n{text.strip()}")
        except ImportError:
            logger.warning(f"Cannot read PDF - no PDF library available: {path}")
            return []

    if not all_text:
        logger.warning(f"No text extracted from PDF: {path}")
        return []

    full_text = f"User Manual: {device_name or p.stem}\n\n" + "\n\n".join(all_text)
    chunks = chunk_text(full_text, source=source_label)
    logger.info(f"PDF '{p.name}': {len(all_text)} pages -> {len(chunks)} chunks")
    return chunks


def ingest_project(project: dict, collection, rebuild: bool = False) -> int:
    """Ingest all project documents into ChromaDB."""
    if rebuild:
        logger.info("Rebuild mode: clearing existing project documents")
        try:
            existing = collection.get(where={"type": "project"})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                logger.info(f"Deleted {len(existing['ids'])} existing project documents")
        except Exception as e:
            logger.warning(f"Could not delete existing docs: {e}")

    all_chunks: list[dict] = []
    all_chunks.extend(generate_room_documents(project))
    all_chunks.extend(generate_scene_documents(project))
    all_chunks.extend(generate_network_documents(project))
    all_chunks.extend(generate_troubleshooting_documents(project))
    all_chunks.extend(generate_faq_documents(project))

    try:
        from client_knowledge_builder import generate_equipment_kb  # type: ignore
        kb_text = generate_equipment_kb(project)
        all_chunks.extend(chunk_text(kb_text, source="knowledge_base:full"))
    except ImportError:
        summary = _generate_equipment_summary(project)
        all_chunks.extend(chunk_text(summary, source="knowledge_base:summary"))

    if not all_chunks:
        logger.warning("No documents generated from project data")
        return 0

    return _upsert_chunks(collection, all_chunks, metadata_type="project")


def _generate_equipment_summary(project: dict) -> str:
    """Minimal fallback if client_knowledge_builder isn't importable."""
    systems = project.get("systems", {})
    lines = [f"# {project.get('client_name', 'Home')} Equipment Summary\n"]
    for system_name, system_data in systems.items():
        lines.append(f"\n## {system_name.title()}")
        lines.append(json.dumps(system_data, indent=2))
    return "\n".join(lines)


def ingest_pdf_manual(pdf_path: str, device_name: str, collection) -> int:
    """Add a PDF user manual to the knowledge base."""
    chunks = ingest_pdf(pdf_path, device_name)
    if not chunks:
        return 0
    return _upsert_chunks(collection, chunks, metadata_type="manual")


def _upsert_chunks(collection, chunks: list[dict], metadata_type: str) -> int:
    """Batch-upsert text chunks into ChromaDB with deduplication."""
    if not chunks:
        return 0

    BATCH_SIZE = 50
    total_inserted = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[batch_start: batch_start + BATCH_SIZE]
        ids = []
        texts = []
        metas = []

        for chunk in batch:
            import hashlib
            chunk_id = hashlib.sha256(
                f"{chunk['source']}:{chunk['chunk_index']}:{chunk['text'][:64]}".encode()
            ).hexdigest()[:16]
            ids.append(chunk_id)
            texts.append(chunk["text"])
            metas.append({
                "source": chunk["source"],
                "chunk_index": chunk["chunk_index"],
                "type": metadata_type,
                "ingested_at": now_iso,
                "length": len(chunk["text"]),
            })

        try:
            collection.upsert(ids=ids, documents=texts, metadatas=metas)
            total_inserted += len(batch)
        except Exception as e:
            logger.error(f"ChromaDB upsert error (batch {batch_start}): {e}")

    logger.info(f"Upserted {total_inserted} chunks (type={metadata_type})")
    return total_inserted


def query_knowledge_base(query: str, collection, n_results: int = 5, filter_type: Optional[str] = None) -> list[dict]:
    """Query the knowledge base for relevant context."""
    where = {"type": filter_type} if filter_type else None
    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.error(f"ChromaDB query error: {e}")
        return []

    formatted = []
    if results and results.get("documents"):
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]
        for doc, meta, dist in zip(docs, metas, distances):
            formatted.append({
                "text": doc,
                "source": meta.get("source", "unknown"),
                "distance": round(float(dist), 4),
                "metadata": meta,
            })
    return formatted


def build_rag_context(query: str, collection, n_results: int = 5, max_context_chars: int = 3000) -> str:
    """Build the RAG context string to inject into the LLM prompt."""
    results = query_knowledge_base(query, collection, n_results=n_results)
    if not results:
        return ""

    relevant = [r for r in results if r["distance"] < 0.5]
    if not relevant:
        relevant = results[:2]

    context_parts = []
    total_chars = 0
    for result in relevant:
        if total_chars + len(result["text"]) > max_context_chars:
            break
        source_label = result["source"].replace(":", " - ").replace("_", " ").title()
        context_parts.append(f"[{source_label}]\n{result['text']}")
        total_chars += len(result["text"])

    if not context_parts:
        return ""

    return "RELEVANT KNOWLEDGE BASE CONTEXT:\n\n" + "\n\n---\n\n".join(context_parts)


def get_ingestion_status(collection) -> dict:
    """Return a status summary of the current knowledge base."""
    try:
        count = collection.count()
        sample = collection.get(limit=1000, include=["metadatas"])
        source_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for meta in sample.get("metadatas", []):
            source_prefix = meta.get("source", "unknown").split(":")[0]
            source_counts[source_prefix] = source_counts.get(source_prefix, 0) + 1
            t = meta.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total_chunks": count,
            "source_breakdown": source_counts,
            "type_breakdown": type_counts,
            "status": "ready" if count > 0 else "empty",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(
        description="Symphony Concierge - Knowledge Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", "-p", help="Path to D-Tools project file (JSON or XML)")
    parser.add_argument("--pdf", help="Path to a PDF user manual to ingest")
    parser.add_argument("--device", help="Device name label for the PDF manual")
    parser.add_argument("--rebuild", action="store_true", help="Clear and rebuild the vector store")
    parser.add_argument("--status", action="store_true", help="Show knowledge base status and exit")
    parser.add_argument("--chroma-path", default=DEFAULT_CHROMA_PATH)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--n-results", type=int, default=5)
    parser.add_argument("--test-query", help="Run a test query against the knowledge base")
    args = parser.parse_args()

    print(f"\nSymphony Concierge - Knowledge Ingestion v{INGESTION_VERSION}")
    print(f"ChromaDB path: {args.chroma_path}")
    print(f"Collection:    {args.collection}")
    print()

    embed_fn = LocalEmbeddingFunction()
    client = get_chroma_client(args.chroma_path)
    collection = get_or_create_collection(client, args.collection, embed_fn)

    if args.status:
        status = get_ingestion_status(collection)
        print("Knowledge Base Status:")
        print(json.dumps(status, indent=2))
        return

    if args.project:
        logger.info(f"Ingesting project file: {args.project}")
        project = load_project_file(args.project)
        count = ingest_project(project, collection, rebuild=args.rebuild)
        logger.info(f"Project ingestion complete: {count} chunks added")

    if args.pdf:
        device_name = args.device or Path(args.pdf).stem
        logger.info(f"Ingesting PDF manual: {args.pdf} (device: {device_name})")
        count = ingest_pdf_manual(args.pdf, device_name, collection)
        logger.info(f"PDF ingestion complete: {count} chunks added")

    if args.test_query:
        print(f"\nTest query: '{args.test_query}'")
        context = build_rag_context(args.test_query, collection, n_results=args.n_results)
        print(context or "(No relevant results found)")

    status = get_ingestion_status(collection)
    print(f"\nKnowledge Base: {status['total_chunks']} chunks total")
    print(f"Sources: {status.get('source_breakdown', {})}")
    print("\nKnowledge base ready for concierge_server.py")


if __name__ == "__main__":
    main()
