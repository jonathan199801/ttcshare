from app.tiktok_api import compute_chunk_plan, generate_pkce


def test_pkce_lengths_and_hex():
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 64
    int(challenge, 16)


def test_small_file_one_chunk():
    size = 4 * 1024 * 1024
    chunk, count = compute_chunk_plan(size)
    assert chunk == size
    assert count == 1


def test_large_file_multiple_chunks():
    size = 100 * 1024 * 1024
    chunk, count = compute_chunk_plan(size)
    assert chunk == 32 * 1024 * 1024
    assert count == size // chunk
