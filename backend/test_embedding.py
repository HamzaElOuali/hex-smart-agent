from app.embedding import create_weaviate_schema, store_chunks_in_weaviate

class DummyDoc:
    def __init__(self):
        self.title = "Sample Title"
        self.filename = "dummy.txt"
        self.description = "Un document fictif pour test d'embedding"
        self.role = "user"
        self.content = """
        This is a dummy text. It simulates a real document to test the embedding and chunking process.
        Each sentence will be processed and split into smaller units, then sent to the SentenceTransformer model.
        """

# Étape 1 – Créer le schéma dans Weaviate
create_weaviate_schema()

# Étape 2 – Créer un faux document et le stocker
dummy_doc = DummyDoc()
store_chunks_in_weaviate(dummy_doc)
