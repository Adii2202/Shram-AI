from flask import Flask, request, jsonify
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance, Filter, FieldCondition, MatchValue
import uuid
import requests
import os
from qdrant_client.http import models as rest


app = Flask(__name__)

QDRANT_HOST = os.getenv("QDRANT_HOST", "http://localhost:6333")
COLLECTION_NAME = "user_memories"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")  # Default Ollama endpoint

qdrant = QdrantClient(url=QDRANT_HOST)

def create_collection():
    try:
        qdrant.delete_collection(collection_name=COLLECTION_NAME)
    except:
        pass

    qdrant.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE)
    )

create_collection()

def embed(text):
    response = requests.post(f"{OLLAMA_URL}/api/embeddings", json={
        "model": "nomic-embed-text",
        "prompt": text
    })
    response.raise_for_status()
    return response.json()["embedding"]

@app.route('/add_memory', methods=['POST'])
def add_memory():
    data = request.json
    user_id = data.get("user_id")
    memory_text = data.get("memory")

    vector = embed(memory_text)
    point = PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={"user_id": user_id, "text": memory_text}
    )
    qdrant.upsert(collection_name=COLLECTION_NAME, points=[point])
    return jsonify({"status": "success", "memory": memory_text})

@app.route('/query_memory', methods=['POST'])
def query_memory():
    data = request.json
    user_id = data.get("user_id")
    query = data.get("query")

    vector = embed(query)
    results = qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=5,
        query_filter=Filter(must=[
            FieldCondition(key="user_id", match=MatchValue(value=user_id))
        ])
    )
    texts = [hit.payload["text"] for hit in results]
    return jsonify({"results": texts})

@app.route('/delete_memory', methods=['POST'])
def delete_memory():
    data = request.json
    user_id = data.get("user_id")
    delete_text = data.get("text")

    if not delete_text:
        return jsonify({"error": "Missing text for deletion"}), 400

    delete_vector = embed(delete_text)
    
    search_result = qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=delete_vector,
        limit=3,
        with_payload=True,
        query_filter=Filter(must=[
            FieldCondition(key="user_id", match=MatchValue(value=user_id))
        ])
    )

    ids_to_delete = [point.id for point in search_result]
    
    if not ids_to_delete:
        return jsonify({"message": "No matching memory found to delete"}), 404

    qdrant.delete(
        collection_name=COLLECTION_NAME,
        points_selector=rest.PointIdsList(points=ids_to_delete)
    )

    return jsonify({"message": "Memory deleted", "deleted_ids": ids_to_delete})

if __name__ == '__main__':
    app.run(debug=True)
