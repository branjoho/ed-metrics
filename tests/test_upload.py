import pytest
from parse_pdf import parse_metrics, ParseError

REAL_PDF = "/Users/branjoho/Documents/Attending metrics/2_2026 - ED Provider Metrics.pdf"

def test_parse_returns_dict():
    result = parse_metrics(REAL_PDF)
    assert isinstance(result, dict)

def test_parse_required_keys():
    result = parse_metrics(REAL_PDF)
    required = ['month', 'year', 'patients', 'discharge_los_me', 'discharge_los_peers']
    for key in required:
        assert key in result, f"Missing key: {key}"

def test_parse_numeric_values():
    result = parse_metrics(REAL_PDF)
    assert isinstance(result['patients'], (int, type(None)))
    assert isinstance(result['discharge_los_me'], (float, type(None)))

def test_parse_wrong_file_raises():
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(b'%PDF-1.4 not a real metrics file')
        path = f.name
    try:
        with pytest.raises(ParseError):
            parse_metrics(path)
    finally:
        os.unlink(path)

def test_parse_nonexistent_file_raises():
    with pytest.raises(Exception):
        parse_metrics('/nonexistent/path/file.pdf')
