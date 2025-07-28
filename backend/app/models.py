from sqlalchemy import Column, Integer, String, Text
from .database import Base

class Document(Base):
    __tablename__ = "document"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    description = Column(Text)
    role = Column(String, nullable=False)
    content = Column(Text)
