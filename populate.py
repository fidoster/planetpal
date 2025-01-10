import os
import openai
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from pdfminer.high_level import extract_text
import numpy as np
import hashlib
import time

# Load environment variables from .env
load_dotenv()

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


# Helper: Extract text from PDF
def extract_text_from_pdf(pdf_path):
    """Extracts text from a PDF file."""
    try:
        text = extract_text(pdf_path)
        return text
    except Exception as e:
        print(f"Error extracting text: {e}")
        return None

# Helper: Generate Embeddings with OpenAI
def embed_text(text):
    """Embed a text using the OpenAI embedding API."""
    try:
        for attempt in range(5):  # Retry up to 5 times
             try:
                response = openai.Embedding.create(
                    input=text,
                     engine=os.getenv("AZURE_EMBEDDING_ENGINE")
                )
                return response['data'][0]['embedding']
             except openai.error.RateLimitError as e:
                print(f"Rate limit exceeded. Retrying in {2**attempt} seconds...")
                time.sleep(2**attempt)
                if attempt == 4:
                  print("Max retries reached, giving up...")
                  raise e
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None


def index_embeddings(embeddings, id_list, index_name, namespace):
    """Indexes a list of embeddings into a Pinecone index."""
    index = pc.Index(index_name)
    # Upsert the embeddings into the Pinecone Index
    vectors = list(zip(id_list, embeddings, [{"text": text} for text in id_list]))
    index.upsert(vectors=vectors, namespace=namespace)

def generate_id(text):
     """Generates an id from the input text using a hash method"""
     return hashlib.sha256(text.encode()).hexdigest()

def populate_pinecone_from_pdf(pdf_path, index_name, namespace):
    """Processes a PDF and uploads embeddings to Pinecone."""
    print(f"Processing PDF: {pdf_path}")
    pdf_text = extract_text_from_pdf(pdf_path)
    if not pdf_text:
        print(f"Could not extract text from: {pdf_path}")
        return

      # Split the text into paragraphs or sections
    split_texts = pdf_text.split("\n\n")
      # generate ids using a hash for each of them
    split_ids = [generate_id(text) for text in split_texts]
    # Embed the split sections
    embeddings = [embed_text(text) for text in split_texts]
    # Index embeddings in Pinecone
    index_embeddings(embeddings, id_list=split_ids, index_name=index_name, namespace=namespace)

    print(f"PDF {pdf_path} processed and indexed successfully in index {index_name} and namespace {namespace} .")

if __name__ == '__main__':
    pdf_file_paths = {
        "green_loan_guide":"static/assets/personas/PrincipleOP.pdf",
        "eif_guarantee_guide":"static/assets/personas/GreenbondOP.pdf"
    }

    for namespace, pdf_path in pdf_file_paths.items():
         print(f"Now processing the PDF: {pdf_path} in the name space {namespace}")
         populate_pinecone_from_pdf(pdf_path,index_name, namespace=namespace)