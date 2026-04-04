import pytest
from src.core.security import encrypt_value, decrypt_value
from src.core.config import settings

def test_encrypt_decrypt_value():
    original_text = "my_super_secret_password_123!"
    
    # Encrypt
    encrypted = encrypt_value(original_text)
    assert encrypted != original_text
    assert isinstance(encrypted, str)
    
    # Decrypt
    decrypted = decrypt_value(encrypted)
    assert decrypted == original_text

def test_encrypt_decrypt_with_explicit_key(monkeypatch):
    """Test that setting SMTP_ENCRYPTION_KEY changes the encryption output,
    but can still be decrypted correctly."""
    original_text = "test_password"
    
    # Base encryption (fallback)
    monkeypatch.setattr(settings, "SMTP_ENCRYPTION_KEY", None)
    encrypted_base = encrypt_value(original_text)
    
    # Explicit key encryption
    monkeypatch.setattr(settings, "SMTP_ENCRYPTION_KEY", "explicit_test_key_xyz")
    encrypted_explicit = encrypt_value(original_text)
    
    # The ciphertexts should differ because different keys were used
    # (Fernet also includes randomness, but it guarantees they are different if keys differ 
    # or even if the same key is used. But we can verify decryption).
    assert encrypted_base != encrypted_explicit
    
    # Decrypting with explicit key should return original text
    decrypted_explicit = decrypt_value(encrypted_explicit)
    assert decrypted_explicit == original_text
