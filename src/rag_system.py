# src/rag_system.py
import pandas as pd
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = 'paraphrase-multilingual-MiniLM-L12-v2'

class RAGSystem:
    def __init__(self, catalog_path="data/catalog.csv", sales_book_path="data/sales_book.txt"):
        self.model = SentenceTransformer(MODEL_NAME)
        self.catalog_data = []
        self.sales_book_chunks = []
        self.all_chunks_text = []
        self.index = None
        self.chunk_sources = []

        self._load_and_chunk_data(catalog_path, sales_book_path)
        self._build_index()

    def _load_and_chunk_data(self, catalog_path, sales_book_path):
        df_catalog = pd.read_csv(catalog_path)
        for _, row in df_catalog.iterrows():
            text_chunk = f"ID: {row['ID']}. Название: {row['Название детали']}. " \
                         f"Совместимость: {row['Совместимость моделей']}. " \
                         f"Тип: {'Оригинал' if row['Оригинал'] == 'Да' else 'Аналог'}. " \
                         f"Цена: {row['Цена (₽)']} руб. Артикул: {row['Артикул']}."
            self.catalog_data.append(dict(row))
            self.all_chunks_text.append(text_chunk)
            self.chunk_sources.append({'type': 'catalog_item', 'data': dict(row)})


        with open(sales_book_path, 'r', encoding='utf-8') as f:
            current_category = ""
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.endswith(':'):
                    current_category = line[:-1]
                else:
                    chunk_text = f"Совет по продажам ({current_category}): {line}"
                    self.sales_book_chunks.append(line)
                    self.all_chunks_text.append(chunk_text)
                    self.chunk_sources.append({'type': 'sales_tip', 'data': line, 'category': current_category})
        
        print(f"Total chunks created: {len(self.all_chunks_text)}")
        if not self.all_chunks_text:
            raise ValueError("No chunks were created. Check data paths and content.")


    def _build_index(self):
        if not self.all_chunks_text:
            print("No text chunks to build index from. Skipping FAISS index creation.")
            return

        print("Encoding chunks...")
        embeddings = self.model.encode(self.all_chunks_text, convert_to_tensor=False, show_progress_bar=True)
        
        if embeddings.ndim == 1:
             embeddings = embeddings.reshape(1, -1)

        embeddings = np.array(embeddings).astype('float32')
        
        if embeddings.shape[0] == 0:
            print("Embeddings array is empty. Cannot build FAISS index.")
            return

        self.index = faiss.IndexFlatL2(embeddings.shape[1])
        self.index.add(embeddings)
        print(f"FAISS index built with {self.index.ntotal} vectors.")

    def search(self, query_text, k=5):
        if self.index is None or self.index.ntotal == 0:
            print("FAISS index is not available or empty.")
            return []
        
        query_embedding = self.model.encode([query_text], convert_to_tensor=False)
        query_embedding = np.array(query_embedding).astype('float32')
        
        distances, indices = self.index.search(query_embedding, k=min(k, self.index.ntotal))
        
        results = []
        for i in range(len(indices[0])):
            idx = indices[0][i]
            if 0 <= idx < len(self.all_chunks_text):
                results.append({
                    'text': self.all_chunks_text[idx],
                    'source_info': self.chunk_sources[idx],
                    'distance': distances[0][i]
                })
            else:
                print(f"Warning: Index {idx} out of bounds for all_chunks_text (len={len(self.all_chunks_text)})")
        return results

if __name__ == '__main__':
    rag = RAGSystem()
    
    print("\n--- Test Search ---")
    test_query = "моторчик омывателя Golf 6"
    search_results = rag.search(test_query, k=3)
    print(f"Search results for: '{test_query}'")
    for res in search_results:
        print(f"  Distance: {res['distance']:.4f} - Source Type: {res['source_info']['type']}")
        print(f"  Text: {res['text']}\n")

    test_query_2 = "как закрыть сделку"
    search_results_2 = rag.search(test_query_2, k=2)
    print(f"Search results for: '{test_query_2}'")
    for res in search_results_2:
        print(f"  Distance: {res['distance']:.4f} - Source Type: {res['source_info']['type']}")
        print(f"  Text: {res['text']}\n")

    test_query_3 = "сколько стоит задний фонарь на пассат б7"
    search_results_3 = rag.search(test_query_3, k=3)
    print(f"Search results for: '{test_query_3}'")
    for res in search_results_3:
        print(f"  Distance: {res['distance']:.4f} - Source Type: {res['source_info']['type']}")
        print(f"  Text: {res['text']}\n")