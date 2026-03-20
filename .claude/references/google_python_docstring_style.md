# ✅ Google Python Style Guide — Comments & Docstrings (Condensed, LLM-Friendly)

## 1. General Principles
- Write comments **only when necessary**
- Prefer **self-explanatory code over comments**
- Keep comments **updated and accurate**
- Use **complete sentences**, proper grammar

## 2. Comments

### 2.1 Inline Comments
- Use **sparingly**
- Only for **non-obvious logic**

```python
result = x * y  # Area calculation (not obvious in context)
```

### 2.2 Block Comments
- Place above the code they describe
- Indent at the same level
- Use full sentences

```python
# We retry because the API is eventually consistent.
# Without this, transient failures would break the flow.
response = fetch_data()
```

### 2.3 When NOT to Comment
Avoid redundant comments:

```python
# BAD
x = x + 1  # Increment x
```

### 2.4 Prefer Docstrings over Comments
If describing a function/class → **use a docstring instead**

## 3. Docstrings (Core Rules)

### 3.1 When Required
Write docstrings for:
- Public modules
- Public classes
- Public functions/methods

Optional for:
- Private/internal helpers (if obvious)

### 3.2 High-Level Rules
- Triple quotes: `"""Docstring"""`
- First line = **one-line summary**
- Focus on **what**, not how
- Be concise but complete

## 4. Docstring Structure (Google Style)

### 4.1 Minimal Example

```python
def add(a: int, b: int) -> int:
    """Returns the sum of two numbers."""
```

### 4.2 Full Structured Example

```python
def fetch_user(user_id: int) -> dict:
    """Fetches a user from the database.

    Retrieves user information based on the provided ID.

    Args:
        user_id: unique identifier of the user

    Returns:
        user data

    Raises:
        ValueError: if the user_id is invalid
    """
```

👉 Key sections:
- Summary line
- Optional description
- `Args`
- `Returns`
- `Raises`

### 4.3 Formatting Rules
- Section headers end with `:`
- Indented content under each section
- Argument format:

```
name: description
```

## 5. Special Cases

### 5.1 One-liners
Use for trivial functions:

```python
def is_even(n: int) -> bool:
    """Returns True if n is even."""
```

### 5.2 Classes

```python
class BankAccount:
    """Represents a bank account.

    Handles deposits, withdrawals, and balance tracking.
    """
```

### 5.3 Override Methods

```python
def method(self):
    """See base class."""
```

### 5.4 Module Docstrings

```python
"""Utility functions for processing user data."""
```

## 6. What to Document

Document:
- Inputs (meaning of parameters)
- Outputs
- Exceptions
- Side effects (if any)

Do NOT document:
- Implementation details
- Obvious behaviour

## 7. Common Anti-Patterns

### ❌ Too verbose
```python
"""This function takes a number and returns its square by multiplying it by itself."""
```

### ✅ Better
```python
"""Returns the square of a number."""
```

### ❌ Implementation-focused
```python
"""Loops through list and appends values."""
```

### ✅ Behaviour-focused
```python
"""Filters valid items from the input list."""
```

## 8. LLM-Friendly Notes

- Structure is **predictable → good for parsing**
- Use consistent section headers (`Args`, `Returns`, `Raises`)
- Keep descriptions short and atomic
- Avoid narrative text
- Prefer consistent formatting across all docstrings
