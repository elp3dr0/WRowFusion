import pytest
from collections import Counter

from src.s4if import MEMORY_MAP, SIZE_MAP, SIZE_PARSE_MAP  # adjust import path as needed

def test_memory_map_has_unique_addresses():
    """Ensure all addresses in MEMORY_MAP are unique."""
    addresses = list(MEMORY_MAP.keys())
    counts = Counter(addresses)
    duplicates = [addr for addr, count in counts.items() if count > 1]
    assert not duplicates, f"Duplicate addresses found in MEMORY_MAP: {duplicates}"

def test_memory_map_entries_have_valid_size_map_size():
    """Ensure every entry in MEMORY_MAP refers to a valid size defined in SIZE_MAP."""
    for address, entry in MEMORY_MAP.items():
        size = entry.get("size")
        assert size in SIZE_MAP, f"Size '{size}' for address '{address}' not found in SIZE_MAP"

def test_memory_map_entries_have_valid_size_parse_map_size():
    """Ensure every entry in MEMORY_MAP refers to a valid size defined in SIZE_PARSE_MAP."""
    for address, entry in MEMORY_MAP.items():
        size = entry.get("size")
        assert size in SIZE_PARSE_MAP, f"Size '{size}' for address '{address}' not found in SIZE_PARSE_MAP"

def test_memory_map_has_required_fields():
    """Each MEMORY_MAP entry should include at least 'type', 'size' and 'base'."""
    for address, entry in MEMORY_MAP.items():
        assert 'type' in entry, f"Missing 'type' for address '{address}'"
        assert 'size' in entry, f"Missing 'size' for address '{address}'"
        assert 'base' in entry, f"Missing 'base' for address '{address}'"

def test_size_map_entries_have_request_and_response_prefixes():
    """Ensure each size definition in SIZE_MAP includes both request and response prefixes."""
    for size, entry in SIZE_MAP.items():
        for key in ('request', 'response'):
            assert key in entry, f"Missing '{key}' prefix for size '{size}'"
            assert isinstance(entry[key], str), f"'{key}' prefix for size '{size}' must be a string"

def test_size_map_prefixes_are_unique():
    """Make sure request/response prefixes are unique to prevent command collisions."""
    for key in ('request', 'response'):
        prefixes = [entry[key] for entry in SIZE_MAP.values()]
        assert len(prefixes) == len(set(prefixes)), f"Duplicate {key} prefixes found in SIZE_MAP"

def test_size_map_has_request_and_response_keys():
    """Ensure each entry in SIZE_MAP has both 'request' and 'response' keys."""
    for size, entry in SIZE_MAP.items():
        assert 'request' in entry, f"Missing 'request' key for size '{size}'"
        assert isinstance(entry['request'], str), f"Request prefix for size '{size}' must be a string"
        assert 'response' in entry, f"Missing 'response' key for size '{size}'"
        assert isinstance(entry['response'], str), f"Response prefix for size '{size}' must be a string"