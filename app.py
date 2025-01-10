from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import os
import openai
import redis
from pinecone import Pinecone, ServerlessSpec
from werkzeug.utils import secure_filename
from pdfminer.high_level import extract_text
import numpy as np
import time
from personas import get_persona_prompt  # Importing from personas.py


# Load environment variables from .env
load_dotenv()

# Flask App Configuration
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Redis Configuration
try:
    redis_client = redis.StrictRedis(
        host=os.getenv("REDIS_HOST"),      # Redis Cloud host
        port=int(os.getenv("REDIS_PORT")), # Redis Cloud port
        password=os.getenv("REDIS_PASSWORD"), # Redis Cloud password
        decode_responses=True             # Decode responses to UTF-8
    )
    redis_client.ping()
    print("Connected to Redis Cloud.")
except Exception as e:
    print(f"Failed to connect to Redis Cloud: {e}")
    redis_client = None

# OpenAI Configuration (Azure)
openai.api_type = "azure"
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = "https://myai-chatbot.openai.azure.com/"
openai.api_version = "2023-05-15"

# Pinecone Configuration
api_key = os.getenv("PINECONE_API_KEY")  # API Key from .env
index_name = "planetpal"  # Index Name
dimension = 1536  # Embedding dimension for text-embedding-ada-002

try:
    # Initialize Pinecone client
    pc = Pinecone(api_key=api_key)
    print("Pinecone client initialized successfully.")

    # Check if index exists, create if not
    existing_indexes = pc.list_indexes().names()
    if index_name not in existing_indexes:
        print(f"Index '{index_name}' does not exist. Creating it now...")
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",  # Ensure this matches your embedding model
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        print(f"Index '{index_name}' created successfully.")
    else:
        print(f"Index '{index_name}' already exists.")

    # Connect to the Pinecone index
    pinecone_index = pc.Index(index_name)
    print(f"Connected to index '{index_name}'.")
except Exception as e:
    print(f"Error initializing or connecting to Pinecone: {e}")
    pinecone_index = None

# Helper: Count tokens in messages
def count_tokens(messages):
    """Estimate the token count of messages."""
    return sum(len(msg['content'].split()) for msg in messages)

# Helper: Generate Embeddings with OpenAI
def embed_text(text):
    """Embed a text using the OpenAI embedding API."""
    try:
        response = openai.Embedding.create(
            input=text,
             engine=os.getenv("AZURE_EMBEDDING_ENGINE")
        )
        return response['data'][0]['embedding']
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None


def search_index(index_name,query_embedding, namespace, top_k=3):
     """Searches a Pinecone index for similar embeddings."""
     index = pc.Index(index_name)
     query_embedding_list = query_embedding.tolist()
     results = index.query(vector=query_embedding_list,top_k=top_k,namespace=namespace,include_metadata = True)
     return [match.metadata['text'] for match in results.matches]




# Route: Home Page
@app.route('/')
def home():
    return render_template('index.html')

# Route to handle favicon requests
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')

# Custom error handler for 404 errors
@app.errorhandler(404)
def not_found_error(e):
    return jsonify({"error": "The requested URL was not found on the server."}), 404



# Route: Fetch List of Uploaded PDFs
@app.route('/fetch-pdfs', methods=['GET'])
def fetch_pdfs():
    try:
        print("Fetching PDF names from Pinecone...")
         #Fetch index and list of namespaces from the index.
        index = pc.Index(index_name)
        pdf_list = index.describe_index_stats().namespaces
        if pdf_list:
            pdfs = [namespace for namespace in pdf_list.keys()]
        else:
            pdfs = []

        print(f"Retrieved PDF names: {pdfs}")
        return jsonify({"pdfs": pdfs})
    except Exception as e:
        print(f"Error in /fetch-pdfs: {e}")
        return jsonify({"error": "Failed to fetch PDFs."}), 500

# Route: Ask Question with Persona
@app.route('/ask', methods=['POST'])
def ask_question():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON payload provided."}), 400

        question = data.get("question")
        persona = data.get("persona", "Advisor")
        level = data.get("level", 1)
        selected_pdf = data.get("selected_pdf", None)  # Optional selected PDF for context
        session_id = data.get("session_id", "default")

        if not question:
            return jsonify({"error": "Question is missing."}), 400

         # Retrieve persona prompt
        system_prompt = get_persona_prompt(persona, level)


        # Retrieve session context from Redis (limit to last 3 messages)
        session_key = f"chat:{session_id}"
        previous_messages = redis_client.lrange(session_key, -3, -1) if redis_client else []
        messages = [{"role": "system", "content": system_prompt}] + [
            {"role": "assistant" if i % 2 else "user", "content": msg}
            for i, msg in enumerate(previous_messages)
        ]
        messages.append({"role": "user", "content": question})

          # If a PDF is selected, query the PDF content from Pinecone
        if selected_pdf and pinecone_index:
             query_embedding = embed_text(question)
             if query_embedding is not None:
                relevant_text = search_index(index_name,query_embedding,namespace = selected_pdf)

                if relevant_text:
                     context = " ".join(relevant_text)
                     messages.append({"role": "user", "content": f"Context: {context[:1500]}\nQuestion: {question}"})


        # Log the total tokens before making the API call
        total_tokens = count_tokens(messages)
        print(f"Total tokens sent: {total_tokens}")

        # Generate response using OpenAI
        response = openai.ChatCompletion.create(
            engine="gpt-4",  # Replace with your Azure OpenAI deployment name
            messages=messages,
            temperature=0.55,
            max_tokens=100
        )
        answer = response['choices'][0]['message']['content']

        # Save context in Redis
        if redis_client:
            redis_client.rpush(session_key, question, answer)

        return jsonify({"answer": answer})
    except Exception as e:
        print(f"Error in /ask: {e}")
        return jsonify({"error": f"Failed to fetch answer: {str(e)}"}), 500

# Global error handler
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled exception: {e}")
    return jsonify({"error": "An internal server error occurred.", "details": str(e)}), 500

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)