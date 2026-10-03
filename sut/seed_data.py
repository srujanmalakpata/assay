"""Deterministic seed catalogue and demo account.

The values never change between runs so that smoke tests can rely on them
(for example "searching 'austen' returns exactly two books").
"""

from __future__ import annotations

from typing import NamedTuple


class SeedBook(NamedTuple):
    isbn: str
    title: str
    author: str
    price_cents: int
    stock: int


DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-password"

SEED_BOOKS: tuple[SeedBook, ...] = (
    SeedBook("9780000000001", "Pride and Prejudice", "Jane Austen", 1299, 40),
    SeedBook("9780000000002", "Emma", "Jane Austen", 1199, 40),
    SeedBook("9780000000003", "Moby-Dick", "Herman Melville", 1599, 40),
    SeedBook("9780000000004", "Frankenstein", "Mary Shelley", 999, 40),
    SeedBook("9780000000005", "Dracula", "Bram Stoker", 1099, 40),
    SeedBook("9780000000006", "Great Expectations", "Charles Dickens", 1399, 40),
    SeedBook("9780000000007", "A Tale of Two Cities", "Charles Dickens", 1299, 40),
    SeedBook("9780000000008", "Middlemarch", "George Eliot", 1699, 40),
    SeedBook("9780000000009", "Jane Eyre", "Charlotte Bronte", 1199, 40),
    SeedBook("9780000000010", "Wuthering Heights", "Emily Bronte", 1099, 40),
    SeedBook("9780000000011", "The Odyssey", "Homer", 1499, 40),
    SeedBook("9780000000012", "War and Peace", "Leo Tolstoy", 2499, 40),
    SeedBook("9780000000013", "Anna Karenina", "Leo Tolstoy", 1999, 40),
    SeedBook("9780000000014", "Crime and Punishment", "Fyodor Dostoevsky", 1499, 40),
    SeedBook("9780000000015", "The Count of Monte Cristo", "Alexandre Dumas", 1899, 40),
    SeedBook("9780000000016", "Don Quixote", "Miguel de Cervantes", 2199, 40),
    SeedBook("9780000000017", "Little Women", "Louisa May Alcott", 1099, 40),
    SeedBook("9780000000018", "The Time Machine", "H. G. Wells", 899, 40),
    SeedBook("9780000000019", "Treasure Island", "Robert Louis Stevenson", 999, 40),
    SeedBook("9780000000020", "The Last Copy", "Rare Press", 4999, 1),
)
